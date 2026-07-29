import secrets
import hashlib
import jwt
import os
import re
import requests
from datetime import datetime, timedelta, timezone
from flask import current_app, request
from functools import wraps


_formio_token_cache = {
    "token": None,
    "expires_at": 0
}

def get_formio_token() -> str:
    """
    Fetch a real admin token directly from the Form.io REST API.
    Caches the token in memory to avoid repetitive logins.
    """
    now = datetime.now(timezone.utc).timestamp()
    if _formio_token_cache["token"] and now < _formio_token_cache["expires_at"]:
        return _formio_token_cache["token"]

    form_api = current_app.config.get('FORMIO_DEFAULT_PROJECT_URL')
    email = current_app.config.get('FORMIO_ROOT_EMAIL')
    password = current_app.config.get('FORMIO_ROOT_PASSWORD')

    if not form_api:
        raise ValueError("FORMIO_DEFAULT_PROJECT_URL is not configured.")
    if not email or not password:
        raise ValueError("FORMIO_ROOT_EMAIL or FORMIO_ROOT_PASSWORD is not configured.")

    login_url = f"{form_api}/user/login"
    payload = {"data": {"email": email, "password": password}}

    current_app.logger.info(f"Fetching Form.io admin token from: {login_url}")
    res = requests.post(login_url, json=payload)
    current_app.logger.info(f"Form.io login response status: {res.status_code}")
    if res.status_code == 401:
        raise ValueError(
            f"Form.io admin login failed (401). "
            f"Check FORMIO_ROOT_EMAIL and FORMIO_ROOT_PASSWORD in .env. "
            f"Using: {email}"
        )
    res.raise_for_status()
    token = res.headers.get("x-jwt-token")
    if not token:
        raise ValueError("No x-jwt-token header returned from Form.io login response.")
    current_app.logger.info("Successfully fetched Form.io admin token.")

    # Cache for 3 hours (Formio tokens usually last 4h)
    _formio_token_cache["token"] = token
    _formio_token_cache["expires_at"] = now + (3 * 3600)
    return token


def generate_token() -> str:
    """Generate a cryptographically secure URL-safe token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Return a SHA-256 hash of the raw token for safe storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def build_magic_link(token: str) -> str:
    """Construct the full magic link URL with the raw token as a query param."""
    base_url = current_app.config.get('MAGIC_LINK_TOKEN_URL')
    return f"{base_url}?token={token}"


def create_jwt(payload: dict, expiry_minutes: int = None) -> str:
    """Create a signed JWT access token for a given payload."""
    secret = current_app.config.get('JWT_SECRET_KEY')
    minutes = expiry_minutes if expiry_minutes is not None else current_app.config.get('JWT_EXPIRY_MINUTES', 60)

    # Add standard claims if not present
    if 'iat' not in payload:
        payload['iat'] = datetime.now(timezone.utc)
    if 'exp' not in payload:
        payload['exp'] = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    return jwt.encode(payload, secret, algorithm='HS256')


def extract_form_id(url: str) -> str:
    """Extract form ID from a form URL."""
    if not url:
        return None
    match = re.search(r'/form/([a-z0-9]{24})', url, re.I)
    return match.group(1) if match else None


def extract_submission_id(url: str) -> str:
    """Extract submission ID from a form URL."""
    if not url:
        return None
    match = re.search(r'/submission/([a-z0-9]{24})', url, re.I)
    return match.group(1) if match else None


def get_kc_admin_token() -> str:
    """Get an admin token from Keycloak using client credentials."""
    token_url = current_app.config.get('KEYCLOAK_TOKEN_URL')
    client_id = current_app.config.get('KEYCLOAK_BPM_CLIENT_ID')
    client_secret = current_app.config.get('KEYCLOAK_BPM_CLIENT_SECRET')

    if not all([token_url, client_id, client_secret]):
        raise ValueError("Keycloak configuration is missing.")

    data = {
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret
    }

    current_app.logger.info(f"Fetching Keycloak admin token from: {token_url}")
    response = requests.post(token_url, data=data)
    if not response.ok:
        current_app.logger.error(f"Failed to fetch Keycloak token: {response.status_code} {response.text}")
    response.raise_for_status()
    current_app.logger.info("Successfully fetched Keycloak admin token.")
    return response.json().get('access_token')


def token_required(f):
    """
    Decorator to validate the Keycloak Bearer token in the Authorization header.
    It uses the Keycloak introspection endpoint for maximum security.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(" ")[1]
        
        if not token:
            current_app.logger.warning("Authorization header missing or invalid format.")
            return {'message': 'Authorization token is missing!'}, 401
        
        try:
            # 1. Get Keycloak config
            token_url = current_app.config.get('KEYCLOAK_TOKEN_URL')
            client_id = current_app.config.get('KEYCLOAK_BPM_CLIENT_ID')
            client_secret = current_app.config.get('KEYCLOAK_BPM_CLIENT_SECRET')

            if not token_url:
                current_app.logger.error("KEYCLOAK_TOKEN_URL not configured.")
                return {'message': 'Server authentication misconfigured.'}, 500

            # 2. Derive introspection URL (standard OIDC path)
            introspect_url = token_url.replace('/token', '/token/introspect')
            
            # 3. Call introspection endpoint
            data = {
                'token': token,
                'client_id': client_id,
                'client_secret': client_secret
            }
            
            current_app.logger.info(f"Calling Keycloak introspection endpoint: {introspect_url}")
            response = requests.post(introspect_url, data=data)
            current_app.logger.info(f"Keycloak introspection response status: {response.status_code}")
            if not response.ok:
                current_app.logger.error(f"Keycloak introspection failed: {response.status_code} {response.text}")
                return {
                    'message': 'Failed to validate token with Keycloak.',
                    'status_code': response.status_code,
                    'error': response.text
                }, 401
            
            res_json = response.json()
            if not res_json.get('active'):
                current_app.logger.warning(f"Token is inactive or expired. Keycloak response: {res_json}")
                return {
                    'message': 'Invalid or expired token.',
                    'details': res_json
                }, 401

            # Validate issuer
            expected_iss = current_app.config.get('KEYCLOAK_ISSUER_URL')
            actual_iss = res_json.get('iss', '')
            if expected_iss and actual_iss != expected_iss:
                current_app.logger.warning(f"Token issuer mismatch. Expected: {expected_iss}, Got: {actual_iss}")
                return {'message': 'Token issuer is not trusted.'}, 401

            # Validate audience
            expected_client = current_app.config.get('KEYCLOAK_BPM_CLIENT_ID')
            actual_client = res_json.get('client_id', '')
            if actual_client != expected_client:
                current_app.logger.warning(f"Token client mismatch. Expected: {expected_client}, Got: {actual_client}")
                return {'message': 'Token audience is not valid for this service.'}, 401

            # Token is valid!
            pass

        except Exception as e:
            current_app.logger.error(f"Unexpected error during token validation: {str(e)}")
            return {
                'message': 'Internal server error during authentication.',
                'error': str(e)
            }, 500

        return f(*args, **kwargs)
            
    return decorated
