"""
JWKS Server - serves the public key as a JSON Web Key Set.
Epic will fetch this URL to verify JWTs signed by your private key.

Run with: python jwks_server.py
The server will be available at: http://0.0.0.0:8003/.well-known/jwks.json
"""

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

JWKS_FILE = Path(__file__).parent / "jwks.json"
_jwks_data: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load JWKS data on startup."""
    global _jwks_data
    logger.info("--- JWKS SERVER VERSION 1.2 ---")
    # Try loading from environment variable first
    env_jwks = os.environ.get("JWKS_JSON")
    if env_jwks:
        # Strip leading/trailing single or double quotes added by some .env parsers
        env_jwks = env_jwks.strip("'\"")
        try:
            _jwks_data = json.loads(env_jwks)
            kids = [k.get("kid", "NO-KID") for k in _jwks_data.get("keys", [])]
            logger.info(f"Loaded JWKS from environment variable with kids: {kids}")
        except Exception as e:
            logger.error(f"❌ Failed to parse JWKS data from environment variable: {e}")

    # Fallback to file if environment variable was not set or was invalid
    if not _jwks_data:
        logger.info(f"Reading from file: {JWKS_FILE.resolve()}")
        if not JWKS_FILE.exists():
            logger.error(
                f"❌ jwks.json not found at {JWKS_FILE} and environment variable JWKS_JSON is not set. "
                "Please run 'python generate_keys.py' first."
            )
        else:
            with open(JWKS_FILE) as f:
                _jwks_data = json.load(f)
            kids = [k.get("kid", "NO-KID") for k in _jwks_data.get("keys", [])]
            logger.info(f"Loaded JWKS from file with kids: {kids}")

    yield
    # shutdown
    logger.info("JWKS server shutting down.")


app = FastAPI(title="JWKS Server", lifespan=lifespan)


@app.get("/.well-known/jwks.json", response_class=JSONResponse)
async def get_jwks():
    """Return the JSON Web Key Set for Epic to validate your JWTs."""
    if not _jwks_data:
        return JSONResponse(
            status_code=503,
            content={"error": "JWKS not loaded. Run 'python generate_keys.py' first."}
        )
    return _jwks_data


@app.get("/health")
async def health():
    return {"status": "ok", "keys_loaded": bool(_jwks_data)}


if __name__ == "__main__":
    port = int(os.environ.get("JWKS_PORT", 8003))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
