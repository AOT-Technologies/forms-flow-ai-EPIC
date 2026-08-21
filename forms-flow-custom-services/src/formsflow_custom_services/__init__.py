import logging
import os
import sys
from flask import Flask, request
from flask_cors import CORS
from formsflow_custom_services.config import config_by_name


class PrefixMiddleware:
    """WSGI middleware to force a SCRIPT_NAME prefix on all routes."""
    def __init__(self, wsgi_app, prefix=''):
        self.wsgi_app = wsgi_app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        if self.prefix:
            environ['SCRIPT_NAME'] = self.prefix
            path_info = environ.get('PATH_INFO', '')
            if path_info.startswith(self.prefix):
                environ['PATH_INFO'] = path_info[len(self.prefix):]
        return self.wsgi_app(environ, start_response)


def create_app(config_name):
    """Application factory."""
    app = Flask(__name__)

    # Enable ProxyFix middleware to support reverse proxies / subpaths
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Get config class, default to ProductionConfig if name not found
    config_class = config_by_name.get(config_name, config_by_name['production'])
    app.config.from_object(config_class)

    # Apply PrefixMiddleware if APPLICATION_ROOT is set and not root
    prefix = app.config.get('APPLICATION_ROOT')
    if prefix and prefix != '/':
        app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix)


    enable_logger = os.getenv('ENABLE_LOGGER', 'true').strip().lower() in ('true', '1', 'yes', 'on')

    if enable_logger:
        # ── Configure Logging ──────────────────────────────────────────────────
        from formsflow_custom_services.utils.file_log_handler import register_log_handlers
        
        # Set base log level to INFO
        logging.basicConfig(level=logging.INFO)
        
        register_log_handlers(
            app,
            log_file="logs/forms-flow-custom-services.log",
            when=os.getenv("CUSTOM_SERVICES_LOG_ROTATION_WHEN", "d"),
            interval=int(os.getenv("CUSTOM_SERVICES_LOG_ROTATION_INTERVAL", "1")),
            backupCount=int(os.getenv("CUSTOM_SERVICES_LOG_BACKUP_COUNT", "7")),
            configure_log_file=app.config.get("CONFIGURE_LOGS", True),
        )
        app.logger.setLevel(logging.INFO)
        app.logger.info(f"Starting app in {config_name} mode...")
    else:
        app.logger.disabled = True



    # Import the shared restx Api from extensions
    # (must import after Flask app is created to avoid circular issues)
    from formsflow_custom_services.extensions import restx_api, cors

    # Initialize extensions
    cors.init_app(app, resources={r"/*": {"origins": "*"}})
    restx_api.init_app(app)

    # ── Feature: MagicLink ───────────────────────────────────────────────
    from formsflow_custom_services.magic_link import magic_link_ns
    restx_api.add_namespace(magic_link_ns)

    return app
