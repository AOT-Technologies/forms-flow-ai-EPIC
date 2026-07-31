import time
import uuid
import codecs
import logging
from datetime import datetime, timezone

import httpx
import jwt
from jwt import PyJWK, PyJWKClient

from src.config import get_settings

logger = logging.getLogger(__name__)


class LaunchExchangeError(Exception):
    """
    Raised whenever an EHR-launch exchange can't be trusted - bad signature,
    untrusted iss, expired token, or Epic no longer honoring the access
    token for the claimed patient. Callers should turn this into an HTTP
    401/400: a rejected launch is an expected outcome, not a server bug.
    """


class LaunchService:
    """
    Verifies an Epic-issued id_token from the interactive (patient/provider)
    SMART EHR-launch flow, and mints a short-lived internal assertion that
    Keycloak's EpicLaunchAssertionAuthenticator can independently verify.

    This is a completely separate trust relationship from EpicService's
    private_key_jwt backend-services flow: that one proves *ehr_connectors'*
    identity *to Epic*. This one proves something *to our own Keycloak*,
    signed with its own dedicated key (LAUNCH_ASSERTION_PRIVATE_KEY/KID) -
    never the Epic-facing key.
    """

    ASSERTION_TTL_SECONDS = 60

    def __init__(self):
        self.settings = get_settings()
        self._smart_config_cache = {}  # iss -> (jwks_uri, cached_at_epoch)
        self._smart_config_cache_ttl = 3600

    def _assert_iss_allowed(self, iss: str) -> None:
        allowed = self.settings.epic_allowed_iss_list
        if not allowed:
            logger.warning(
                "EPIC_ALLOWED_ISS is not configured - refusing all launch "
                "exchanges until an allowlist is set."
            )
            raise LaunchExchangeError("iss allowlist is not configured")
        if iss not in allowed:
            raise LaunchExchangeError(f"iss '{iss}' is not in the trusted allowlist")

    async def _get_jwks_uri(self, iss: str) -> str:
        cached = self._smart_config_cache.get(iss)
        now = time.time()
        if cached and (now - cached[1]) < self._smart_config_cache_ttl:
            return cached[0]

        discovery_url = f"{iss.rstrip('/')}/.well-known/smart-configuration"
        async with httpx.AsyncClient(timeout=self.settings.EPIC_TIMEOUT) as client:
            response = await client.get(discovery_url)
            response.raise_for_status()
            data = response.json()

        jwks_uri = data.get("jwks_uri")
        if not jwks_uri:
            raise LaunchExchangeError(f"No jwks_uri found in {discovery_url}")

        self._smart_config_cache[iss] = (jwks_uri, now)
        return jwks_uri

    async def _verify_epic_id_token(self, id_token: str, iss: str) -> dict:
        jwks_uri = await self._get_jwks_uri(iss)

        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as e:
            raise LaunchExchangeError(f"id_token header could not be parsed: {e}")

        if header.get("kid"):
            jwk_client = PyJWKClient(jwks_uri)
            try:
                signing_key = jwk_client.get_signing_key_from_jwt(id_token).key
            except jwt.PyJWTError as e:
                raise LaunchExchangeError(f"id_token verification failed: {e}")
        else:
            # Some sandboxes (e.g. launch.smarthealthit.org) omit `kid` when
            # they only have one active signing key - PyJWKClient can't match
            # a token to a key without one. Fall back to that single key
            # rather than requiring an exact kid match.
            async with httpx.AsyncClient(timeout=self.settings.EPIC_TIMEOUT) as client:
                response = await client.get(jwks_uri)
                response.raise_for_status()
            keys = response.json().get("keys", [])
            if len(keys) != 1:
                raise LaunchExchangeError(
                    f"id_token has no 'kid' and JWKS has {len(keys)} keys - "
                    "cannot determine which key to verify against"
                )
            signing_key = PyJWK(keys[0]).key

        try:
            claims = jwt.decode(
                id_token,
                signing_key,
                algorithms=["RS256", "RS384"],
                audience=self.settings.EPIC_INTERACTIVE_CLIENT_ID,
                issuer=iss,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.PyJWTError as e:
            raise LaunchExchangeError(f"id_token verification failed: {e}")

        return claims

    async def _confirm_token_is_live(self, patient_id: str, access_token: str) -> None:
        """
        Belt-and-suspenders: confirm Epic still honors *this exact* access
        token for *this exact* patient, right now - not just that the
        id_token's signature was valid at some point. This is also what
        actually binds `patient_id` to the launch, since SMART's `patient`
        launch-context value is returned alongside the token response, not
        guaranteed to be a claim inside the id_token itself.
        """
        url = f"{self.settings.EPIC_FHIR_BASE_URL.rstrip('/')}/Patient/{patient_id}"
        async with httpx.AsyncClient(timeout=self.settings.EPIC_TIMEOUT) as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/fhir+json",
                },
            )
        if response.status_code != 200:
            raise LaunchExchangeError(
                f"Epic rejected the launch's access_token for Patient/{patient_id} "
                f"(HTTP {response.status_code})"
            )

    def _mint_assertion(self, patient_id: str, fhir_user: str) -> str:
        if not self.settings.LAUNCH_ASSERTION_PRIVATE_KEY or not self.settings.LAUNCH_ASSERTION_KID:
            raise LaunchExchangeError(
                "LAUNCH_ASSERTION_PRIVATE_KEY/LAUNCH_ASSERTION_KID are not configured - "
                "run generate_launch_assertion_key.py"
            )

        private_key_pem = codecs.decode(self.settings.LAUNCH_ASSERTION_PRIVATE_KEY, "unicode_escape")

        now = int(datetime.now(tz=timezone.utc).timestamp())
        payload = {
            "iss": "ehr-connectors",
            "aud": "formsflow-keycloak",
            "patientId": patient_id,
            "fhirUser": fhir_user,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + self.ASSERTION_TTL_SECONDS,
        }
        headers = {
            "alg": "RS256",
            "typ": "JWT",
            "kid": self.settings.LAUNCH_ASSERTION_KID,
        }
        return jwt.encode(payload, private_key_pem, algorithm="RS256", headers=headers)

    async def exchange(self, id_token: str, access_token: str, iss: str, patient_id: str) -> str:
        """Full verify-then-mint pipeline. Returns a signed assertion JWT."""
        self._assert_iss_allowed(iss)
        # Establishes "Epic really issued this, for a real user, in this
        # iss" - fhirUser lives in these verified claims.
        claims = await self._verify_epic_id_token(id_token, iss)
        # Establishes "and that user's token really does grant access to
        # this specific patient, right now" - see docstring above.
        await self._confirm_token_is_live(patient_id, access_token)

        return self._mint_assertion(patient_id=patient_id, fhir_user=claims.get("fhirUser"))
