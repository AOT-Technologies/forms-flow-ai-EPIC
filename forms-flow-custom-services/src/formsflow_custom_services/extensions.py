from flask_restx import Api
from flask_cors import CORS

# NOTE: Named `restx_api` to avoid shadowing the `api/` package on import
restx_api = Api(
    title='Forms Flow AI Custom Services',
    version='1.0',
    description=(
        'Custom service APIs including patient portal features like '
        'MagicLink passwordless authentication.'
    ),
    doc='/',
    authorizations={
        'Bearer': {
            'type': 'apiKey',
            'in': 'header',
            'name': 'Authorization',
            'description': 'Enter: **Bearer &lt;JWT&gt;**',
        }
    },
)

cors = CORS()
