import pytest
import responses
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
        f"{config['BPM_API_URL']}/engine-rest-ext/v1/process-instance/{pid}/variables",
        status=204
    )


# ── Request endpoint ────────────────────────────────────────────────────────

class TestRequestMagicLink:

    @responses.activate
    def test_request_returns_magic_link(self, client, app):
        setup_kc_mocks(app.config, "pid-1")
        response = client.post(
            '/v1/magic-links/request',
            json={
                'email': 'patient@example.com',
                'processInstanceId': 'pid-1',
                'formId': 'form-1'
            },
            headers={'Authorization': 'Bearer test-token'}
        )
        assert response.status_code == 200
        data = response.get_json()
        assert 'magic_link' in data
        assert 'patient@example.com' not in data['magic_link']  # email not in URL

    @responses.activate
    def test_request_missing_email_returns_400(self, client, app):
        setup_kc_mocks(app.config, "pid-1")
        response = client.post(
            '/v1/magic-links/request',
            json={},
            headers={'Authorization': 'Bearer test-token'}
        )
        assert response.status_code == 400

    @responses.activate
    def test_request_normalises_email_to_lowercase(self, client, app):
        setup_kc_mocks(app.config, "pid-1")
        response = client.post(
            '/v1/magic-links/request',
            json={
                'email': 'PATIENT@EXAMPLE.COM',
                'processInstanceId': 'pid-1',
                'formId': 'form-1'
            },
            headers={'Authorization': 'Bearer test-token'}
        )
        assert response.status_code == 200


# ── Resend endpoint ─────────────────────────────────────────────────────────

class TestResendMagicLink:

    @responses.activate
    def test_resend_returns_new_link(self, client, app):
        setup_kc_mocks(app.config, "p1")
        
        # 1. First generate the link
        client.post(
            '/v1/magic-links/request',
            json={'email': 'r@example.com', 'processInstanceId': 'p1', 'formId': 'f1'},
            headers={'Authorization': 'Bearer test-token'}
        )
        
        # 2. Resend it
        response = client.post(
            '/v1/magic-links/resend',
            json={'email': 'r@example.com'},
            headers={'Authorization': 'Bearer test-token'}
        )
        assert response.status_code == 200
        assert 'magic_link' in response.get_json()

    @responses.activate
    def test_resend_missing_email_returns_400(self, client, app):
        setup_kc_mocks(app.config, "p1")
        response = client.post(
            '/v1/magic-links/resend',
            json={},
            headers={'Authorization': 'Bearer test-token'}
        )
        assert response.status_code == 400


# ── Health endpoint ─────────────────────────────────────────────────────────

class TestMagicLinkHealth:

    def test_health_returns_200(self, client):
        response = client.get('/v1/magic-links/health')
        assert response.status_code == 200
        assert response.get_json()['status'] == 'healthy'
