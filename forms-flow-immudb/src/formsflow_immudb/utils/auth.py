"""Authentication utilities for the ImmuDB worker service."""

import time
import functools
import logging
from flask import request, jsonify, current_app
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

def require_auth(f):
    """Decorator to require Fernet-encrypted authentication token in header."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get("X-Auth-Token")
        secret_key = current_app.config.get("IMMUDB_SECRET_KEY")

        if not secret_key:
            logger.error("IMMUDB_SECRET_KEY not configured on server!")
            return jsonify({"error": "Server configuration error"}), 500

        if not token:
            logger.warning("Missing X-Auth-Token header")
            return jsonify({"error": "Authentication token missing"}), 401

        logger.debug(f"Received token: {token[:5]}... (len: {len(token)})")
        logger.debug(f"Expected secret: {secret_key[:5]}... (len: {len(secret_key if secret_key else '')})")

        try:
            # Check for raw match (fallback for simple POC clients like BPM plugin)
            if token == secret_key:
                return f(*args, **kwargs)

            fernet = Fernet(secret_key)
            # Decrypt the token
            fernet.decrypt(token.encode(), ttl=60) # 60 seconds TTL
            
            return f(*args, **kwargs)
        except Exception as e:
            logger.warning(f"Invalid or expired authentication token: {e}")
            return jsonify({"error": "Invalid or expired authentication token"}), 401

    return decorated_function
