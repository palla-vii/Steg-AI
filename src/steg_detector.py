# src/steg_detector.py
#
# Neural Steganalysis Detector — v2
#
# v1 problem: synthetic "clean" training images were over-smoothed (Gaussian
# blobs), so the model learned "high LSB autocorrelation = clean". Real photos
# have naturally low LSB autocorrelation (sensor noise, JPEG, texture), so
# the model falsely flagged everything as stego.
#
# v2 fixes:
#   1. Realistic training images — multi-scale texture + fine sensor noise,
#      producing LSB statistics that match real photos.
#   2. Better features — chi-square on POV pairs, LSB run-length entropy,
#      and residual kurtosis. These measure cryptographic randomness vs.
#      natural noise, not smooth vs. textured.
#   3. Embed LARGE payloads during training (40–80 % capacity) so the
#      statistical signal is clear.
#   4. More conservative thresholds (0.50 / 0.75) to avoid false positives
#      on natural images.
#
# Limitation (by design): very short messages fill only a tiny fraction of
# pixels, making them statistically undetectable — this is the goal of
# steganography. The detector is meaningful for medium-to-large payloads.

import cv2
import numpy as np
from sklearn.neural_network import MLPClassifier

TARGET_SIZE = (128, 128)

_detector = MLPClassifier(
    hidden_layer_sizes=(64, 32),
    activation="relu",
    random_state=42,
    max_iter=600,
    early_stopping=True,
    validation_fraction=0.15,
)
_detector_trained = False


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def _chi_square_pov(gray):
    """
    Chi-square test on PoV (Pairs of Values) pairs.

    For each even value 2k, count freq(2k) and freq(2k+1).
    Clean image  → these counts differ naturally (large chi2).
    Stego image  → AES bits equalise them toward 50/50 (small chi2).

    We normalise by image size and return the mean per-pair chi2.
    Lower value → more uniform → more likely stego.
    """
    flat = gray.flatten().astype(np.int32)
    hist = np.bincount(flat, minlength=256).astype(np.float64)

    chi2_vals = []
    for k in range(128):
        n = hist[2 * k] + hist[2 * k + 1]
        if n < 2:
            continue
        expected = n / 2.0
        chi2_pair = ((hist[2 * k] - expected) ** 2 +
                     (hist[2 * k + 1] - expected) ** 2) / expected
        chi2_vals.append(chi2_pair)

    return float(np.mean(chi2_vals)) if chi2_vals else 0.0


def _lsb_run_entropy(gray):
    """
    Entropy of run-lengths in the LSB bit sequence.
    Cryptographic (AES) bits → very short runs → high run-length entropy.
    Natural noise → slightly longer runs → lower run-length entropy.
    """
    lsb  = (gray.flatten() & 1).astype(np.uint8)
    runs = []
    cur_len = 1
    for i in range(1, len(lsb)):
        if lsb[i] == lsb[i - 1]:
            cur_len += 1
        else:
            runs.append(cur_len)
            cur_len = 1
    runs.append(cur_len)

    runs = np.array(runs, dtype=np.float64)
    max_run = int(runs.max()) if len(runs) > 0 else 1
    counts  = np.bincount(runs.astype(np.int32), minlength=max_run + 1)[1:]
    total   = counts.sum()
    if total == 0:
        return 0.0
    probs = counts / total
    probs = probs[probs > 0]
    return float(-np.sum(probs * np.log2(probs)))


def _residual_stats(gray):
    """
    Statistics on the high-pass noise residual.
    """
    img_f    = gray.astype(np.float64)
    blurred  = cv2.GaussianBlur(img_f, (5, 5), 1.0)
    residual = (img_f - blurred).flatten()

    res_std = float(np.std(residual))
    std = np.std(residual)
    if std > 1e-6:
        kurtosis = float(np.mean(((residual - np.mean(residual)) / std) ** 4))
    else:
        kurtosis = 3.0

    # Entropy of quantised residual
    q = np.round(residual).astype(np.int32)
    _, counts = np.unique(q, return_counts=True)
    probs = counts / counts.sum()
    res_entropy = float(-np.sum(probs * np.log2(probs + 1e-12)))

    return [res_std, kurtosis, res_entropy]


def _lsb_basic(gray):
    """
    Two simple LSB statistics less sensitive to image content.
    """
    lsb = (gray & 1).astype(np.float64)

    # Mean (random payload → 0.5)
    lsb_mean = float(np.mean(lsb))

    # Diagonal autocorrelation (less content-sensitive than H/V)
    diag_corr = float(np.mean(lsb[:-1, :-1] == lsb[1:, 1:]))

    return [lsb_mean, diag_corr]


def extract_features(img_bgr):
    """
    Full 7-feature vector from a BGR numpy array.
    [chi2_pov, run_entropy, res_std, kurtosis, res_entropy, lsb_mean, diag_corr]
    """
    resized = cv2.resize(img_bgr, TARGET_SIZE)
    gray    = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

    return (
        [_chi_square_pov(gray), _lsb_run_entropy(gray)] +
        _residual_stats(gray) +
        _lsb_basic(gray)
    )   # 7 features total


def _features_from_path(path):
    img = cv2.imread(path)
    if img is None:
        raise ValueError(f"[DETECTOR] Cannot read image: {path}")
    return extract_features(img)


# ---------------------------------------------------------------------------
# Synthetic training data
# ---------------------------------------------------------------------------

def _make_realistic_clean(H, W, rng):
    """
    Generate a synthetic image with realistic multi-scale texture.

    Strategy: combine a random base colour, medium-frequency structure
    (simulates large image regions), and fine-grain sensor-like noise.
    This produces LSB statistics similar to real photographs — NOT the
    heavily-smoothed blobs that caused v1 to fail.
    """
    base = float(rng.randint(20, 220))
    img  = np.full((H, W), base, dtype=np.float64)

    # Medium-scale structure (edges, gradients, large blobs)
    for sigma in rng.choice([4, 8, 16, 24], size=2, replace=False):
        blob   = rng.randn(H, W) * rng.uniform(20, 60)
        smooth = cv2.GaussianBlur(blob, (0, 0), float(sigma))
        img   += smooth

    # Fine-grain sensor noise (this is what makes real image LSBs non-trivial)
    img += rng.normal(0, rng.uniform(4, 14), (H, W))

    return np.clip(img, 0, 255).astype(np.uint8)


def _embed_lsb(gray, bits):
    """Sequential LSB embedding (matches our embed_data pipeline)."""
    flat     = gray.flatten().copy()
    n        = min(len(bits), len(flat))
    flat[:n] = (flat[:n] & 0xFE) | bits[:n]
    return flat.reshape(gray.shape)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_detector():
    """
    Train the MLP on realistic synthetic clean/stego pairs.

    Key differences from v1:
      - Clean images use multi-scale texture + fine noise (not just Gaussian blur).
      - Stego images embed 40–80 % of capacity with AES-like random bits.
      - Larger embedding fraction gives a clear statistical signal.
    """
    global _detector_trained
    if _detector_trained:
        return

    rng  = np.random.RandomState(42)
    H, W = TARGET_SIZE
    X, y = [], []

    for _ in range(1000):
        clean = _make_realistic_clean(H, W, rng)

        # --- Clean sample ---
        clean_bgr = cv2.cvtColor(clean, cv2.COLOR_GRAY2BGR)
        X.append(extract_features(clean_bgr))
        y.append(0)

        # --- Stego sample: 40–80 % of capacity ---
        capacity    = H * W
        payload_len = rng.randint(int(0.40 * capacity), int(0.80 * capacity))
        bits        = rng.randint(0, 2, payload_len, dtype=np.uint8)
        stego       = _embed_lsb(clean, bits)
        stego_bgr   = cv2.cvtColor(stego, cv2.COLOR_GRAY2BGR)
        X.append(extract_features(stego_bgr))
        y.append(1)

    _detector.fit(X, y)
    _detector_trained = True
    print(f"[DETECTOR] v2 trained — {len(X)} samples, 7 features, MLP(64,32).")


# Train on first import
train_detector()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyse(image_path: str) -> dict:
    """
    Run neural steganalysis on an image file.

    Thresholds (conservative to minimise false positives on clean images):
      < 0.50 → NOT DETECTED
      0.50 – 0.75 → SUSPECTED
      > 0.75 → DETECTED

    Note: short messages occupy <1 % of pixels — statistically undetectable
    by design. The detector is meaningful for medium-to-large payloads.
    """
    feats   = _features_from_path(image_path)
    proba   = _detector.predict_proba([feats])[0]  # [P(clean), P(stego)]
    p_stego = float(proba[1])
    pct     = round(p_stego * 100, 1)

    if p_stego < 0.50:
        verdict     = "NOT DETECTED"
        level       = "safe"
        explanation = (
            "The neural detector found no significant statistical evidence of "
            "hidden data. LSB patterns, noise residuals, and chi-square analysis "
            "are consistent with a natural, unmodified image."
        )
    elif p_stego < 0.75:
        verdict     = "SUSPECTED"
        level       = "warn"
        explanation = (
            "The neural detector found mild statistical anomalies but could not "
            "confirm the presence of hidden data. This may indicate a short or "
            "partially embedded payload — message content remains encrypted and "
            "unreadable without the receiver's private key."
        )
    else:
        verdict     = "DETECTED"
        level       = "danger"
        explanation = (
            "The neural detector identified statistical patterns inconsistent "
            "with a natural image. Chi-square and residual analysis suggest a "
            "significant LSB payload. Consider using a larger carrier image to "
            "distribute the payload more sparsely for better stealth."
        )

    return {
        "detection_prob": p_stego,
        "confidence_pct": pct,
        "verdict":        verdict,
        "verdict_level":  level,
        "explanation":    explanation,
    }
