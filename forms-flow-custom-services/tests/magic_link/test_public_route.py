import pytest
import responses
import jwt
from formsflow_custom_services import create_app


@pytest.fixture
def app():
    app = create_app('testing')
    app.config['FORMIO_DEFAULT_PROJECT_URL'] = 'https://real-form.io/api'
    app.config['BPM_API_URL'] = 'https://real-bpm.ai/api'
    app.config['KEYCLOAK_TOKEN_URL'] = 'https://real-keycloak.com/token'
    app.config['KEYCLOAK_BPM_CLIENT_ID'] = 'test-client'
    app.config['KEYCLOAK_BPM_CLIENT_SECRET'] = 'test-secret'
    app.config['KEYCLOAK_ISSUER_URL'] = 'https://real-keycloak.com'
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


# Helper to setup Keycloak mocks
def setup_kc_mocks(config, pid="pid-1"):
    responses.add(
        responses.POST,
        "https://real-keycloak.com/token/introspect",
        json={"active": True, "iss": "https://real-keycloak.com", "client_id": "test-client"},
        status=200,
    )
    responses.add(
        responses.POST,
        config['KEYCLOAK_TOKEN_URL'],
        json={'access_token': 'kc-token-123'},
        status=200
    )
    responses.add(
        responses.POST,
        f"{config['BPM_API_URL']}/engine-rest-ext/process-instance/{pid}/variables",
        status=204
    )


class TestMagicLinkPublicRoute:

    @responses.activate
    def test_public_returns_form_details_success(self, client, app):
        """Happy path for public endpoint: decodes JWT and returns form schema."""
        config = app.config
        email = "patient@example.com"
        pid = "pid-1"

        setup_kc_mocks(config, pid)

        # 1. Request magic link to generate valid token
        resp = client.post(
            '/v1/magic-links/request',
            json={
                'email': email,
                'processInstanceId': pid,
                'formId': 'form-123'
            },
            headers={'Authorization': 'Bearer test-token'}
        )
        assert resp.status_code == 200
        jwt_token = resp.get_json()['magic_link'].split('=')[-1]

        # 2. Mock external calls for get-form details
        responses.add(
            responses.GET,
            f"{config['BPM_API_URL']}/engine-rest-ext/v1/task?processInstanceId={pid}",
            json=[{'id': 'task-123'}],
            status=200,
        )
        responses.add(
            responses.GET,
            f"{config['BPM_API_URL']}/engine-rest-ext/v1/task/task-123/variables",
            json={
                'formUrl': {'value': 'http://formio/form/507f1f77bcf86cd799439011/submission/507f1f77bcf86cd799439012'},
                'token': {'value': jwt_token, 'type': 'String'}
            },
            status=200
        )
        responses.add(
            responses.POST,
            f"{config['FORMIO_DEFAULT_PROJECT_URL']}/user/login",
            json={'status': 'ok'},
            headers={'x-jwt-token': 'formio-jwt-token-123'},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{config['FORMIO_DEFAULT_PROJECT_URL']}/form/507f1f77bcf86cd799439011",
            json={'title': 'Test Form', 'components': []},
            status=200
        )
        responses.add(
            responses.GET,
            f"{config['FORMIO_DEFAULT_PROJECT_URL']}/form/507f1f77bcf86cd799439011/submission/507f1f77bcf86cd799439012",
            json={'data': {'firstName': 'Jane'}},
            status=200
        )

        # 3. Call public GET endpoint
        response = client.get(f'/v1/magic-links/public?token={jwt_token}')
        assert response.status_code == 200
        data = response.get_json()
        assert data['formId'] == '507f1f77bcf86cd799439011'
        assert data['taskId'] == 'task-123'
        assert data['prefill']['firstName'] == 'Jane'

    def test_public_missing_token_returns_400(self, client):
        response = client.get('/v1/magic-links/public')
        assert response.status_code == 400
        assert response.get_json()['error'] == 'missing_token'

    def test_public_invalid_token_returns_401(self, client):
        response = client.get('/v1/magic-links/public?token=invalid-jwt-token-xyz')
        assert response.status_code == 401
        assert response.get_json()['error'] == 'invalid_token'


class TestMagicLinkResendEdgeCases:

    @responses.activate
    def test_resend_no_history_returns_404(self, client, app):
        """Resend requests for unknown emails should return 404."""
        setup_kc_mocks(app.config, "pid-1")
        response = client.post(
            '/v1/magic-links/resend',
            json={'email': 'nonexistent@example.com'},
            headers={'Authorization': 'Bearer test-token'}
        )
        assert response.status_code == 404
        assert response.get_json()['error'] == 'no_history'
