"""
Run this script ONCE to add a SECOND signing key, dedicated to the internal
"launch assertion" JWT that ehr_connectors mints for Keycloak (see
/epic/launch/exchange). This is deliberately a different keypair from the one
generate_keys.py produces:

  - EPIC_PRIVATE_KEY/EPIC_KID (generate_keys.py) let *Epic* verify JWTs
    ehr_connectors sends *to Epic* (private_key_jwt backend-services auth).
  - LAUNCH_ASSERTION_PRIVATE_KEY/LAUNCH_ASSERTION_KID (this script) let *our
    own Keycloak* verify JWTs ehr_connectors sends *to Keycloak*.

Keeping them separate means rotating one never affects the other.

The public half is merged into the SAME jwks.json (and therefore served by
the same jwks_server.py) as a second entry in the "keys" array, distinguished
by "kid" - JWKS natively supports multiple keys, so no second server/endpoint
is needed.
"""

import json
import uuid
import base64
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

JWKS_FILE = Path(__file__).parent / "jwks.json"
PRIVATE_KEY_FILE = Path(__file__).parent / "launch_assertion_private_key.pem"


def int_to_base64url(n: int) -> str:
    """Convert a large integer to base64url-encoded bytes."""
    byte_length = (n.bit_length() + 7) // 8
    n_bytes = n.to_bytes(byte_length, byteorder="big")
    return base64.urlsafe_b64encode(n_bytes).rstrip(b"=").decode("ascii")


def main():
    # 1. Generate a fresh RSA 2048-bit private key - independent of the
    #    Epic-facing key, even though the algorithm/size happen to match.
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    # 2. Save private key to its own PEM file (never merge this with
    #    private_key.pem - different purpose, different trust boundary).
    pem_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )
    with open(PRIVATE_KEY_FILE, "wb") as f:
        f.write(pem_bytes)
    print(f"Private key saved to: {PRIVATE_KEY_FILE.name}")

    # 3. Build the JWK from the public key. RS256 here (not RS384) - this
    #    key only ever signs/verifies against our own Keycloak, not Epic, so
    #    there's no Epic-imposed algorithm requirement to match.
    pub_key = private_key.public_key()
    pub_numbers = pub_key.public_numbers()

    kid = str(uuid.uuid4())
    jwk = {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": int_to_base64url(pub_numbers.n),
        "e": int_to_base64url(pub_numbers.e),
    }

    # 4. Merge into the existing jwks.json rather than overwriting it, so
    #    the Epic-facing key already in there survives untouched.
    if JWKS_FILE.exists():
        with open(JWKS_FILE) as f:
            jwks = json.load(f)
    else:
        jwks = {"keys": []}

    jwks.setdefault("keys", [])
    # Drop any previous launch-assertion key (alg=RS256) before adding the
    # new one, so re-running this script rotates rather than accumulates.
    jwks["keys"] = [k for k in jwks["keys"] if k.get("alg") != "RS256"]
    jwks["keys"].append(jwk)

    with open(JWKS_FILE, "w") as f:
        json.dump(jwks, f, indent=2)
    print(f"Launch-assertion public key merged into: {JWKS_FILE.name}")

    # 5. Print .env values
    private_key_single_line = pem_bytes.decode().replace("\n", "\\n")
    print("\n--- Add these to your .env file ---")
    print(f"LAUNCH_ASSERTION_KID={kid}")
    print(f"LAUNCH_ASSERTION_PRIVATE_KEY={private_key_single_line}")
    print("-----------------------------------")
    print("\nNo new endpoint needed - the existing jwks_server.py already")
    print("serves this key alongside the Epic-facing one, since both now")
    print("live in the same jwks.json. Keycloak's authenticator should")
    print("fetch that same JWKS URL and pick the key by 'kid'.")


if __name__ == "__main__":
    main()
