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
matplotlib.use('Agg')  # Non-interactive backend — prevents crashes on headless servers
import matplotlib.pyplot as plt
from src.ml_module import is_safe_block

DELIMITER   = b"##STEGAI##"   # Unique end-of-payload marker
_REF_SIZE   = (512, 512)      # Reference size used ONLY for metric comparison


# ---------------------------------------------------------------------------
# Capacity helpers
# ---------------------------------------------------------------------------

def get_capacity_bits(img):
    """Return how many bits the image can carry (one bit per channel byte)."""
    return img.shape[0] * img.shape[1] * img.shape[2]   # H × W × C


def get_capacity_bytes(img):
    return get_capacity_bits(img) // 8


# ---------------------------------------------------------------------------
# Block analysis helpers (used by get_safe_blocks)
# ---------------------------------------------------------------------------

def get_block_entropy(block):
    """Shannon entropy of a block."""
    hist  = np.histogram(block.flatten(), bins=256, range=(0, 255))[0]
    total = hist.sum()
    if total == 0:
        return 0.0
    prob = hist / total
    prob = prob[prob > 0]
    return float(-np.sum(prob * np.log2(prob)))


def get_safe_blocks(img, block_size=8, threshold=4.0, max_blocks=200):
    """
    Return a list of (row, col) top-left corners of high-texture 8×8 blocks
    that the ML model classifies as safe for embedding.
    """
    h, w = img.shape[:2]
    safe_blocks = []

    for i in range(0, h - block_size + 1, block_size):
        for j in range(0, w - block_size + 1, block_size):
            block = img[i:i + block_size, j:j + block_size]

            if block.shape[0] != block_size or block.shape[1] != block_size:
                continue

            # Fast pre-filter: skip uniform/low-variance blocks
            if np.var(block) < 20:
                continue

            # ML safety check (uses flattened features — works for 2D or 3D)
            if is_safe_block(block):
                safe_blocks.append((i, j))

            if len(safe_blocks) >= max_blocks:
                print(f"[INFO] Hit block limit at {len(safe_blocks)} blocks")
                return safe_blocks

    print(f"[INFO] Safe blocks found: {len(safe_blocks)}")
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
    Embed `data` (bytes) into `image_path` using LSB steganography.
    Saves the resulting stego image to `output_path`.

    The image is processed at its **native resolution** (no resize).
    Capacity is computed dynamically from actual pixel dimensions.

    Steps:
      1. Read image at native resolution.
      2. Append delimiter so extraction knows where data ends.
      3. Convert payload to a binary string (1 bit per character).
      4. Verify the image has enough capacity.
      5. Embed each bit into the LSB of successive channel bytes.
      6. Write out the modified image as PNG (lossless).
    """
    print("[EMBED] Starting embedding process...")

    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not read image file: {image_path}")

    # Work on native resolution — NO resize
    img = img.astype(np.uint8)
    h, w, c = img.shape
    print(f"[EMBED] Image shape: {img.shape}  ({h}×{w}, {c} channels)")

    payload     = data + DELIMITER
    binary_str  = ''.join(format(byte, '08b') for byte in payload)
    total_bits  = len(binary_str)
    print(f"[EMBED] Payload size: {len(payload)} bytes ({total_bits} bits)")

    flat_img      = img.flatten()
    capacity_bits = len(flat_img)

    if total_bits > capacity_bits:
        raise ValueError(
            f"Message too large to embed: needs {total_bits} bits but image "
            f"capacity is only {capacity_bits} bits "
            f"({capacity_bits // 8} bytes). Shorten your message or use a larger image."
        )

    # LSB embedding
    for i, bit in enumerate(binary_str):
        flat_img[i] = (flat_img[i] & 0xFE) | int(bit)

    stego_img = flat_img.reshape(img.shape).astype(np.uint8)

    if not cv2.imwrite(output_path, stego_img):
        raise IOError(f"Failed to write stego image to: {output_path}")

    print(f"[EMBED] ✅ Embedding complete! Saved to {output_path}")


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
            print(f"[EXTRACT] ✅ Delimiter found — extracted {len(result)} bytes")
            return result

    print(f"[EXTRACT] ⚠️  No delimiter found. Returning raw data ({len(data)} bytes).")
    return bytes(data)