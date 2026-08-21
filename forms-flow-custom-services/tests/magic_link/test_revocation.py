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


# Helper to setup Keycloak and BPM mocks
def setup_common_mocks(config, pid="p1"):
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


class TestRevocationAndMockMode:

    @responses.activate
    def test_mock_mode_fallback(self, client, app):
        config = app.config
        pid = "p1"
        setup_common_mocks(config, pid)

        # 1. Setup magic link (returns JWT directly now)
        resp = client.post('/v1/magic-links/request', json={
            'email': 'mock@example.com',
            'processInstanceId': pid,
            'formId': '697a450b1b1e8b849d603300'
        }, headers={'Authorization': 'Bearer test-token'})
        assert resp.status_code == 200
        jwt_token = resp.get_json()['magic_link'].split('=')[-1]

        # 2. Mock magic APIs for get-form
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
            json={'data': {'firstName': 'Sankar'}},
            status=200
        )

        # 3. Call get-form directly with the JWT
        response = client.get(f'/v1/magic-links/get-form?token={jwt_token}')

        assert response.status_code == 200
        data = response.get_json()
        assert data['prefill']['firstName'] == 'Sankar'
        assert 'schema' in data

    @responses.activate
    def test_revoke_magic_token(self, client, app):
        config = app.config
        pid = "p1"
        setup_common_mocks(config, pid)

        # 1. Request magic link
        resp = client.post('/v1/magic-links/request', json={
            'email': 'revoke@example.com',
            'processInstanceId': pid,
            'formId': 'f1'
        }, headers={'Authorization': 'Bearer test-token'})
        assert resp.status_code == 200
        jwt_token = resp.get_json()['magic_link'].split('=')[-1]

        # 2. Revoke it
        rev_res = client.post('/v1/magic-links/revoke', json={'token': jwt_token}, headers={'Authorization': 'Bearer test-token'})
        assert rev_res.status_code == 200

        # 3. Try to use it (should fail)
        get_res = client.get(f'/v1/magic-links/get-form?token={jwt_token}')
        assert get_res.status_code == 401
        assert get_res.get_json()['error'] == 'token_revoked'
