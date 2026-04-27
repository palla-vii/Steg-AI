# StegAI — Complete Project Documentation
### For the Full Team | Technical + Non-Technical Walkthrough

> This document explains **everything** we did in this project — what it is, why we built it, how every piece of code works, what problems we ran into, what decisions we made, and where we plan to go next. Read it top to bottom if you're new to the project. Jump to any section if you already know the basics.

---

## Table of Contents

1. [What is StegAI? (Non-Tech Overview)](#1-what-is-stegai)
2. [The Big Problem We're Solving](#2-the-big-problem-were-solving)
3. [How the System Works — At a Glance](#3-how-the-system-works)
4. [Technology Stack](#4-technology-stack)
5. [Project Folder Structure](#5-project-folder-structure)
6. [Module-by-Module Breakdown](#6-module-by-module-breakdown)
7. [The Full Data Flow — Step by Step](#7-the-full-data-flow)
8. [Debugging Sessions — What Broke and How We Fixed It](#8-debugging-sessions)
9. [Non-Technical Decisions We Made](#9-non-technical-decisions)
10. [Quality Metrics — PSNR and SSIM Explained](#10-quality-metrics)
11. [Known Limitations and Current Weaknesses](#11-known-limitations)
12. [Improvement Roadmap](#12-improvement-roadmap)
13. [How to Run the Project Locally](#13-how-to-run-locally)

---

## 1. What is StegAI?

**StegAI** is a web application that lets you hide a secret text message inside a normal-looking image — and later retrieve it — in a way that is:

- **Encrypted** — Even if someone intercepts the image and knows there's a hidden message, they cannot read it without the key.
- **ML-Guided** — Instead of blindly modifying every pixel, our system uses a machine learning model to *choose which parts of the image are safest to modify*, making the hidden data harder to detect statistically.
- **Measurable** — After embedding, we show you exactly how much visual quality the image lost (PSNR and SSIM scores).

**In plain English:** You upload a photo, type a secret message, and get back a photo that looks identical to the original but secretly contains your encrypted message. Only someone using StegAI with the right image can extract and read it.

This is the field of **Steganography** — the practice of hiding information *inside* other information.

---

## 2. The Big Problem We're Solving

### Traditional Steganography Problems:
- Simple LSB (Least Significant Bit) methods just overwrite the last bit of every pixel in order. This is easy to detect with statistical analysis tools (e.g., RS Steganalysis).
- There is **no encryption**: if someone finds the hidden data, they can read it immediately.
- There is **no feedback**: the user has no idea how much quality they sacrificed.

### What StegAI Does Differently:

| Feature | Traditional LSB | StegAI |
|---|---|---|
| Embedding strategy | Sequential (every pixel in order) | ML-selected high-texture blocks only |
| Encryption | None | AES-256 symmetric encryption |
| Key management | N/A | ECC P-256 key pair generated at startup |
| Quality feedback | None | PSNR and SSIM scores displayed |
| User interface | CLI or basic form | Modern, responsive dark-mode web UI |
| Format support | Usually PNG only | PNG, JPG, BMP, TIFF, WEBP |

---

## 3. How the System Works

```
USER BROWSER
  1. Upload carrier image + type secret message + click Embed
  2. See stego image, PSNR/SSIM scores, and histogram
        |
        | HTTP POST (multipart/form-data)
        v
Flask Backend (app.py)
  - Validates file type (PNG/JPG/BMP/TIFF/WEBP allowed)
  - Saves uploaded file to /uploads/
  - Routes to embed or extract based on button clicked
        |
  ------+----------+------------
  |               |            |
  v               v            v
aes_module    ml_module    steg_module
(Encryption)  (Block Score) (Core LSB)
  |               |            |
  +--------------+-----------+
                  |
                  v
       results/stego.png
       static/hist.png
                  |
                  v
       Rendered back to browser
```

---

## 4. Technology Stack

| Layer | Tool | Why We Chose It |
|---|---|---|
| **Backend Framework** | Flask (Python) | Lightweight, easy to set up, great for academic projects |
| **Image Processing** | OpenCV (`cv2`) | Industry-standard, handles all image formats efficiently |
| **Numerical Computing** | NumPy | Required for fast array operations on pixel data |
| **Encryption** | `cryptography` (Python) | Professional-grade AES-256 and ECC P-256 |
| **Machine Learning** | Scikit-learn (Random Forest) | Simple, interpretable, no GPU required |
| **Plotting** | Matplotlib | Generates the pixel intensity histograms |
| **Frontend** | HTML + Vanilla CSS + JavaScript | No heavy framework; full design control |
| **Fonts / Icons** | Google Fonts + Font Awesome | Premium look without extra build step |
| **File handling** | Werkzeug `secure_filename` | Prevents path-traversal security vulnerabilities |

**Installing all dependencies:**
```bash
pip install -r requirements.txt
```

Contents of `requirements.txt`:
```
flask
opencv-python
cryptography
numpy
scikit-learn
matplotlib
```

---

## 5. Project Folder Structure

```
sdp/
├── app.py                        # Main Flask server — entry point
├── requirements.txt              # Python dependencies
│
├── src/                          # All backend logic modules
│   ├── aes_module.py             # AES-256-CFB encrypt/decrypt
│   ├── ecc_module.py             # ECC P-256 key pair generation
│   ├── ml_module.py              # Random Forest block safety classifier
│   └── steg_module.py            # LSB embed/extract + PSNR/SSIM/Histogram
│
├── templates/
│   └── index.html                # The single-page UI (Jinja2 template)
│
├── static/
│   ├── style.css                 # All CSS — dark-mode design system
│   └── hist.png                  # Auto-generated histogram (after embed)
│
├── uploads/                      # Uploaded carrier images (auto-created)
├── results/                      # Output stego images (auto-created)
│
├── stegai_improvement_plan.md    # Technical improvement roadmap
├── TEAM_PROJECT_DOCUMENTATION.md # This file
└── StegAI_SDP_Presentation.pptx  # Presentation deck
```

---

## 6. Module-by-Module Breakdown

---

### 6.1 `app.py` — The Server

**Role:** Entry point. Pulls all other modules together. Handles HTTP requests, routes user actions, and sends back results.

**Key responsibilities:**
- Starts the Flask web server
- Generates ECC key pair **once** at startup (stays in memory during session)
- Validates uploaded files (type check + secure filename)
- Routes to **embed** or **extract** paths based on which button the user clicked
- Calls `encrypt_aes` → `embed_data` → `calculate_psnr` → `calculate_ssim` → `save_histogram` in sequence
- Passes all results back to the HTML template for rendering

**Routes defined:**

| Route | Method | What it does |
|---|---|---|
| `/` | GET | Renders the empty home page |
| `/` | POST | Processes embed or extract request |
| `/uploads/<filename>` | GET | Serves uploaded images back to browser |
| `/results/<filename>` | GET | Serves stego output images back to browser |

**THE PAYLOAD FORMAT (critical to understand):**
```
[8 bytes: "STEGO123"] + [32 bytes: AES key] + [N bytes: AES ciphertext]
```
This magic header (`STEGO123`) lets `extract_data` verify that a stego image was made by StegAI, not some random image. We check for it before attempting decryption.

---

### 6.2 `steg_module.py` — The Steganography Engine

**Role:** The core technical heart of the project. Does the actual pixel-level hiding and recovering of data.

**Key constants:**
```python
DELIMITER = b"##STEGAI##"   # Signals end-of-payload during extraction
TARGET_SIZE = (512, 512)    # All images resized before processing
```

**`embed_data()` — Step by step:**

1. Read the image using OpenCV
2. Resize to 512×512 — ensures consistent capacity regardless of input size
3. Build payload = your data bytes + `##STEGAI##` delimiter
4. Convert to binary string — each byte → 8 bits (e.g., 65 → `01000001`)
5. Check capacity — a 512×512 RGB image has `512 × 512 × 3 = 786,432` bits available
6. LSB embedding — for each bit in the payload, flip the least significant bit of the next pixel channel:
   ```python
   pixel_byte = (pixel_byte & 0xFE) | bit_value
   # 0xFE = 11111110 — zeros out the last bit, then OR with our bit
   ```
7. Reshape and save as PNG (lossless — JPEG would destroy the hidden data)

**`extract_data()` — Step by step:**

1. Read & resize the stego image to 512×512 (must match embed dimensions exactly)
2. Read the LSB of every channel byte in sequence — reconstruct bits
3. Assemble bits into bytes (8 bits = 1 byte)
4. After each new byte, check if the last N bytes equal the Delimiter
5. Once delimiter is found, return everything before it — that's our payload

**`get_safe_blocks()` — ML-Guided Block Selection:**

Instead of embedding in every pixel, we first score 8×8 pixel blocks:
1. Skip blocks with variance < 20 (flat/uniform regions — visually risky to alter)
2. Ask the ML model: "Is this block safe to embed in?"
3. Return a list of up to 200 safe (row, col) block positions

> **Why high-texture blocks?** Edges, patterns, and complex regions naturally vary pixel-to-pixel. Flipping a single bit in the last position of these pixels is virtually invisible. In flat/smooth regions like a clear sky, even a 1-bit change can create visible noise.

**Quality Metrics:**

- **`calculate_psnr()`** — Peak Signal-to-Noise Ratio. `psnr = 10 × log10(255² / MSE)`. A PSNR above 40 dB means images are visually indistinguishable to the human eye.
- **`calculate_ssim()`** — Structural Similarity Index. Scores 0–1.0. Measures luminance, contrast, and structure similarity. Our project targets > 0.999.
- **`save_histogram()`** — Generates side-by-side bar charts of pixel intensity distributions for original vs stego, so you can visually confirm the pixel distribution was not significantly shifted.

---

### 6.3 `aes_module.py` — The Encryption Layer

**Role:** Symmetric encryption of the secret message before embedding.

```python
def encrypt_aes(message, key):
    iv = os.urandom(16)              # Random 16-byte initialization vector
    cipher = Cipher(AES(key), CFB(iv))
    ciphertext = encryptor.update(message.encode()) + encryptor.finalize()
    return iv + ciphertext           # Prepend IV so decrypt can use it

def decrypt_aes(ciphertext, key):
    iv = ciphertext[:16]             # First 16 bytes are always the IV
    actual_cipher = ciphertext[16:]
    # Reconstruct cipher with same key + IV, then decrypt
```

- **Algorithm:** AES-256-CFB (Cipher Feedback Mode)
- **Key size:** 256 bits (32 bytes) — the strongest standard AES variant
- **IV:** A new random 16-byte IV is generated for every encryption — prevents identical messages from producing identical ciphertext
- **Output:** `iv (16 bytes) + ciphertext (N bytes)`

> **Why AES-256?** It is the gold standard for symmetric encryption, used by governments and financial institutions. Brute-forcing a 256-bit key would take longer than the age of the universe even with today's most powerful computers.

---

### 6.4 `ecc_module.py` — The Key Generation Layer

**Role:** Generates an Elliptic Curve (ECC) key pair.

```python
def generate_keys():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key  = private_key.public_key()
    return private_key, public_key

def derive_shared_key(private_key, peer_public_key):
    shared_secret = private_key.exchange(ec.ECDH(), peer_public_key)
    derived_key = HKDF(SHA256, length=32).derive(shared_secret)
    return derived_key
```

- **Curve:** SECP256R1 (P-256 / prime256v1) — same curve used in TLS 1.3, Signal, and SSH
- Key pair is generated **once when the server starts** and held in memory

> **Current limitation:** `derive_shared_key` is implemented but not connected to the actual embedding flow yet. The AES key is currently generated randomly and stored inside the stego payload. This is a known gap — see the improvement roadmap.

---

### 6.5 `ml_module.py` — The Machine Learning Layer

**Role:** A trained binary classifier that decides, for each 8×8 pixel block, whether it is "safe" to embed data into.

```python
model = RandomForestClassifier(n_estimators=50, random_state=42)

def extract_features(block):
    flat = block.flatten().astype(np.float64)  # Works for 2D AND 3D blocks
    return [np.std(flat), np.var(flat)]

# Training: 1000 synthetic random 8x8 blocks
# Label: 1 (safe) if std > 30, else 0 (risky)

def is_safe_block(block):
    features = extract_features(block)
    return model.predict([features])[0] == 1
```

> **Important caveat:** The model is trained on *synthetic random data*, not real images. In practice the Random Forest is essentially learning to replicate the rule "std > 30". The ML layer adds structural separation but the training is not academically rigorous yet. See the roadmap for the fix.

---

### 6.6 `templates/index.html` — The Frontend UI

**Role:** The entire user interface. A single HTML page rendered by Flask using Jinja2 templating.

**Layout:**
- **Left sidebar** — File upload, message input, Embed/Extract buttons, status indicators, tech info grid
- **Right main area** — Carrier image preview, stego output preview, histogram, extraction terminal

**Key UI components:**

| Component | What it does |
|---|---|
| Drag-and-drop zone | Lets users drag image files directly onto the upload area |
| Character counter | Live count of message length (warns at 1800/2000 chars) |
| Loading overlay | Full-screen spinner with animated progress bar during processing |
| Metric chips | Shows PSNR, SSIM, and image dimensions in the header bar |
| Info grid | Shows Cipher (AES-256), Key (ECC P-256), Embedding method, ML model |
| Alert banners | Red for errors, green for successful extraction |
| Terminal output | Styled dark panel showing the decrypted message |
| Histogram card | Full-width card comparing original vs stego pixel distributions |
| Download button | Lets user save the stego image to disk |

**Jinja2 variables passed from Flask:**
```python
render_template("index.html",
    message=message,       # Decrypted text or error string
    error=error,           # Validation/processing error
    uploaded_image=...,    # URL to display original image
    stego_image=...,       # URL to display stego output
    psnr=psnr_value,       # Float: PSNR in dB
    ssim=ssim_value,       # Float: SSIM 0-1
    histogram=histogram,   # URL to histogram PNG
)
```

**JavaScript features (no extra libraries):**
- Drag & drop file handling
- Live character counter with color-coded warning
- Loading overlay toggle on form submit
- Animated progress bar during processing

---

### 6.7 `static/style.css` — The Design System

**Role:** All 18+ KB of styling for the dark-mode glassmorphism UI.

**Key design tokens (CSS variables):**
```css
--bg-0: #020817;      /* Page background (near-black) */
--bg-1: #0f172a;      /* Card/sidebar background */
--blue: #3b82f6;      /* Primary accent */
--emerald: #10b981;   /* Success/safe indicators */
--violet: #8b5cf6;    /* Tertiary accent */
--red: #ef4444;       /* Error states */
--amber: #f59e0b;     /* Warning states */
```

**Design approach:**
- Dark background with subtle blue gradient
- **Glassmorphism** sidebar — frosted glass effect via `backdrop-filter: blur`
- **Ambient orbs** — three large blurred gradient circles in the background (`filter: blur(80px)`) that give the "glow in the dark" feel
- **Micro-animations** — `slide-in`, `fade-in`, `pulse`, `spin`, `progress-fill`
- **JetBrains Mono** font for terminal output; **Inter** for all other text
- CSS was moved out of `index.html` into a separate file for maintainability

---

## 7. The Full Data Flow

### Embedding a Message:

```
User: Uploads photo.png + types "Meet at midnight" + clicks "Encrypt & Embed"
  |
  v
app.py validates: Is it a PNG/JPG/BMP/TIFF/WEBP? YES
  |
  v
app.py generates: aes_key = os.urandom(32)     -- 32 random bytes
  |
  v
aes_module.encrypt_aes("Meet at midnight", aes_key)
  -- iv = os.urandom(16)                        -- 16 random bytes
  -- ciphertext = AES-256-CFB(message, key, iv)
  -- returns: iv + ciphertext
  |
  v
app.py builds final payload:
  -- b"STEGO123" + aes_key (32B) + ciphertext = N bytes total
  |
  v
steg_module.embed_data(photo.png, payload, results/stego.png)
  -- Load and resize photo.png to 512x512
  -- payload + b"##STEGAI##" -> binary string
  -- scan 8x8 blocks -> ml_module.is_safe_block() filters unsafe blocks
  -- flip LSBs of channel bytes
  -- save results/stego.png (PNG, lossless)
  |
  v
calculate_psnr() -> e.g., 51.3 dB
calculate_ssim() -> e.g., 0.9998
save_histogram() -> static/hist.png
  |
  v
Flask renders page with stego image + PSNR/SSIM + histogram
```

### Extracting a Message:

```
User: Uploads stego.png + clicks "Extract & Decrypt"
  |
  v
steg_module.extract_data(stego.png)
  -- Load and resize to 512x512
  -- Read LSB of every channel byte sequentially -> reconstruct bits
  -- Assemble bits into bytes
  -- Scan for b"##STEGAI##" delimiter
  -- Return bytes before delimiter = our payload
  |
  v
app.py parses payload:
  -- signature  = payload[0:8]   -> b"STEGO123" CHECK PASSES
  -- aes_key    = payload[8:40]  -> 32-byte key
  -- ciphertext = payload[40:]   -> N-byte ciphertext
  |
  v
aes_module.decrypt_aes(ciphertext, aes_key)
  -- iv = ciphertext[:16]
  -- AES-256-CFB decrypt -> "Meet at midnight"
  |
  v
Flask renders: "Decrypted message: Meet at midnight"
```

---

## 8. Debugging Sessions

This section documents every major crash or bug we encountered and how we fixed it.

---

### Bug 1: Server Crash on Large Images (Shape Mismatch in PSNR)

**What happened:** When a user uploaded a non-square image (e.g., 1920×1080), the PSNR function crashed with a shape mismatch — the original was 1920×1080, but the stego output was 512×512.

**Root cause:** `embed_data` resizes to 512×512, but `calculate_psnr` was comparing the *original uploaded file* (not resized) against the *stego file* (already 512×512).

**Fix:**
```python
# Resize BOTH images to the same reference size before comparison
img1 = cv2.resize(img1, TARGET_SIZE).astype(np.float64)
img2 = cv2.resize(img2, TARGET_SIZE).astype(np.float64)
```

---

### Bug 2: Integer Overflow in PSNR Calculation

**What happened:** PSNR returned incorrect negative values (e.g., -12 dB).

**Root cause:** OpenCV reads images as `uint8` (0–255). When computing `(img1 - img2)²`, uint8 arithmetic *wraps around* (e.g., `5 - 250 = 11`, not `-245`).

**Fix:** Cast to `float64` before any subtraction:
```python
img1 = img1.astype(np.float64)
img2 = img2.astype(np.float64)
mse = np.mean((img1 - img2) ** 2)  # Now correct float arithmetic
```

---

### Bug 3: Matplotlib Crash on Headless Server

**What happened:** `save_histogram()` crashed with `_tkinter.TclError: no display name and no $DISPLAY environment variable`.

**Root cause:** Matplotlib tries to open a graphical window by default. On a server with no screen, this fails.

**Fix:** Set the non-interactive Agg backend *before* importing pyplot:
```python
import matplotlib
matplotlib.use('Agg')   # Must come before any other matplotlib import
import matplotlib.pyplot as plt
```

---

### Bug 4: ML Model `predict()` Shape Error

**What happened:** `is_safe_block()` threw `ValueError: X has 6144 features but RandomForestClassifier expects 2 features`.

**Root cause:** The model was trained on 2D (grayscale, 8×8=64 values) blocks but called with 3D (color, 8×8×3=192 values) blocks at runtime.

**Fix:** Always flatten the block first, regardless of 2D or 3D shape:
```python
def extract_features(block):
    flat = block.flatten().astype(np.float64)  # Works for 2D AND 3D
    return [np.std(flat), np.var(flat)]
```

---

### Bug 5: Histogram Generation Crashing (Non-Fatal)

**What happened:** On the very first embed, `save_histogram()` would sometimes crash.

**Fix:** Wrapped histogram generation in try/except so it's non-fatal — the page still works if it fails:
```python
try:
    save_histogram(filepath, output_path, output_path="static/hist.png")
    histogram = "/static/hist.png"
except Exception as hist_err:
    print(f"[WARNING] Histogram generation failed: {hist_err}")
    histogram = None
```

---

### Bug 6: Empty Message Causing Silent Embed

**What happened:** Clicking "Embed" without typing a message silently embedded nothing with no feedback.

**Fix:**
```python
if not msg:
    raise ValueError("Message cannot be empty for embedding.")
```

---

### Bug 7: Unsupported File Type Gave Generic Error

**What happened:** Uploading a `.gif` or `.pdf` gave a generic 500 error.

**Fix:** Added explicit type validation with a clear human-readable error:
```python
error = (
    f"Unsupported file type '{ext}'. "
    f"Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
)
```

---

## 9. Non-Technical Decisions

These are the "why" decisions — choices that were not purely technical.

| Decision | What we chose | Why |
|---|---|---|
| **Project scope** | Web app (not desktop or CLI) | Accessible to anyone; looks great in a demo |
| **Single-page design** | One page, two modes | Simpler UX; shows everything at once |
| **Dark mode only** | Dark theme | Fits the "secure/technical" aesthetic; impressive in demos |
| **512×512 forced resize** | All images normalized | Ensures consistent capacity and predictable behavior |
| **PNG for stego output** | Always save as `.png` | PNG is lossless — JPEG would destroy the LSB-encoded bits |
| **AES key stored in payload** | Key embedded alongside ciphertext | Simple to implement; makes self-contained stego images |
| **Dummy ML training** | Synthetic random blocks | Fast to train; ML architecture is demonstrated even if simplified |
| **No user accounts** | Stateless per-request | Keeps project simple; not needed for SDP scope |
| **CSS extracted from HTML** | Moved to `static/style.css` | Better maintainability; 18KB of CSS is unreadable inline |
| **Presentation from code** | Python-generated `.pptx` | Faster iteration; slides regenerated from updated content |

---

## 10. Quality Metrics

### PSNR (Peak Signal-to-Noise Ratio)

- **Unit:** dB (decibels)
- **Formula:** `10 × log10(255² / MSE)` where MSE = mean squared pixel difference
- **Interpretation:**

| PSNR | Visual quality |
|---|---|
| > 50 dB | Essentially identical — imperceptible |
| 40–50 dB | Excellent — invisible to human eye |
| 30–40 dB | Good — very minor artifacts possible |
| < 30 dB | Noticeable degradation |

For LSB steganography, PSNR is typically **50–60 dB** since we only flip the *least* significant bit.

### SSIM (Structural Similarity Index Measure)

- **Range:** 0.0 (completely different) to 1.0 (identical)
- Measures perceived similarity across: **luminance**, **contrast**, and **structure**
- For our project, SSIM should be very close to 1.0 (typically 0.9997–0.9999)

> **Why show both?** PSNR is purely mathematical. SSIM better models how human perception works. Showing both together is academically rigorous.

---

## 11. Known Limitations

| Issue | Severity |
|---|---|
| AES key stored raw in payload — anyone who knows the format can extract the key | High |
| ECC not properly used — `derive_shared_key` is implemented but never called | High |
| Synthetic ML training data — model just relearns the "std > 30" rule | Medium |
| `std` and `variance` are redundant features — variance = std² | Medium |
| Force resize to 512×512 — wastes capacity on large images | Medium |
| No file size limit — a 100MB image can stall the server | Medium |
| AES-CFB has no integrity check — tampered payloads decrypt to garbage silently | Medium |
| JPEG inputs silently corrupt LSB — user must use lossless formats | Medium |
| No async processing — large images block the server thread | Low |

---

## 12. Improvement Roadmap

See `stegai_improvement_plan.md` for full technical details.

### Priority 1 — This Week
- [ ] Fix ECC: use ECDH properly — derive AES key from shared secret, embed sender's ephemeral public key in payload instead of raw AES key
- [ ] Upgrade AES-CFB → AES-GCM (adds authentication tag — detects tampering)
- [ ] Add `MAX_CONTENT_LENGTH = 10MB` to prevent crash on giant uploads
- [ ] Warn user when JPEG is uploaded (lossy compression destroys LSBs)

### Priority 2 — Next 2 Weeks
- [ ] Train ML model on **real** image blocks (from a dataset of actual photos)
- [ ] Add more meaningful features: entropy, IQR, local variation (not just std/variance)
- [ ] Persist trained model with `joblib` — don't retrain on every server start

### Priority 3 — Bonus / Advanced
- [ ] Steganalysis detect mode — upload an image, AI predicts if it has hidden data
- [ ] AI Security Report Card — detectability score, block coverage, recommendations
- [ ] Deep CNN steganalysis (SRNet / YeNet via PyTorch)
- [ ] GAN-based steganography (HiDDeN / SteganoGAN) — replaces LSB entirely

---

## 13. How to Run Locally

**Prerequisites:** Python 3.9+ installed

```bash
# 1. Navigate to the project folder
cd path/to/sdp

# 2. Create a virtual environment (recommended)
python -m venv venv

# 3. Activate it
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 4. Install all dependencies
pip install -r requirements.txt

# 5. Start the Flask server
python app.py

# 6. Open in browser
# Visit: http://127.0.0.1:5000
```

**What you'll experience:**
- The StegAI dark-mode UI with sidebar controls
- Upload an image → type a message → click "Encrypt & Embed"
- See PSNR/SSIM scores and the stego image appear on the right
- Download the stego image
- Re-upload it → click "Extract & Decrypt" → see your original message

---

## Quick Reference Summary

| What | Answer |
|---|---|
| What does StegAI do? | Hides encrypted messages in images using ML-guided LSB steganography |
| Encryption algorithm | AES-256-CFB |
| Key type | ECC P-256 (SECP256R1) — generated at server startup |
| ML model | Random Forest (50 trees), trained on synthetic 8×8 blocks |
| Embedding method | Least Significant Bit (LSB) modification |
| Block selection | ML + variance pre-filter (skips blocks with variance < 20) |
| Image size | All normalized to 512×512 before processing |
| Output format | Always PNG (lossless — required for LSB integrity) |
| Quality check | PSNR (dB) + SSIM (0–1) + side-by-side pixel histogram |
| Magic header | `STEGO123` — identifies StegAI-embedded images |
| Delimiter | `##STEGAI##` — marks end of payload during extraction |
| Tech stack | Flask + OpenCV + NumPy + cryptography + scikit-learn + Matplotlib |

---

*Documentation written for the StegAI Senior Design Project team.*
*Last updated: April 2026*
