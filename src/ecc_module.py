# src/ecc_module.py
#
# Ephemeral ECDH (SECP256R1) key exchange.
#
# HOW IT WORKS (proper ECDH — no raw key in payload):
#   Embed flow:
#     1. Sender generates an ephemeral ECC key pair each time.
#     2. AES key = ECDH(sender_ephemeral_private, receiver_public)
#     3. Embed payload:
#        [magic 8B][sender_pub_key_bytes 65B][AES-GCM ciphertext...]
#        The **raw AES key is never stored in the image**.
#
#   Extract flow:
#     1. Read sender_pub_key_bytes from payload.
#     2. Deserialize as an EC public key.
#     3. AES key = ECDH(receiver_private, sender_pub_key)
#     4. Decrypt with recovered AES key.
#
# PERSISTENT RECEIVER KEY PAIR:
#   Previously the key pair was regenerated on every server restart,
#   meaning previously embedded images became undecryptable.
#   Now keys are loaded from PEM files on disk (created once if missing).
#
# PEM key paths (relative to project root):
#   keys/receiver_private.pem
#   keys/receiver_public.pem

import os
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization

KEYS_DIR         = "keys"
PRIVATE_KEY_PATH = os.path.join(KEYS_DIR, "receiver_private.pem")
PUBLIC_KEY_PATH  = os.path.join(KEYS_DIR, "receiver_public.pem")

# Uncompressed EC public key on SECP256R1 is always 65 bytes (0x04 prefix + X + Y)
EC_PUBLIC_KEY_BYTES = 65


# ---------------------------------------------------------------------------
# Persistent receiver key pair helpers
# ---------------------------------------------------------------------------

def _save_keys(private_key):
    """Serialise and persist a key pair to the keys/ directory."""
    os.makedirs(KEYS_DIR, exist_ok=True)

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    with open(PRIVATE_KEY_PATH, "wb") as f:
        f.write(private_pem)
    with open(PUBLIC_KEY_PATH, "wb") as f:
        f.write(public_pem)

    print(f"[ECC] Key pair written to {KEYS_DIR}/")


def load_or_generate_receiver_keys():
    """
    Load the persistent receiver key pair from disk.
    If the PEM files do not exist, generate a new pair and save it.

    Returns: (private_key, public_key)
    """
    if os.path.exists(PRIVATE_KEY_PATH):
        with open(PRIVATE_KEY_PATH, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
        public_key = private_key.public_key()
        print("[ECC] Loaded persistent receiver key pair from disk.")
        return private_key, public_key

    print("[ECC] No key files found — generating new receiver key pair.")
    private_key = ec.generate_private_key(ec.SECP256R1())
    _save_keys(private_key)
    return private_key, private_key.public_key()


# ---------------------------------------------------------------------------
# Ephemeral sender helpers (called per embed operation)
# ---------------------------------------------------------------------------

def generate_ephemeral_keys():
    """
    Generate a fresh ephemeral key pair for a single embed operation.
    The private key is discarded after the AES key is derived.

    Returns: (ephemeral_private_key, ephemeral_public_key_bytes: bytes[65])
    """
    private_key = ec.generate_private_key(ec.SECP256R1())
    pub_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    assert len(pub_bytes) == EC_PUBLIC_KEY_BYTES
    return private_key, pub_bytes


def derive_shared_key(private_key, peer_public_key) -> bytes:
    """
    Derive a 32-byte AES key via ECDH + HKDF-SHA256.

    *peer_public_key* can be a cryptography EllipticCurvePublicKey object
    or raw uncompressed bytes (65 bytes).
    """
    if isinstance(peer_public_key, (bytes, bytearray)):
        peer_public_key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), bytes(peer_public_key)
        )

    shared_secret = private_key.exchange(ec.ECDH(), peer_public_key)

    derived_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"stegai-v2",
    ).derive(shared_secret)

    return derived_key


def public_key_from_bytes(pub_bytes: bytes):
    """Deserialise an uncompressed EC point (65 bytes) into a public key object."""
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), pub_bytes)


# ---------------------------------------------------------------------------
# Legacy shim — kept so old call-sites don't immediately break
# ---------------------------------------------------------------------------

def generate_keys():
    """Deprecated shim. Use load_or_generate_receiver_keys() instead."""
    return load_or_generate_receiver_keys()