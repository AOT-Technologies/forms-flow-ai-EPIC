"""
Run this script ONCE to:
  1. Generate an RSA-384 key pair
  2. Save the private key to private_key.pem
  3. Save the public JWK Set to jwks.json
  4. Print the values you need to put in .env
"""

import json
import uuid
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend


def int_to_base64url(n: int) -> str:
    """Convert a large integer to base64url-encoded bytes."""
    byte_length = (n.bit_length() + 7) // 8
    n_bytes = n.to_bytes(byte_length, byteorder="big")
    return base64.urlsafe_b64encode(n_bytes).rstrip(b"=").decode("ascii")


def main():
    # 1. Generate RSA 2048-bit private key (Epic recommends RS384)
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    # 2. Save private key to PEM file
    pem_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )
    with open("private_key.pem", "wb") as f:
        f.write(pem_bytes)
    print("✅ Private key saved to: private_key.pem")

    # 3. Build the JWK from the public key
    pub_key = private_key.public_key()
    pub_numbers = pub_key.public_key().public_numbers() if hasattr(pub_key, 'public_key') else pub_key.public_numbers()
    
    kid = str(uuid.uuid4())
    jwk = {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS384",
        "n": int_to_base64url(pub_numbers.n),
        "e": int_to_base64url(pub_numbers.e),
    }
    jwks = {"keys": [jwk]}

    # 4. Save JWKS to file
    with open("jwks.json", "w") as f:
        json.dump(jwks, f, indent=2)
    print("✅ JWKS saved to: jwks.json")

    # 5. Print .env values
    private_key_single_line = pem_bytes.decode().replace("\n", "\\n")
    print("\n--- Add these to your .env file ---")
    print(f"EPIC_KID={kid}")
    print(f"EPIC_PRIVATE_KEY={private_key_single_line}")
    print("-----------------------------------")
    print("\n⚠️  NEXT STEP: Register your JWKS URL or upload jwks.json in the Epic on FHIR portal.")
    print("   JWKS endpoint will be: http://localhost:8003/.well-known/jwks.json")
    print("   (use ngrok or similar to expose it as HTTPS if Epic requires a JWK Set URL)")


if __name__ == "__main__":
    main()
