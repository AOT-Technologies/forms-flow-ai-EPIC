import pytest
import responses
import jwt
from formsflow_custom_services import create_app


@pytest.fixture
def app():
    app = create_app('testing')
    # Set non-placeholder URLs to bypass service.py's mock mode check
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


# ── FormsFlow Integration Tests ──────────────────────────────────────────────

TASK_DEF_KEY = "review-form-task"


class TestFormsFlowIntegration:

    @responses.activate
    def test_get_form_details_success(self, client, app):
        """Happy path: successfully returns active Camunda task."""
        config = app.config
        email = "test@example.com"
        pid = "proc-123"

        # Mock Keycloak token introspection
        responses.add(
            responses.POST,
            "https://real-keycloak.com/token/introspect",
            json={"active": True, "iss": "https://real-keycloak.com", "client_id": "test-client"},
            status=200,
        )

        # Mock Keycloak token and variables POST calls needed during link generation
        responses.add(responses.POST, config['KEYCLOAK_TOKEN_URL'],
                      json={'access_token': 'kc-token-123'}, status=200)
        # Mock variable POST calls (magicLink and token)
        responses.add(responses.POST,
                      f"{config['BPM_API_URL']}/engine-rest-ext/v1/process-instance/{pid}/variables",
                      status=204)

        response = client.post(
            '/v1/magic-links/request',
            json={
                'email': email,
                'processInstanceId': pid,
            },
            headers={'Authorization': 'Bearer test-jwt-token-abc'}
        )
        assert response.status_code == 200, response.get_json()

        # 2. Extract JWT from link
        jwt_token = response.get_json()['magic_link'].split('=')[-1]

        # 3. Mock External APIs for get-form call
        responses.add(
            responses.GET,
            f"{config['BPM_API_URL']}/engine-rest-ext/v1/task?processInstanceId={pid}",
            json=[{'id': 'task-123'}],
            status=200,
        )

        responses.add(responses.GET, f"{config['BPM_API_URL']}/engine-rest-ext/v1/task/task-123/variables",
                      json={
                          'formUrl': {'value': 'http://formio/form/507f1f77bcf86cd799439011/submission/507f1f77bcf86cd799439012'},
                          'token': {'value': jwt_token, 'type': 'String'}
                      },
                      status=200)

        responses.add(
            responses.POST,
            f"{config['FORMIO_DEFAULT_PROJECT_URL']}/user/login",
            json={'status': 'ok'},
            headers={'x-jwt-token': 'formio-jwt-token-123'},
            status=200,
        )

        responses.add(responses.GET, f"{config['FORMIO_DEFAULT_PROJECT_URL']}/form/507f1f77bcf86cd799439011",
                      json={'title': 'Test Form', 'components': []}, status=200)

        responses.add(responses.GET, f"{config['FORMIO_DEFAULT_PROJECT_URL']}/form/507f1f77bcf86cd799439011/submission/507f1f77bcf86cd799439012",
                      json={'data': {'firstName': 'John'}}, status=200)

        # 4. Call Endpoint
        response = client.get(f'/v1/magic-links/get-form?token={jwt_token}')

        assert response.status_code == 200
        data = response.get_json()
        assert data['formId'] == '507f1f77bcf86cd799439011'
        assert data['taskId'] == 'task-123'
        assert data['prefill']['firstName'] == 'John'

    @responses.activate
    def test_get_form_rejects_when_no_active_tasks(self, client, app):
        """
        Scenario: the workflow has already completed — no active tasks returned.
        The existing 404 guard fires.
        """
        config = app.config
        email = "done@example.com"
        pid = "proc-done"

        # Mock Keycloak token introspection
        responses.add(
            responses.POST,
            "https://real-keycloak.com/token/introspect",
            json={"active": True, "iss": "https://real-keycloak.com", "client_id": "test-client"},
            status=200,
        )

        # Mock Keycloak token and variables POST calls needed during link generation
        responses.add(responses.POST, config['KEYCLOAK_TOKEN_URL'],
                      json={'access_token': 'kc-token-123'}, status=200)
        responses.add(responses.POST,
                      f"{config['BPM_API_URL']}/engine-rest-ext/v1/process-instance/{pid}/variables",
                      status=204)

        response = client.post(
            '/v1/magic-links/request',
            json={
                'email': email,
                'processInstanceId': pid,
            },
            headers={'Authorization': 'Bearer test-jwt-token-abc'}
        )
        jwt_token = response.get_json()['magic_link'].split('=')[-1]

        # No active tasks — workflow completed
        responses.add(
            responses.GET,
            f"{config['BPM_API_URL']}/engine-rest-ext/v1/task?processInstanceId={pid}",
            json=[],
            status=200,
        )

        responses.add(
            responses.POST,
            f"{config['FORMIO_DEFAULT_PROJECT_URL']}/user/login",
            json={'status': 'ok'},
            headers={'x-jwt-token': 'formio-jwt-token-123'},
            status=200,
        )

        responses.add(responses.GET, f"{config['BPM_API_URL']}/engine-rest-ext/v1/process-instance/{pid}/variables",
                      json={
                          'token': {'value': jwt_token, 'type': 'String'}
                      },
                      status=200)

        response = client.get(f'/v1/magic-links/get-form?token={jwt_token}')

        assert response.status_code == 404
        assert response.get_json()['error'] == 'no_task'

    @responses.activate
    def test_submit_form_success(self, client, app):
        config = app.config
        # 1. Setup mock JWT
        secret = config['JWT_SECRET_KEY']
        jwt_token = jwt.encode({'sub': 'test@example.com', 'processInstanceId': 'p1'}, secret, algorithm='HS256')

        # Populate in-memory token store for test
        from formsflow_custom_services.magic_link.service import _token_store
        from formsflow_custom_services.magic_link.utils import hash_token
        _token_store[hash_token(jwt_token)] = {
            'email': 'test@example.com',
            'process_instance_id': 'p1',
            'used': False
        }

        # 2. Mock External APIs
        responses.add(responses.POST, config['KEYCLOAK_TOKEN_URL'],
                      json={'access_token': 'kc-token-123'}, status=200)

        responses.add(responses.GET, f"{config['BPM_API_URL']}/engine-rest-ext/v1/task/t1/variables",
                      json={
                          'formUrl': {'value': 'http://formio/form/f1/submission/507f1f77bcf86cd799439012'},
                          'token': {'value': jwt_token, 'type': 'String'}
                      },
                      status=200)

        responses.add(
            responses.POST,
            f"{config['FORMIO_DEFAULT_PROJECT_URL']}/user/login",
            json={'status': 'ok'},
            headers={'x-jwt-token': 'formio-jwt-token-123'},
            status=200,
        )

        responses.add(responses.PUT, f"{config['FORMIO_DEFAULT_PROJECT_URL']}/form/f1/submission/507f1f77bcf86cd799439012",
                      json={'status': 'updated'}, status=200)

        responses.add(responses.POST, f"{config['BPM_API_URL']}/engine-rest-ext/process-instance/p1/variables",
                      status=204)

        responses.add(responses.POST, f"{config['BPM_API_URL']}/engine-rest-ext/task/t1/submit-form",
                      status=204)

        # 3. Call Endpoint
        response = client.post('/v1/magic-links/submit-form', json={
            'token': jwt_token,
            'data': {'field1': 'value1'},
            'taskId': 't1',
            'formId': 'f1'
        })

        assert response.status_code == 200
        assert response.get_json()['message'] == 'Success'
