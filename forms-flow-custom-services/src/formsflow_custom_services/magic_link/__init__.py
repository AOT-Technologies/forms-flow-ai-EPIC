from flask_restx import Namespace

magic_link_ns = Namespace(
    'magic-links',
    description='Passwordless authentication via Magic Links for the Patient Portal',
    path='/v1/magic-links',
)

from formsflow_custom_services.magic_link import routes  # noqa: E402, F401 — registers routes onto namespace
