# src/aes_module.py
#
# AES-256-GCM (authenticated encryption with associated data).
# Replaces the previous AES-256-CFB implementation.
#
# Why GCM over CFB?
#   CFB gives confidentiality only.  GCM also produces a 16-byte
#   authentication tag that detects any bit-flip or truncation in
#   the ciphertext *before* decryption — preventing chosen-ciphertext
#   attacks and silent data corruption.
#
# Wire format (returned by encrypt_aes):
#   [12-byte nonce][16-byte auth-tag][ciphertext...]

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os

NONCE_LEN = 12   # GCM standard nonce size
TAG_LEN   = 16   # GCM auth-tag is always 16 bytes (appended by the library)


def encrypt_aes(message: str, key: bytes) -> bytes:
    """
    Encrypt *message* with AES-256-GCM using *key* (32 bytes).

    Returns: nonce (12 B) + ciphertext+tag (len(message)+16 B)
    """
    if len(key) != 32:
        raise ValueError(f"AES key must be 32 bytes, got {len(key)}")

    nonce = os.urandom(NONCE_LEN)
    aesgcm = AESGCM(key)
    # AESGCM.encrypt returns ciphertext with the 16-byte tag already appended
    ciphertext_with_tag = aesgcm.encrypt(nonce, message.encode("utf-8"), None)
    return nonce + ciphertext_with_tag


def decrypt_aes(ciphertext: bytes, key: bytes) -> str:
    """
    Decrypt and *authenticate* the ciphertext produced by encrypt_aes.

    Raises cryptography.exceptions.InvalidTag if the payload was tampered.
    Returns the original plaintext string.
    """
    if len(key) != 32:
        raise ValueError(f"AES key must be 32 bytes, got {len(key)}")

    if len(ciphertext) < NONCE_LEN + TAG_LEN:
        raise ValueError("Ciphertext is too short to be valid AES-GCM output")

    nonce           = ciphertext[:NONCE_LEN]
    ciphertext_tag  = ciphertext[NONCE_LEN:]   # ciphertext + 16-byte tag

    aesgcm  = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext_tag, None)  # raises on bad tag
    return plaintext.decode("utf-8", errors="replace")