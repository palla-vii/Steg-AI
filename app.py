# app.py
#
# General improvements applied (see stegai_improvement_plan.md §🛠️):
#
#   1. Proper ephemeral ECDH — AES key derived via ECDH + HKDF; the raw key
#      is NEVER stored in the stego payload.  Payload layout (v2):
#        [magic 8B][sender_pub_key_bytes 65B][AES-GCM ciphertext + tag]
#
#   2. AES-256-GCM replaces AES-256-CFB — adds integrity authentication.
#
#   3. 10 MB upload size limit — prevents server crash from huge files.
#
#   4. JPEG warning — LSB embedding is destroyed by JPEG recompression;
#      user is warned when a lossy format is uploaded.
#
#   5. Receiver ECC keys are now persistent (loaded from keys/ PEM files)
#      so previously embedded images remain decryptable after server restart.
#
#   6. Images are processed at native resolution (no forced 512×512 resize).

import os
from flask import Flask, render_template, request, send_from_directory, jsonify
from werkzeug.utils import secure_filename

from src.ecc_module import (
    load_or_generate_receiver_keys,
    generate_ephemeral_keys,
    derive_shared_key,
    public_key_from_bytes,
    EC_PUBLIC_KEY_BYTES,
)
from src.aes_module import encrypt_aes, decrypt_aes
from src.steg_module import (
    embed_data,
    extract_data,
    calculate_psnr,
    calculate_ssim,
    save_histogram,
)

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------

app = Flask(__name__)

# Improvement #3 — refuse uploads larger than 10 MB
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024   # 10 MB

UPLOAD_FOLDER = "uploads"
RESULT_FOLDER = "results"
ALLOWED_EXTENSIONS = {"png", "bmp", "tiff", "webp", "jpg", "jpeg"}

# Lossy formats — LSB is destroyed by their compression
LOSSY_EXTENSIONS = {"jpg", "jpeg"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULT_FOLDER, exist_ok=True)
os.makedirs("static",      exist_ok=True)

# Improvement #5 — load persistent receiver key pair (generated once if missing)
receiver_private_key, receiver_public_key = load_or_generate_receiver_keys()

# Payload magic / version
MAGIC   = b"STEGAI02"   # v2 payload (v1 was "STEGO123" with raw AES key)
PUB_OFF = len(MAGIC)                           # 8
CT_OFF  = PUB_OFF + EC_PUBLIC_KEY_BYTES        # 8 + 65 = 73


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def is_lossy(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in LOSSY_EXTENSIONS


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def index():
    message        = None
    uploaded_image = None
    stego_image    = None
    psnr_value     = None
    ssim_value     = None
    histogram      = None
    error          = None
    jpeg_warning   = False   # Improvement #4
    img_dims       = None    # Improvement #6 — show actual image dimensions

    if request.method == "POST":

        # ── Validate file upload ───────────────────────────────────────────
        if "image" not in request.files:
            error = "No file field in request."
        else:
            file = request.files["image"]

            if file.filename == "":
                error = "No file selected."
            elif not allowed_file(file.filename):
                error = (
                    f"Unsupported file type '{file.filename.rsplit('.', 1)[-1]}'. "
                    f"Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
                )

        if error is None:
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            uploaded_image = "/uploads/" + filename

            # Improvement #4 — JPEG warning
            if is_lossy(filename):
                jpeg_warning = True

            action = request.form.get("action", "")

            try:
                if action == "embed":
                    msg = request.form.get("message", "").strip()
                    if not msg:
                        raise ValueError("Message cannot be empty for embedding.")

                    # ── Ephemeral ECDH key derivation (Improvement #1) ─────
                    # 1. Generate ephemeral sender key pair
                    sender_ephemeral_priv, sender_pub_bytes = generate_ephemeral_keys()

                    # 2. Derive shared AES key: ECDH(sender_priv, receiver_pub)
                    aes_key = derive_shared_key(sender_ephemeral_priv, receiver_public_key)

                    # 3. Encrypt with AES-256-GCM (Improvement #2)
                    ciphertext = encrypt_aes(msg, aes_key)

                    # 4. Payload v2: [magic 8B][sender_pub 65B][ciphertext...]
                    #    The raw AES key is NEVER stored in the payload.
                    final_data = MAGIC + sender_pub_bytes + ciphertext

                    output_path = os.path.join(RESULT_FOLDER, "stego.png")
                    embed_data(filepath, final_data, output_path)

                    # Quality metrics
                    psnr_value = calculate_psnr(filepath, output_path)
                    ssim_value = calculate_ssim(filepath, output_path)

                    # Histogram (non-fatal)
                    try:
                        save_histogram(filepath, output_path, output_path="static/hist.png")
                        histogram = "/static/hist.png"
                    except Exception as hist_err:
                        print(f"[WARNING] Histogram generation failed: {hist_err}")
                        histogram = None

                    stego_image = "/results/stego.png"

                    # Improvement #6 — report real image dimensions
                    import cv2
                    _img = cv2.imread(filepath)
                    if _img is not None:
                        img_dims = f"{_img.shape[1]} × {_img.shape[0]}"

                elif action == "extract":
                    extracted = extract_data(filepath)

                    # ── Parse v2 payload ──────────────────────────────────
                    if len(extracted) < CT_OFF + 1:
                        message = "⚠️ Invalid or corrupted stego image (payload too short)."
                    elif extracted[:len(MAGIC)] == MAGIC:
                        # v2: ECDH-derived key
                        sender_pub_bytes = extracted[PUB_OFF : CT_OFF]
                        ciphertext       = extracted[CT_OFF :]
                        aes_key = derive_shared_key(receiver_private_key, sender_pub_bytes)
                        decrypted = decrypt_aes(ciphertext, aes_key)
                        message = f"✅ Decrypted message: {decrypted}"

                    elif extracted[:8] == b"STEGO123":
                        # v1 legacy fallback (raw AES key in payload)
                        if len(extracted) < 40:
                            message = "⚠️ Corrupted v1 stego image."
                        else:
                            aes_key   = extracted[8:40]
                            ciphertext = extracted[40:]
                            decrypted = decrypt_aes(ciphertext, aes_key)
                            message = f"✅ Decrypted message (legacy v1): {decrypted}"
                    else:
                        message = "❌ No hidden message found in this image."

                else:
                    error = f"Unknown action: '{action}'"

            except Exception as exc:
                error = f"Processing error: {str(exc)}"
                print(f"[ERROR] {exc}")

    return render_template(
        "index.html",
        message=message,
        error=error,
        uploaded_image=uploaded_image,
        stego_image=stego_image,
        psnr=psnr_value,
        ssim=ssim_value,
        histogram=histogram,
        jpeg_warning=jpeg_warning,
        img_dims=img_dims,
    )


# ---------------------------------------------------------------------------
# Static file routes
# ---------------------------------------------------------------------------

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory("uploads", filename)


@app.route("/results/<filename>")
def result_file(filename):
    return send_from_directory("results", filename)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle the 413 raised by Flask when MAX_CONTENT_LENGTH is exceeded."""
    return render_template(
        "index.html",
        error="File too large. Maximum allowed upload size is 10 MB.",
        message=None, uploaded_image=None, stego_image=None,
        psnr=None, ssim=None, histogram=None,
        jpeg_warning=False, img_dims=None,
    ), 413


if __name__ == "__main__":
    app.run(debug=True)