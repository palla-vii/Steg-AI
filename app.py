# app.py — StegAI Flask Application
#
# ML-guided LSB steganography with AES-256-GCM encryption and
# ephemeral ECDH (SECP256R1) key exchange.
# Async job processing via background threads + /status polling.

import os
import uuid
import threading
import cv2

from flask import Flask, render_template, request, send_from_directory, jsonify
from werkzeug.utils import secure_filename

from src.ecc_module import (
    load_or_generate_receiver_keys,
    generate_ephemeral_keys,
    derive_shared_key,
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
from src.steg_detector import analyse as ai_analyse

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------

app = Flask(__name__)

# Refuse uploads larger than 10 MB
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024   # 10 MB

UPLOAD_FOLDER    = "uploads"
RESULT_FOLDER    = "results"
ALLOWED_EXTENSIONS = {"png", "bmp", "tiff", "webp", "jpg", "jpeg"}
LOSSY_EXTENSIONS   = {"jpg", "jpeg"}   # LSB is destroyed by their compression

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULT_FOLDER, exist_ok=True)
os.makedirs("static",      exist_ok=True)

# Load persistent receiver key pair (generated once if missing)
receiver_private_key, receiver_public_key = load_or_generate_receiver_keys()

# Payload magic / version
MAGIC   = b"STEGAI02"          # v2 payload (v1 was "STEGO123" with raw AES key)
PUB_OFF = len(MAGIC)           # 8
CT_OFF  = PUB_OFF + EC_PUBLIC_KEY_BYTES   # 8 + 65 = 73

# ---------------------------------------------------------------------------
# In-memory job store (thread-safe via lock)
# ---------------------------------------------------------------------------
# job = {
#   "status": "pending" | "running" | "done" | "error",
#   "result": {...} | None,
#   "error":  str | None,
# }

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _set_job(job_id: str, **kwargs):
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(kwargs)


def _get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        return dict(_jobs.get(job_id, {}))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def is_lossy(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in LOSSY_EXTENSIONS


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run_job(job_id: str, action: str, filepath: str, filename: str, message_text: str):
    """
    Runs in a background thread.  Reads the saved upload, performs embed/extract,
    and stores the result (or error) back into _jobs[job_id].
    """
    _set_job(job_id, status="running")

    try:
        result = {}

        if action == "embed":
            if not message_text:
                raise ValueError("Message cannot be empty for embedding.")

            # Ephemeral ECDH key exchange
            sender_ephemeral_priv, sender_pub_bytes = generate_ephemeral_keys()

            # Derive 32-byte AES key — raw key never stored, only sender pub key goes in payload
            aes_key = derive_shared_key(sender_ephemeral_priv, receiver_public_key)

            # AES-256-GCM encrypt
            ciphertext = encrypt_aes(message_text, aes_key)

            # Build payload: [magic 8B][sender_pub 65B][ciphertext...]
            final_data = MAGIC + sender_pub_bytes + ciphertext

            # ML-guided LSB embedding
            output_path = os.path.join(RESULT_FOLDER, f"stego_{job_id}.png")
            embed_stats = embed_data(filepath, final_data, output_path)

            result["stego_image"]   = f"/results/stego_{job_id}.png"
            result["embed_stats"]   = embed_stats   # safe_blocks, bits_in_safe, etc.

            # Surface ephemeral public key fingerprint (first 8 hex bytes)
            result["eph_pub_fingerprint"] = sender_pub_bytes[:8].hex()

            # Quality metrics
            result["psnr"] = calculate_psnr(filepath, output_path)
            result["ssim"] = calculate_ssim(filepath, output_path)

            # Histogram (non-fatal)
            try:
                hist_path = f"static/hist_{job_id}.png"
                save_histogram(filepath, output_path, output_path=hist_path)
                result["histogram"] = f"/{hist_path}"
            except Exception as hist_err:
                print(f"[WARNING] Histogram failed: {hist_err}")
                result["histogram"] = None

            # Report real image dimensions
            _img = cv2.imread(filepath)
            if _img is not None:
                result["img_dims"] = f"{_img.shape[1]} x {_img.shape[0]}"

            result["jpeg_warning"] = is_lossy(filename)

            # AI steganalysis — run detector on the stego image we just created
            try:
                result["ai_analysis"] = ai_analyse(output_path)
            except Exception as ai_err:
                print(f"[WARNING] AI analysis failed: {ai_err}")
                result["ai_analysis"] = None

        elif action == "extract":
            extracted = extract_data(filepath)

            if len(extracted) < CT_OFF + 1:
                result["message"] = "Invalid or corrupted stego image (payload too short)."

            elif extracted[:len(MAGIC)] == MAGIC:
                # v2: recover AES key via ECDH(receiver_priv, sender_pub)
                sender_pub_bytes = extracted[PUB_OFF:CT_OFF]
                ciphertext_blob  = extracted[CT_OFF:]
                aes_key          = derive_shared_key(receiver_private_key, sender_pub_bytes)
                decrypted        = decrypt_aes(ciphertext_blob, aes_key)
                # Surface the recovered public key fingerprint for UI proof
                result["eph_pub_fingerprint"] = sender_pub_bytes[:8].hex()
                result["message"] = f"Decrypted message: {decrypted}"

            elif extracted[:8] == b"STEGO123":
                # v1 legacy fallback
                if len(extracted) < 40:
                    result["message"] = "Corrupted v1 stego image."
                else:
                    aes_key         = extracted[8:40]
                    ciphertext_blob = extracted[40:]
                    decrypted       = decrypt_aes(ciphertext_blob, aes_key)
                    result["message"] = f"Decrypted message (legacy v1): {decrypted}"

            else:
                result["message"] = "No hidden message found in this image."

            result["jpeg_warning"] = is_lossy(filename)

        else:
            raise ValueError(f"Unknown action: '{action}'")

        _set_job(job_id, status="done", result=result, error=None)

    except Exception as exc:
        print(f"[ERROR] job {job_id}: {exc}")
        _set_job(job_id, status="error", result=None, error=str(exc))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/process", methods=["POST"])
def process():
    """
    Improvement #5 — async entry point.

    Accepts a multipart form (same fields as the old POST /), saves the
    upload, starts a background thread, and immediately returns a JSON
    response with the job_id so the client can poll /status/<job_id>.
    """
    # ── Validate file ──────────────────────────────────────────────────────
    if "image" not in request.files:
        return jsonify({"error": "No file field in request."}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400
    if not allowed_file(file.filename):
        ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "?"
        return jsonify({"error": f"Unsupported file type '.{ext}'. "
                                  f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."}), 400

    action = request.form.get("action", "")
    if action not in ("embed", "extract"):
        return jsonify({"error": f"Unknown action '{action}'."}), 400

    # ── Save upload ────────────────────────────────────────────────────────
    job_id   = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    # Prefix with job_id so concurrent uploads never collide
    safe_name = f"{job_id}_{filename}"
    filepath  = os.path.join(UPLOAD_FOLDER, safe_name)
    file.save(filepath)

    message_text = request.form.get("message", "").strip()

    # ── Register job & start thread ────────────────────────────────────────
    _set_job(job_id, status="pending", result=None, error=None)
    t = threading.Thread(
        target=_run_job,
        args=(job_id, action, filepath, filename, message_text),
        daemon=True,
    )
    t.start()

    return jsonify({"job_id": job_id}), 202


@app.route("/status/<job_id>", methods=["GET"])
def status(job_id: str):
    """
    Poll endpoint.  Returns JSON:
      { "status": "pending"|"running"|"done"|"error",
        "result": {...} | null,
        "error":  str | null }
    """
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Unknown job id."}), 404
    return jsonify(job), 200


@app.route("/analyse", methods=["POST"])
def analyse_only():
    """
    Standalone AI steganalysis endpoint.
    Accepts a single image upload, runs the neural detector synchronously,
    and returns the result immediately (no job polling required).
    """
    if "image" not in request.files:
        return jsonify({"error": "No file field in request."}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400
    if not allowed_file(file.filename):
        ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "?"
        return jsonify({"error": f"Unsupported file type '.{ext}'."}), 400

    # Save upload temporarily
    tmp_name = f"_ai_{uuid.uuid4().hex[:8]}_{secure_filename(file.filename)}"
    tmp_path = os.path.join(UPLOAD_FOLDER, tmp_name)
    file.save(tmp_path)

    try:
        result = ai_analyse(tmp_path)
        return jsonify({"ai_analysis": result}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Static file routes
# ---------------------------------------------------------------------------

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory("uploads", filename)


@app.route("/results/<filename>")
def result_file(filename):
    return send_from_directory("results", filename, as_attachment=True)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle 413 raised by Flask when MAX_CONTENT_LENGTH is exceeded."""
    return jsonify({"error": "File too large. Maximum allowed upload size is 10 MB."}), 413


if __name__ == "__main__":
    app.run(debug=True)