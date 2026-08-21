from flask_restx import fields
from formsflow_custom_services.magic_link import magic_link_ns as ns

# ── Request models ──────────────────────────────────────────────────────────

request_link_model = ns.model('RequestMagicLink', {
    'email': fields.String(required=True, description='Patient email address', example='patient@example.com'),
    'processInstanceId': fields.String(required=True, description='Camunda Process Instance ID', example='12345-abcde'),
    'iss': fields.String(required=False, description='Issuer for the JWT', default='surgical-portal-service'),
    'aud': fields.String(required=False, description='Audience for the JWT', default='public-patient-intake'),
    'token_expiry': fields.Integer(required=False, description='Token expiry in minutes (overrides env default)', example=60),
})

resend_model = ns.model('ResendMagicLink', {
    'email': fields.String(required=True, description='Patient email address to resend link to', example='patient@example.com'),
})

submit_form_model = ns.model('SubmitFormRequest', {
    'token': fields.String(required=True, description='Magic link token'),
    'data': fields.Raw(required=True, description='The form data to submit'),
    'taskId': fields.String(required=True, description='Camunda Task ID'),
    'formId': fields.String(required=True, description='Form.io Form ID'),
})

revoke_token_model = ns.model('RevokeTokenRequest', {
    'token': fields.String(required=True, description='Magic link token or JWT to revoke'),
})

# ── Response models ─────────────────────────────────────────────────────────

success_model = ns.model('MagicLinkSuccess', {
    'message': fields.String(description='Human-readable status message'),
    'magic_link': fields.String(description='The generated magic link URL'),
    'token': fields.String(description='The generated JWT token'),
    'expires_in_minutes': fields.Integer(description='Token validity in minutes'),
})

form_details_model = ns.model('FormDetailsResponse', {
    'schema': fields.Raw(description='Form.io Form Schema'),
    'prefill': fields.Raw(description='Prefill data for the form'),
    'taskId': fields.String(description='Camunda Task ID'),
    'formId': fields.String(description='Form.io Form ID'),
})

error_model = ns.model('ErrorResponse', {
    'error': fields.String(description='Error type identifier'),
    'message': fields.String(description='Human-readable error description'),
    'details': fields.Raw(description='Additional error details'),
    'status_code': fields.Integer(description='HTTP status code from upstream'),
})
