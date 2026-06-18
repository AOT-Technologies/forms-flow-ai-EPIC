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

    # Server config
    PORT: int = 8002
    HOST: str = "0.0.0.0"
    LOG_LEVEL: str = "info"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings():
    return Settings()
