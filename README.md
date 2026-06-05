# 🔐 Steg-AI

**AI-guided image steganography with end-to-end encryption**

Steg-AI is a web application that lets you hide secret messages inside ordinary images using **ML-guided LSB steganography**, secured with **AES-256-GCM** encryption and **ephemeral ECDH (SECP256R1)** key exchange. A built-in **neural steganalysis detector** can also analyze images and report whether hidden data is likely present.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🤖 **ML-Guided Embedding** | A Random Forest classifier identifies high-texture 8×8 blocks where data can be hidden with minimal visual impact |
| 🔒 **AES-256-GCM Encryption** | All messages are encrypted before embedding — only the receiver can decrypt |
| 🔑 **Ephemeral ECDH Key Exchange** | A fresh key pair is generated per message; the raw AES key is never stored or transmitted |
| 🧠 **Neural Steganalysis** | An MLP neural network analyzes images for statistical anomalies and reports a detection verdict |
| 📊 **Quality Metrics** | PSNR and SSIM scores measure how visually similar the stego image is to the original |
| 📈 **Pixel Histograms** | Side-by-side histograms compare original vs. stego image pixel distributions |
| ⚡ **Async Processing** | Embed/extract jobs run in background threads; the UI polls for completion — no blocking |
| 🧹 **Auto Cleanup** | Uploaded and result files are auto-purged after 30 minutes |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Flask Web App                       │
│                        app.py                           │
└────────┬────────────────────────────────────┬───────────┘
         │                                    │
   ┌─────▼──────┐                    ┌────────▼────────┐
   │ ECC Module │                    │   Steg Module   │
   │ecc_module.py│                   │ steg_module.py  │
   │            │                    │                 │
   │ ECDH key   │                    │ ML block select │
   │ exchange   │                    │ LSB embed/extract│
   └─────┬──────┘                    └────────┬────────┘
         │                                    │
   ┌─────▼──────┐                    ┌────────▼────────┐
   │ AES Module │                    │   ML Module     │
   │aes_module.py│                   │  ml_module.py   │
   │            │                    │                 │
   │ AES-256-GCM│                    │ Random Forest   │
   │ encrypt /  │                    │ block classifier│
   │ decrypt    │                    └────────┬────────┘
   └────────────┘                            │
                                    ┌────────▼────────┐
                                    │  Steg Detector  │
                                    │steg_detector.py │
                                    │                 │
                                    │ MLP neural net  │
                                    │ steganalysis    │
                                    └─────────────────┘
```

### Payload Format

Every embedded message uses this binary layout:

```
[ MAGIC 8B ][ Sender ECC Public Key 65B ][ AES-256-GCM Ciphertext ]
```

- **MAGIC** = `STEGAI02` — version marker for forward/backward compatibility
- **Sender ECC Public Key** — ephemeral public key used by the receiver to re-derive the shared AES key via ECDH
- **Ciphertext** — AES-256-GCM encrypted message with nonce and tag prepended

---

## 📁 Project Structure

```
Steg-AI/
├── app.py                      # Flask application & routing
├── requirements.txt            # Python dependencies
├── Procfile                    # Heroku/Render process file
├── render.yaml                 # Render deployment config
├── build.sh                    # Build script
├── show_training_data.py       # Visualize ML training data
├── training data.png           # Training data sample
├── training_data_visualization.png
├── src/
│   ├── aes_module.py           # AES-256-GCM encrypt/decrypt
│   ├── ecc_module.py           # ECDH key generation & derivation
│   ├── ml_module.py            # Random Forest block classifier
│   ├── steg_module.py          # LSB embed/extract + metrics
│   └── steg_detector.py        # Neural steganalysis (MLP)
├── templates/
│   └── index.html              # Single-page web UI
├── static/                     # CSS, JS, icons
├── keys/                       # Receiver key pair (auto-generated)
│   └── receiver_public.pem     # ✅ Safe to commit
│   # receiver_private.pem      # 🚫 Never committed (.gitignored)
├── uploads/                    # Temp uploads (auto-cleaned, .gitignored)
└── results/                    # Stego output images (auto-cleaned, .gitignored)
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.9+
- pip

### Installation

```bash
# Clone the repository
git clone https://github.com/palla-vii/Steg-AI.git
cd Steg-AI

# Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### Run Locally

```bash
python app.py
```

Then open your browser at `http://127.0.0.1:5000`

---

## 🖥️ Usage

### Embed a Message

1. Select **Embed** mode
2. Upload a cover image (PNG, BMP, TIFF, WebP — lossless formats recommended)
3. Type your secret message
4. Click **Process** — the app will encrypt and embed your message
5. Download the resulting stego image
6. View quality metrics (PSNR, SSIM) and the AI detection report

### Extract a Message

1. Select **Extract** mode
2. Upload the stego image
3. Click **Process** — the app will extract and decrypt the hidden message automatically using the receiver's private key

### Standalone AI Analysis

Upload any image via the **Analyse** tab to get a neural steganalysis verdict:

| Verdict | Confidence | Meaning |
|---|---|---|
| ✅ **NOT DETECTED** | < 50% | No significant statistical evidence of hidden data |
| ⚠️ **SUSPECTED** | 50–75% | Mild anomalies detected; inconclusive |
| 🚨 **DETECTED** | > 75% | Strong statistical evidence of hidden payload |

---

## 🔬 How the AI Works

### Embedding — ML Block Selector

The Random Forest classifier (`ml_module.py`) scores every 8×8 block in the image based on texture features. Blocks with high variance and complexity are selected as **safe** for embedding — LSB changes in textured regions are far less noticeable to the human eye than in smooth areas.

### Detection — Neural Steganalysis

The MLP detector (`steg_detector.py`) extracts 7 statistical features from any image:

1. **Chi-square on PoV pairs** — AES-encrypted bits equalize value-pair frequencies
2. **LSB run-length entropy** — random payloads produce very short runs
3. **Residual standard deviation** — noise residual from Gaussian high-pass filter
4. **Residual kurtosis** — shape of the noise distribution
5. **Residual entropy** — randomness in the quantized noise residual
6. **LSB mean** — random payload → mean ≈ 0.5
7. **Diagonal LSB autocorrelation** — content-insensitive spatial correlation

The MLP is trained on 2,000 synthetic image pairs (1,000 clean + 1,000 stego) with realistic multi-scale texture noise to avoid false positives on natural photographs.

---

## 🌐 Deployment

The app is configured to deploy on **Render** via `render.yaml`:

```yaml
services:
  - type: web
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app
```

> **Note:** Set `UPLOAD_DIR` and `RESULT_DIR` environment variables on your cloud platform to point to writable directories (e.g., `/tmp`).

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `flask` | Web framework |
| `opencv-python` | Image I/O and processing |
| `cryptography` | AES-256-GCM & ECDH (SECP256R1) |
| `numpy` | Array operations |
| `scikit-learn` | Random Forest & MLP classifiers |
| `matplotlib` | Histogram generation |
| `gunicorn` | Production WSGI server |

---

## ⚠️ Limitations

- **JPEG/JPEG2000 are lossy** — compression destroys LSB data. Always use PNG, BMP, TIFF, or WebP for stego output.
- **Short messages are undetectable by design** — they occupy < 1% of pixels, leaving no meaningful statistical signal.
- **In-memory job store** — jobs are lost on server restart (suitable for demo/academic use).
- **Single receiver key pair** — all messages are encrypted to the same receiver key. For multi-user scenarios, extend `ecc_module.py`.

---

## 📄 License

This project was developed as a **Senior Design Project (SDP)**. All rights reserved by the authors.
