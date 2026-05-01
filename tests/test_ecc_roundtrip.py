"""
test_ecc_roundtrip.py
---------------------
Standalone diagnostic: proves (or disproves) that the ECC key exchange
and AES-GCM encryption actually produce the same key on both sides.

Run with:
    .\\venv\\Scripts\\python.exe test_ecc_roundtrip.py
"""

import sys
import os

# Fix Windows console encoding
sys.stdout.reconfigure(encoding="utf-8")

# Make sure src/ is importable
sys.path.insert(0, os.path.dirname(__file__))

from src.ecc_module import (
    load_or_generate_receiver_keys,
    generate_ephemeral_keys,
    derive_shared_key,
    EC_PUBLIC_KEY_BYTES,
)
from src.aes_module import encrypt_aes, decrypt_aes

MAGIC   = b"STEGAI02"
PUB_OFF = len(MAGIC)
CT_OFF  = PUB_OFF + EC_PUBLIC_KEY_BYTES   # 73


def test_ecdh_key_agreement():
    print("\n== Step 1: Load persistent receiver key pair ==")
    receiver_priv, receiver_pub = load_or_generate_receiver_keys()
    print(f"  receiver_priv type : {type(receiver_priv).__name__}")
    print(f"  receiver_pub  type : {type(receiver_pub).__name__}")

    print("\n== Step 2: Generate ephemeral sender key pair ==")
    sender_priv, sender_pub_bytes = generate_ephemeral_keys()
    print(f"  sender_pub_bytes length : {len(sender_pub_bytes)} bytes  (expected 65)")
    print(f"  sender_pub_bytes[0]     : 0x{sender_pub_bytes[0]:02X}  (expected 0x04 uncompressed)")

    print("\n== Step 3: EMBED side — derive AES key via ECDH ==")
    aes_key_embed = derive_shared_key(sender_priv, receiver_pub)
    print(f"  AES key (embed)  : {aes_key_embed.hex()}")
    print(f"  AES key length   : {len(aes_key_embed)} bytes  (expected 32)")

    print("\n== Step 4: EXTRACT side — derive AES key from stored pub bytes ==")
    # Simulate what the extract flow does:
    # sender_pub_bytes is read back as a raw bytes slice from the payload
    aes_key_extract = derive_shared_key(receiver_priv, sender_pub_bytes)
    print(f"  AES key (extract): {aes_key_extract.hex()}")
    print(f"  AES key length   : {len(aes_key_extract)} bytes  (expected 32)")

    match = aes_key_embed == aes_key_extract
    print(f"\n  Keys match? {'YES - ECDH agreement correct' if match else 'NO - BUG IN KEY DERIVATION'}")
    if not match:
        return False

    print("\n== Step 5: Full payload round-trip ==")
    secret_message = "Hello StegAI - ECDH is working!"
    print(f"  Plaintext: {secret_message!r}")

    # Encrypt (embed side)
    ciphertext = encrypt_aes(secret_message, aes_key_embed)
    payload    = MAGIC + sender_pub_bytes + ciphertext
    print(f"  Payload: [{len(MAGIC)}B magic][{len(sender_pub_bytes)}B pub_key][{len(ciphertext)}B ciphertext]")
    print(f"  Total  : {len(payload)} bytes")

    # Simulate extraction
    assert payload[:len(MAGIC)] == MAGIC, "Magic mismatch!"
    recovered_pub_bytes  = payload[PUB_OFF:CT_OFF]
    recovered_ciphertext = payload[CT_OFF:]

    assert recovered_pub_bytes == sender_pub_bytes, "Public key bytes changed in payload!"
    recovered_key = derive_shared_key(receiver_priv, recovered_pub_bytes)
    decrypted     = decrypt_aes(recovered_ciphertext, recovered_key)

    print(f"  Decrypted: {decrypted!r}")
    success = decrypted == secret_message
    print(f"\n  Round-trip: {'PASS' if success else 'FAIL'}")
    return success


if __name__ == "__main__":
    try:
        ok = test_ecdh_key_agreement()
        print("\n" + ("ALL TESTS PASSED - ECC key exchange is wired correctly." if ok else
                      "TEST FAILED - ECC key exchange is broken."))
        sys.exit(0 if ok else 1)
    except Exception:
        import traceback
        print(f"\nEXCEPTION during test:\n{traceback.format_exc()}")
        sys.exit(2)
