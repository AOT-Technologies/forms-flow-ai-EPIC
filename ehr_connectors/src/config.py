from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Epic FHIR endpoints
    EPIC_FHIR_BASE_URL: str = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"
    EPIC_TOKEN_URL: str = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token"

    # Your app's Client ID on the Epic on FHIR portal
    EPIC_CLIENT_ID: str

    # JWT private_key_jwt credentials (run generate_keys.py to create these)
    # EPIC_PRIVATE_KEY: PEM-formatted RSA private key (newlines encoded as \n in .env)
    EPIC_PRIVATE_KEY: str
    # EPIC_KID: the Key ID (kid) that matches the public key you registered with Epic
    EPIC_KID: str
    EPIC_TIMEOUT: float = 30.0

    # The client_id Epic expects as the `aud` claim on id_tokens issued for the
    # interactive patient/provider EHR-launch flow. Kept as its own setting
    # (rather than reusing EPIC_CLIENT_ID directly in that check) so the two
    # usages - backend-services identity vs. interactive-launch audience -
    # stay conceptually distinct even when Epic has them set to one shared
    # client_id, and can be split later without a refactor.
    EPIC_INTERACTIVE_CLIENT_ID: str

    # Comma-separated allowlist of Epic FHIR `iss` origins this service will
    # trust when resolving a launch's JWKS. Without this, a caller could pass
    # an arbitrary `iss` pointing at an attacker-controlled server and forge
    # an id_token that "verifies" against a JWKS that server made up itself.
    EPIC_ALLOWED_ISS: str = ""

    # Signing key for the internal "launch assertion" JWT handed to Keycloak
    # (see /epic/launch/exchange). Deliberately separate from EPIC_PRIVATE_KEY/
    # EPIC_KID above - that pair proves our identity *to Epic*; this pair
    # proves our identity *to our own Keycloak*. Run
    # generate_launch_assertion_key.py to create these.
    LAUNCH_ASSERTION_KID: str = ""
    LAUNCH_ASSERTION_PRIVATE_KEY: str = ""

    # Server config
    PORT: int = 8002
    HOST: str = "0.0.0.0"
    LOG_LEVEL: str = "info"

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def epic_allowed_iss_list(self) -> list:
        """EPIC_ALLOWED_ISS as a clean list, e.g. for `iss in settings.epic_allowed_iss_list`."""
        return [iss.strip() for iss in self.EPIC_ALLOWED_ISS.split(",") if iss.strip()]


@lru_cache()
def get_settings():
    return Settings()
