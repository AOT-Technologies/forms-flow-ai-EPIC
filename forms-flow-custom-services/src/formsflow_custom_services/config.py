import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'default-secret-key')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-default-secret')
    JWT_EXPIRY_MINUTES = int(os.environ.get('JWT_EXPIRY_MINUTES', 60))
    MAGIC_LINK_EXPIRY_MINUTES = int(os.environ.get('MAGIC_LINK_EXPIRY_MINUTES', 15))
    MAGIC_LINK_TOKEN_URL = os.environ.get(
        'MAGIC_LINK_TOKEN_URL',
        'http://localhost:3000/custom-services/magic-links/public'
    )
    
    # FormsFlow.ai Integration
    FORMIO_DEFAULT_PROJECT_URL = os.environ.get('FORMIO_DEFAULT_PROJECT_URL')
    BPM_API_URL = os.environ.get('BPM_API_URL')
    FORMSFLOW_API_URL = os.environ.get('FORMSFLOW_API_URL')

    _kc_token_url = os.environ.get('KEYCLOAK_TOKEN_URL', '')
    KEYCLOAK_TOKEN_URL = _kc_token_url or None
    KEYCLOAK_ISSUER_URL = (
        _kc_token_url.rsplit('/protocol/openid-connect/token', 1)[0]
        if _kc_token_url else None
    )
    KEYCLOAK_BPM_CLIENT_ID = os.environ.get('KEYCLOAK_BPM_CLIENT_ID')
    KEYCLOAK_BPM_CLIENT_SECRET = os.environ.get('KEYCLOAK_BPM_CLIENT_SECRET')
    FORMIO_ROOT_EMAIL = os.environ.get('FORMIO_ROOT_EMAIL', 'admin@example.com')
    FORMIO_ROOT_PASSWORD = os.environ.get('FORMIO_ROOT_PASSWORD', 'changeme')

    # Configure LOG
    CONFIGURE_LOGS = str(os.getenv("CONFIGURE_LOGS", default="true")).lower() == "true"

    DEBUG = False
    TESTING = False

    # Swagger settings
    SWAGGER_UI_DOC_EXPANSION = 'list'
    RESTX_VALIDATE = True
    RESTX_MASK_SWAGGER = False
    ERROR_404_HELP = False


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    APPLICATION_ROOT = '/custom-services-api'


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    MAGIC_LINK_EXPIRY_MINUTES = 1


config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
}
