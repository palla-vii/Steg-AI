# src/ml_module.py
#
# Random Forest block classifier for ML-guided LSB embedding.
#
# Features extracted per 8x8 block (5 total):
#   1. std           — spread of pixel values
#   2. entropy       — information density (Shannon)
#   3. edge_density  — Laplacian variance (sharpness / edge strength)
#   4. mean_gradient — average absolute gradient magnitude
#   5. local_contrast — max − min pixel range
#
# A block is "safe" for embedding if it has high texture/complexity,
# making the ±1 LSB change imperceptible.
#
# Performance note:
#   Use predict_batch(feature_matrix) for bulk classification — it calls
#   model.predict() once for the entire image, avoiding per-block overhead.

from sklearn.ensemble import RandomForestClassifier
import numpy as np

model = RandomForestClassifier(n_estimators=50, random_state=42)
_model_trained = False

N_FEATURES = 5


def extract_features(block):
    """
    Extract a 5-element feature vector from an 8x8 image block.
    Block can be 2D (grayscale) or 3D (colour) — always flattened first.

    Returns: [std, entropy, edge_density, mean_gradient, local_contrast]
    """
    flat = block.flatten().astype(np.float64)

    # 1. Standard deviation
    std_val = float(np.std(flat))

    # 2. Shannon entropy
    hist = np.histogram(flat, bins=32, range=(0, 256))[0]
    total = hist.sum()
    if total > 0:
        prob = hist / total
        prob = prob[prob > 0]
        entropy_val = float(-np.sum(prob * np.log2(prob)))
    else:
        entropy_val = 0.0

    # 3. Edge density — Laplacian variance (works on 2D slice)
    gray = block[:, :, 0] if block.ndim == 3 else block
    gray_f = gray.astype(np.float64)
    # Simple Laplacian via finite differences
    lap = (
        -4 * gray_f[1:-1, 1:-1]
        + gray_f[:-2, 1:-1]
        + gray_f[2:, 1:-1]
        + gray_f[1:-1, :-2]
        + gray_f[1:-1, 2:]
    )
    edge_density = float(np.var(lap)) if lap.size > 0 else 0.0

    # 4. Mean gradient magnitude (Sobel-like)
    gy = np.diff(gray_f, axis=0)   # vertical differences
    gx = np.diff(gray_f, axis=1)   # horizontal differences
    mean_gradient = float(
        (np.mean(np.abs(gy)) + np.mean(np.abs(gx))) / 2
    ) if gy.size > 0 and gx.size > 0 else 0.0

    # 5. Local contrast (dynamic range of block)
    local_contrast = float(flat.max() - flat.min())

    return [std_val, entropy_val, edge_density, mean_gradient, local_contrast]


def train_model():
    """
    Train the Random Forest on synthetic image block data.

    Generates three types of blocks to teach the model to distinguish:
      - Textured blocks (high std, entropy, edges)   → label 1 (safe)
      - Gradient blocks (moderate complexity)        → label 1 (safe)
      - Flat/uniform blocks (very low variance)      → label 0 (unsafe)

    Using synthetic data keeps startup fast while the feature set is
    rich enough to generalise to real images.
    """
    global _model_trained
    if _model_trained:
        return

    np.random.seed(42)
    X, y = [], []

    for _ in range(600):
        # High-texture block (safe) — random noise-like content
        block = np.random.randint(0, 256, (8, 8), dtype=np.uint8)
        X.append(extract_features(block))
        y.append(1)

    for _ in range(300):
        # Gradient block (safe) — smooth ramp with noise
        ramp = np.tile(np.linspace(0, 200, 8), (8, 1)).astype(np.uint8)
        ramp += np.random.randint(0, 30, (8, 8), dtype=np.uint8)
        ramp = np.clip(ramp, 0, 255).astype(np.uint8)
        X.append(extract_features(ramp))
        y.append(1)

    for _ in range(600):
        # Flat/uniform block (unsafe) — near-constant pixel values
        base = np.random.randint(0, 256)
        block = np.full((8, 8), base, dtype=np.uint8)
        block = np.clip(
            block + np.random.randint(-5, 6, (8, 8)), 0, 255
        ).astype(np.uint8)
        X.append(extract_features(block))
        y.append(0)

    model.fit(X, y)
    _model_trained = True
    print(f"[ML] Model trained on {len(X)} samples with {N_FEATURES} features.")


# Train on first import
train_model()


def predict_batch(feature_matrix):
    """
    Classify a batch of blocks in a single model.predict() call.

    Args:
        feature_matrix: list or np.ndarray of shape (N, N_FEATURES)
    Returns:
        np.ndarray of shape (N,) with 1 = safe, 0 = unsafe
    """
    return model.predict(feature_matrix)


def is_safe_block(block):
    """Single-block convenience wrapper (used in tests / one-off calls)."""
    return model.predict([extract_features(block)])[0] == 1