# StegAI — Improvement Roadmap

> Full audit of your Senior Design Project codebase. Covers general improvements, ML upgrades, and real AI integration ideas organized by effort.

---

## 🔍 Current State Summary

| Layer | What you have | Weakness |
|---|---|---|
| **Steganography** | LSB embedding on resized 512×512 image | Sequential LSB — statistically detectable |
| **ML** | Random Forest on `[std, variance]` features | Dummy training data (synthetic random blocks) — not real steg detection |
| **Encryption** | AES-256-CFB + ECC key gen | ECC keys regenerated on every server restart; never used in actual key exchange |
| **UI** | Flask + single-page HTML | No async, no real-time feedback, full page reload on every action |
| **Security** | `secure_filename`, file type check | No file size limit, AES key stored raw inside payload |

---

## 🛠️ General Code Improvements

### 1. Fix the ECC Key Exchange (Currently Broken)
The `ecc_module.py` generates keys and `derive_shared_key` exists — but is **never called**. The AES key is random and stored raw inside the payload. This defeats the purpose of ECC entirely.

**Fix:** Use ECDH properly — embed the sender's ephemeral public key in the stego payload so the receiver can derive the shared AES key.

```python
# What should happen (Ephemeral ECDH):
# 1. Sender generates ephemeral ECC key pair
# 2. Encrypts message with AES key = ECDH(sender_private, receiver_public)
# 3. Embeds: [magic][sender_pub_key_bytes][ciphertext] in the image
# 4. Receiver uses ECDH(receiver_private, sender_pub_key) to get the same AES key
```

### 2. Add a File Size Limit
Right now a user can upload a 100MB TIFF and crash the server.

```python
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB limit
```

### 3. Use AES-GCM Instead of AES-CFB
CFB mode provides confidentiality but **no integrity/authentication**. AES-GCM gives you both — an auth tag detects payload tampering before decryption.

```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
```

### 4. Stop Force-Resizing All Images to 512×512
This is lossy for large images and wastes capacity for small ones. Work on the original dimensions and compute capacity dynamically.

### 5. Async Processing with Background Jobs
Current: user waits for a full page POST. For large images this is a bad UX.

**Fix:** Use `threading` or `celery` + a `/status/<job_id>` polling endpoint so the UI can show real progress via Fetch API.

---

## 🤖 ML Improvements (Within Existing Stack)

### Current ML Problem
Your Random Forest is trained on **randomly generated synthetic blocks** — it will always give the same decision for any input. The threshold `std > 30` used for labeling is also applied directly in `is_safe_block`, making the model redundant (you're teaching the model to replicate a rule you already have).

### Fix 1: Train on REAL Image Blocks

```python
import glob, cv2, numpy as np

def build_training_data(image_folder):
    X, y = [], []
    for path in glob.glob(f"{image_folder}/*.png"):
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        for i in range(0, img.shape[0]-8, 8):
            for j in range(0, img.shape[1]-8, 8):
                block = img[i:i+8, j:j+8]
                features = extract_features(block)
                # label: 1 = safe to embed (high texture), 0 = risky (flat)
                label = 1 if np.std(block) > 30 else 0
                X.append(features); y.append(label)
    return X, y
```

### Fix 2: Add More Features — `[std, variance]` are Redundant
Variance = std², so you only have 1 unique feature. Add meaningful ones:

```python
def extract_features(block):
    flat = block.flatten().astype(np.float64)
    return [
        np.std(flat),                                               # texture
        get_block_entropy(block),                                   # information content
        np.mean(np.abs(np.diff(flat))),                             # local variation
        float(np.percentile(flat, 75) - np.percentile(flat, 25)),  # IQR
    ]
```

### Fix 3: Persist the Trained Model with joblib

```python
import joblib, os

MODEL_PATH = "models/rf_block_classifier.pkl"

def load_or_train():
    if os.path.exists(MODEL_PATH):
        return joblib.load(MODEL_PATH)
    model = train_real_model()
    os.makedirs("models", exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    return model
```

---

## 🧠 Real AI Integration Ideas

### Tier 1 — Easy (Add This Weekend)

#### A. Steganalysis — AI-Based Detection Tab
Add a second mode: **"Detect Hidden Data"** — upload any image, model predicts if it contains a hidden payload.

- Train binary classifier on clean images vs. stego versions
- Aggregate block-level features to image-level (mean, std of block stats)
- **Academic value:** Positions StegAI as both an embedding tool AND a detector — demonstrates you understand the adversarial game of steganography

```python
@app.route("/detect", methods=["POST"])
def detect():
    # Extract block-level features from whole image
    # Aggregate into image-level features
    # Predict: is_stego = detection_model.predict(image_features)
    return jsonify({"stego_probability": float(prob)})
```

#### B. AI Security Report Card
After embedding, show an AI-generated **"Security Report"** card with:
- Block coverage % (what % of pixels were used)
- Estimated detectability score (from your classifier)
- Recommended image type for this payload size

---

### Tier 2 — Medium (1–2 weeks)

#### C. Deep CNN Steganalysis (SRNet / YeNet)
Replace your Random Forest with a **CNN-based steganalysis detector** using PyTorch.

> Reference: [SRNet – Spatial Rich Model Network, ACM MM 2018](https://dl.acm.org/doi/10.1145/3240508.3240591)

Input: 512×512 grayscale image → CNN → Binary output (clean / stego). Academically significant and publishable.

```bash
pip install torch torchvision
```

#### D. Adaptive Payload Distribution via CNN Segmentation
Replace Random Forest block selection with a **lightweight segmentation network** (MobileNet-based) that identifies high-texture zones — far more visually imperceptible.

```
Input image → Lightweight CNN → Pixel capacity heatmap → Embed preferentially in high-capacity zones
```

#### E. Capacity Predictor
Train a regression model: given an image, predict the **maximum safe payload** before statistical detectability. Surface this prediction in the UI before the user even types.

---

### Tier 3 — Advanced (SDP Level, 3–4 weeks)

#### F. GAN-Based Neural Steganography (HiDDeN / SteganoGAN)
Replace LSB entirely with an **encoder-decoder GAN**.

> Papers: HiDDeN (Zhu et al., 2018), SteganoGAN (Zhang et al., 2019)

- **Encoder:** Image + secret → stego image indistinguishable from clean by humans AND statistical detectors
- **Decoder:** Stego image → reconstructed secret
- **Discriminator:** Adversarial training pressure — pushes encoder to be undetectable
- This is a publishable-quality SDP feature

#### G. Frequency Domain + Semantic Embeddings
Use CLIP or a small ViT to encode text as high-dimensional vectors, then embed into DCT/DFT frequency coefficients. Far more robust to JPEG recompression and cropping than LSB.

---

## 🎨 UI / UX Improvements

| Feature | How |
|---|---|
| **Async processing** | Fetch API → `/process` endpoint → poll `/status/<id>` |
| **Capacity preview** | Show "X KB available for this image" before user types |
| **Pixel diff view** | Display amplified difference image (original vs. stego) |
| **Steganalysis tab** | "Check if image has hidden data" mode |
| **Password-protected extraction** | Password field → PBKDF2 → AES key derivation |
| **History panel** | Store operations in SQLite with timestamps |
| **Dark / Light toggle** | Already dark — add a toggle |
| **Shareable stego links** | Upload stego to `/share/<token>` — generate a shareable URL |

---

## 🔒 Security Hardening

| Issue | Fix |
|---|---|
| AES key stored raw inside payload | Use ECDH properly — derive key, never transmit it |
| No payload integrity check | AES-CFB → AES-GCM (adds authentication tag) |
| No file size limit | `app.config['MAX_CONTENT_LENGTH'] = 10*1024*1024` |
| ECC keys regenerated on restart | Load keys from PEM files on disk |
| JPEG silently destroys LSB | Warn user when JPEG is uploaded (lossy = LSB corruption) |
| No rate limiting | Add `flask-limiter` to prevent abuse |

---

## 📊 Academic / SDP Boosters

1. **AUROC metric** — standard evaluation metric for your steganalysis classifier  
2. **RS Steganalysis** (Regular-Singular analysis) — classical statistical test for LSB — show it fails to detect your ML-guided embedding  
3. **Benchmark block selector** — prove your ML selector yields higher PSNR/SSIM vs. naive sequential LSB  
4. **Capacity vs. complexity chart** — information-theoretic insight for your paper  
5. **Formalize payload format** — document `STEGO123 + AES_KEY + CIPHERTEXT` as a proposed protocol spec

---

## 🏁 Recommended Priority Order

```
Week 1: Fix ECC key exchange + AES-GCM + file size limit + JPEG warning
Week 2: Real ML training data + richer features + joblib model persistence
Week 3: Steganalysis "detect" endpoint + steg probability UI card
Week 4: Async processing + image capacity preview
Bonus:  CNN steganalysis (SRNet) or GAN steganography (HiDDeN)
```
