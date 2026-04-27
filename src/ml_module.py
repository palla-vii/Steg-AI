# src/ml_module.py

from sklearn.ensemble import RandomForestClassifier
import numpy as np

model = RandomForestClassifier(n_estimators=50, random_state=42)
_model_trained = False

def extract_features(block):
    """
    Extract features from an image block.
    Block can be 2D (grayscale) or 3D (color). We flatten it first.
    Returns [std, variance] as a consistent 2-element feature vector.
    """
    flat = block.flatten().astype(np.float64)
    std_val = np.std(flat)
    var_val = np.var(flat)
    return [std_val, var_val]

def train_dummy_model():
    """
    Train a simple heuristic model to classify image blocks as
    'safe' (high entropy/texture) or 'unsafe' (flat/uniform).
    Training data uses 2D (8x8) blocks consistent with how
    the model will be predict-called at runtime.
    """
    global _model_trained
    if _model_trained:
        return

    X = []
    y = []

    np.random.seed(42)
    for _ in range(1000):
        # Generate a random 8x8 block (simulate grayscale patch)
        block = np.random.randint(0, 256, (8, 8), dtype=np.uint8)
        features = extract_features(block)
        # Label: 1 (safe to embed) if std > 30, else 0
        label = 1 if features[0] > 30 else 0
        X.append(features)
        y.append(label)

    model.fit(X, y)
    _model_trained = True
    print("[ML] Model trained successfully.")

# Train on first import
train_dummy_model()

def is_safe_block(block):
    """
    Classify whether an image block is a safe region for LSB embedding.
    Returns True if the block has enough texture/complexity.
    """
    features = extract_features(block)
    return model.predict([features])[0] == 1