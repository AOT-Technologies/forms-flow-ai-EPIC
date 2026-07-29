from flask import request
from flask_restx import Resource

from formsflow_custom_services.magic_link import magic_link_ns as ns
from formsflow_custom_services.magic_link.models import (
    request_link_model,
    resend_model,
    success_model,
    form_details_model,
    submit_form_model,
    revoke_token_model,
    error_model,
)
from formsflow_custom_services.magic_link import service
from formsflow_custom_services.magic_link.utils import token_required


def _get_form(token):
    result, status_code = service.get_form_details(token)
    if status_code != 200:
        ns.abort(status_code, **result)
    return result, 200


# ── GET /v1/magic-links/public ───────────────────────────────────────────

@ns.route('/public')
class MagicLinkPublic(Resource):

    @ns.doc('magic_link_public', security=None)
    @ns.param('token', 'JWT token from the magic link', _in='query', required=True)
    @ns.response(200, 'Form details fetched successfully', form_details_model)
    @ns.response(401, 'Unauthorized, expired, or revoked token', error_model)
    @ns.response(404, 'Task not found', error_model)
    @ns.response(500, 'FormsFlow.ai API error', error_model)
    def get(self):
        """Patient entry point — decodes token and returns form schema."""
        token = request.args.get('token', '').strip()
        if not token:
            ns.abort(400, error='missing_token', message='Token is required.')
        return _get_form(token)


# ── GET /v1/magic-links/get-form ─────────────────────────────────────────

@ns.route('/get-form')
class MagicLinkGetForm(Resource):

    @ns.doc('magic_link_get_form', security=None)
    @ns.param('token', 'JWT token from the magic link', _in='query', required=True)
    @ns.response(200, 'Form details fetched successfully', form_details_model)
    @ns.response(401, 'Unauthorized, expired, or revoked token', error_model)
    @ns.response(404, 'Task not found', error_model)
    @ns.response(500, 'FormsFlow.ai API error', error_model)
    def get(self):
        """Fetch form schema using token — called by the FormsFlow frontend."""
        token = request.args.get('token', '').strip()
        if not token:
            ns.abort(400, error='missing_token', message='Token is required.')
        return _get_form(token)


# ── POST /v1/magic-links/submit-form ─────────────────────────────────────

@ns.route('/submit-form')
class SubmitForm(Resource):

    @ns.doc('magic_link_submit_form', security=None)
    @ns.expect(submit_form_model, validate=True)
    @ns.response(200, 'Form submitted and task completed')
    @ns.response(401, 'Unauthorized', error_model)
    @ns.response(500, 'Processing error', error_model)
    def post(self):
        """Submit form data and complete the Camunda task."""
        data = request.get_json()
        token = data.get('token', '')
        if '?token=' in token:
            token = token.split('?token=', 1)[-1].strip()
        form_data = data.get('data')
        task_id = data.get('taskId')
        form_id = data.get('formId')

        result, status_code = service.submit_form_details(token, form_data, task_id, form_id)
        if status_code != 200:
            ns.abort(status_code, **result)
        return result, 200


# ── POST /v1/magic-links/request ─────────────────────────────────────────

@ns.route('/request')
@ns.doc(security='Bearer')
class RequestMagicLink(Resource):

    @ns.expect(request_link_model, validate=True)
    @ns.response(200, 'Magic link generated', success_model)
    @ns.response(400, 'Validation error', error_model)
    @ns.response(401, 'Unauthorized - Invalid or missing token', error_model)
    @ns.response(500, 'Internal Server Error', error_model)
    @token_required
    def post(self):
        """Generate a magic link — called by the Camunda workflow."""
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        process_instance_id = data.get('processInstanceId')
        iss = data.get('iss')
        aud = data.get('aud')
        token_expiry = data.get('token_expiry')

        if not email or not process_instance_id:
            ns.abort(400, error='missing_fields', message='Email and processInstanceId are required.')

        result = service.request_magic_link(
            email,
            process_instance_id=process_instance_id,
            iss=iss,
            aud=aud,
            token_expiry=token_expiry,
        )
        return result, 200


# ── POST /v1/magic-links/revoke ──────────────────────────────────────────

@ns.route('/revoke')
@ns.doc(security='Bearer')
class RevokeToken(Resource):

    @ns.expect(revoke_token_model, validate=True)
    @ns.response(200, 'Token revoked successfully')
    @ns.response(401, 'Unauthorized', error_model)
    @token_required
    def post(self):
        """Revoke a magic link token."""
        data = request.get_json()
        token = data.get('token')
        result, status_code = service.revoke_token(token)
        return result, status_code


# ── POST /v1/magic-links/resend ──────────────────────────────────────────

@ns.route('/resend')
@ns.doc(security='Bearer')
class ResendMagicLink(Resource):

    @ns.expect(resend_model, validate=True)
    @ns.response(200, 'New magic link generated', success_model)
    @ns.response(401, 'Unauthorized', error_model)
    @token_required
    def post(self):
        """Resend a magic link to the patient."""
        data = request.get_json()
        email = data.get('email', '').strip().lower()

        if not email:
            ns.abort(400, error='missing_field', message='Email is required.')

        result, status_code = service.resend_magic_link(email)
        if status_code != 200:
            ns.abort(status_code, **result)
        return result, 200


# ── GET /v1/magic-links/health ───────────────────────────────────────────

@ns.route('/health')
class MagicLinkHealth(Resource):

    @ns.doc('magic_link_health', security=None)
    @ns.response(200, 'Service is healthy')
    def get(self):
        return {'status': 'healthy', 'service': 'magic_link'}, 200
