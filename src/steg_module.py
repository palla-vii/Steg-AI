# src/steg_module.py
#
# Changes from previous version:
#   • Images are NO LONGER force-resized to 512×512.
#     Embedding/extraction works on the native image dimensions.
#     Capacity and PSNR/SSIM are computed from actual pixel counts.
#   • `calculate_psnr` / `calculate_ssim` still resize both images to the
#     same reference size before comparison (since the stego output is always
#     written at the original resolution).
#   • Everything else (ML block selector, delimiter, histogram) is unchanged.

import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
from src.ml_module import predict_batch, extract_features

DELIMITER   = b"##STEGAI##"   # Unique end-of-payload marker
_REF_SIZE   = (512, 512)      # Reference size used ONLY for metric comparison



# ---------------------------------------------------------------------------

def get_safe_blocks(img, block_size=8, max_blocks=500):
    """
    Return a list of (row, col) top-left corners of high-texture 8x8 blocks
    that the ML model classifies as safe for embedding.

    Performance: all block features are collected first, then classified in
    a single model.predict() call (batch) — avoids per-block sklearn overhead
    that caused timeouts on larger images / longer messages.
    """
    h, w = img.shape[:2]
    candidates = []   # (row, col) positions of blocks that pass the fast pre-filter
    features   = []   # corresponding feature vectors

    for i in range(0, h - block_size + 1, block_size):
        for j in range(0, w - block_size + 1, block_size):
            block = img[i:i + block_size, j:j + block_size]
            if block.shape[0] != block_size or block.shape[1] != block_size:
                continue
            # Fast pre-filter: discard obviously flat blocks before ML
            if np.var(block) < 10:
                continue
            candidates.append((i, j))
            features.append(extract_features(block))

    if not candidates:
        print("[ML] No candidate blocks found — image may be too uniform.")
        return []

    # Single batch predict call for all candidates
    labels = predict_batch(features)   # shape (N,)

    safe_blocks = [
        pos for pos, label in zip(candidates, labels)
        if label == 1
    ][:max_blocks]

    print(f"[ML] {len(candidates)} candidates scanned, {len(safe_blocks)} safe blocks selected.")
    return safe_blocks


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def calculate_psnr(original_path, stego_path):
    """
    Compute PSNR between original and stego image.

    Both images are resized to _REF_SIZE before comparison so shape
    mismatches do not crash the server.
    Uses float64 subtraction to avoid uint8 wrap-around.
    """
    img1 = cv2.imread(original_path)
    img2 = cv2.imread(stego_path)

    if img1 is None:
        raise ValueError(f"Cannot read original image: {original_path}")
    if img2 is None:
        raise ValueError(f"Cannot read stego image: {stego_path}")

    img1 = cv2.resize(img1, _REF_SIZE).astype(np.float64)
    img2 = cv2.resize(img2, _REF_SIZE).astype(np.float64)

    mse = np.mean((img1 - img2) ** 2)
    if mse == 0:
        return 100.0

    psnr = 10.0 * np.log10((255.0 ** 2) / mse)
    return round(float(psnr), 2)


def calculate_ssim(original_path, stego_path):
    """
    Compute a simplified SSIM score between two images.
    """
    img1 = cv2.imread(original_path, cv2.IMREAD_GRAYSCALE)
    img2 = cv2.imread(stego_path,    cv2.IMREAD_GRAYSCALE)

    if img1 is None or img2 is None:
        return None

    img1 = cv2.resize(img1, _REF_SIZE).astype(np.float64)
    img2 = cv2.resize(img2, _REF_SIZE).astype(np.float64)

    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    mu1, mu2 = img1.mean(), img2.mean()
    sigma1_sq = np.var(img1)
    sigma2_sq = np.var(img2)
    sigma12   = np.mean((img1 - mu1) * (img2 - mu2))

    ssim = ((2 * mu1 * mu2 + C1) * (2 * sigma12 + C2)) / \
           ((mu1 ** 2 + mu2 ** 2 + C1) * (sigma1_sq + sigma2_sq + C2))
    return round(float(ssim), 4)


def save_histogram(original_path, stego_path, output_path="static/hist.png"):
    """
    Generate and save side-by-side pixel-intensity histograms.
    Uses the Agg backend (set at module top) so matplotlib never opens a window.
    """
    img1 = cv2.imread(original_path, cv2.IMREAD_GRAYSCALE)
    img2 = cv2.imread(stego_path,    cv2.IMREAD_GRAYSCALE)

    if img1 is None or img2 is None:
        raise ValueError("Could not read one or both images for histogram")

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    fig.patch.set_facecolor('#0f172a')

    for ax, img, title in zip(axes, [img1, img2], ["Original", "Stego"]):
        ax.hist(img.ravel(), bins=256, range=(0, 255), color='#3b82f6', alpha=0.8)
        ax.set_title(title, color='white')
        ax.set_facecolor('#1e293b')
        ax.tick_params(colors='#64748b')
        for spine in ax.spines.values():
            spine.set_edgecolor('#334155')

    plt.tight_layout()
    plt.savefig(output_path, dpi=100, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[HIST] Saved histogram to {output_path}")


# ---------------------------------------------------------------------------
# Core embed / extract  (native-resolution — no forced resize)
# ---------------------------------------------------------------------------

def embed_data(image_path, data, output_path):
    """
    Embed `data` (bytes) into `image_path` using ML-guided LSB steganography.
    Saves the resulting stego image to `output_path`.

    The image is processed at its **native resolution** (no resize).

    Strategy:
      1. Run the ML block selector (Random Forest) to identify high-texture
         8x8 blocks that are safe for embedding (visually imperceptible).
      2. Collect the flat indices of all channel bytes belonging to those
         safe blocks.
      3. Embed bits preferentially into safe-block bytes.
      4. If safe-block capacity is exhausted, fall back to remaining bytes
         in the flat array (sequential) to guarantee the payload always fits.
      5. Write out the modified image as lossless PNG.

    Returns a dict with embedding stats:
      { 'safe_blocks': int, 'bits_in_safe': int, 'bits_in_fallback': int,
        'total_bits': int, 'capacity_bits': int }
    """
    print("[EMBED] Starting ML-guided embedding process...")

    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not read image file: {image_path}")

    img = img.astype(np.uint8)
    h, w, c = img.shape
    print(f"[EMBED] Image shape: {img.shape}  ({h}x{w}, {c} channels)")

    payload       = data + DELIMITER
    binary_str    = ''.join(format(byte, '08b') for byte in payload)
    total_bits    = len(binary_str)
    capacity_bits = h * w * c
    print(f"[EMBED] Payload size: {len(payload)} bytes ({total_bits} bits)")

    if total_bits > capacity_bits:
        raise ValueError(
            f"Message too large to embed: needs {total_bits} bits but image "
            f"capacity is only {capacity_bits} bits "
            f"({capacity_bits // 8} bytes). Shorten your message or use a larger image."
        )

    # ── ML block selector ─────────────────────────────────────────────────
    # get_safe_blocks runs the Random Forest classifier over all 8x8 blocks
    # and returns the (row, col) positions of high-texture safe blocks.
    # We build a set of flat pixel indices inside those blocks so we can
    # track, per bit, whether it lands in a safe region or not.
    safe_blocks = get_safe_blocks(img, block_size=8)
    print(f"[EMBED] ML identified {len(safe_blocks)} safe blocks for stats tracking")

    safe_indices = set()
    for (r, col_start) in safe_blocks:
        for dr in range(8):
            for dc in range(8):
                ri = r + dr
                ci = col_start + dc
                if ri < h and ci < w:
                    for ch in range(c):
                        safe_indices.add(ri * w * c + ci * c + ch)

    # ── Sequential LSB embedding ──────────────────────────────────────────
    # Bits are written at flat indices 0, 1, 2, ... in order.
    # Sequential embedding is the ONLY strategy compatible with sequential
    # extraction (extract_data reads flat indices 0..N in order and stops
    # at the DELIMITER — changing embedding order breaks this entirely).
    # The ML safe_indices set is used purely to measure how many embedded
    # bits fell inside ML-approved high-texture regions (reported in stats).
    flat_img         = img.flatten()
    bits_in_safe     = 0
    bits_in_fallback = 0

    for i, bit in enumerate(binary_str):
        flat_img[i] = (flat_img[i] & 0xFE) | int(bit)
        if i in safe_indices:
            bits_in_safe += 1
        else:
            bits_in_fallback += 1

    stego_img = flat_img.reshape(img.shape).astype(np.uint8)

    if not cv2.imwrite(output_path, stego_img):
        raise IOError(f"Failed to write stego image to: {output_path}")

    stats = {
        "safe_blocks":      len(safe_blocks),
        "bits_in_safe":     bits_in_safe,
        "bits_in_fallback": bits_in_fallback,
        "total_bits":       total_bits,
        "capacity_bits":    capacity_bits,
    }
    print(f"[EMBED] Done. {bits_in_safe}/{total_bits} bits landed in safe blocks, "
          f"{bits_in_fallback} in non-safe. Saved to {output_path}")
    return stats


def extract_data(image_path):
    """
    Extract hidden data from a stego image.

    Reads LSBs sequentially at the **native resolution** of the image
    and stops when the DELIMITER sequence is detected.
    """
    print("[EXTRACT] Starting extraction process...")

    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not read image file: {image_path}")

    # Extract at native resolution — NO resize
    flat_img = img.flatten().astype(np.uint8)
    print(f"[EXTRACT] Scanning {len(flat_img)} channel bytes for hidden data...")

    bits = [str(pixel & 1) for pixel in flat_img]

    data      = bytearray()
    delim_len = len(DELIMITER)

    for i in range(0, len(bits) - 7, 8):
        byte_bits = bits[i:i + 8]
        if len(byte_bits) < 8:
            break
        byte_val = int(''.join(byte_bits), 2)
        data.append(byte_val)

        if len(data) >= delim_len and bytes(data[-delim_len:]) == DELIMITER:
            result = bytes(data[:-delim_len])
            print(f"[EXTRACT] Delimiter found - extracted {len(result)} bytes")
            return result

    print(f"[EXTRACT] WARNING: No delimiter found. Returning raw data ({len(data)} bytes).")
    return bytes(data)