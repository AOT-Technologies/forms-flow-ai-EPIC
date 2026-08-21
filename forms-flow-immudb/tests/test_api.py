"""Tests for the API endpoints."""

import pytest
import json
from src.formsflow_immudb.app import create_app


@pytest.fixture
def app():
    """Create test application."""
    app = create_app('testing')
    app.config['IMMUDB_SECRET_KEY'] = 'test-secret-key-12345'
    yield app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


def test_health_check(client):
    """Test health check endpoint."""
    response = client.get('/health')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data['status'] == 'healthy'
    assert data['service'] == 'forms-flow-immudb'


def test_root_endpoint(client):
    """Test root endpoint."""
    response = client.get('/')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data['service'] == 'forms-flow-immudb'
    assert 'endpoints' in data


def test_log_audit_event_unauthorized(client):
    """Test audit log endpoint rejects requests without a valid token."""
    response = client.post('/api/v1/audit/log', json={})
    assert response.status_code == 401


def test_log_audit_event_missing_data(client):
    """Test audit log with missing data."""
    headers = {"X-Auth-Token": "test-secret-key-12345"}
    response = client.post('/api/v1/audit/log', json={}, headers=headers)
    assert response.status_code == 400
    
    data = json.loads(response.data)
    assert 'error' in data


def test_log_audit_event_valid(client):
    """Test audit log with valid data."""
    headers = {"X-Auth-Token": "test-secret-key-12345"}
    payload = {
        'event_name': 'test_event',
        'request_data': {'test': 'request'},
        'response_data': {'test': 'response'}
    }
    
    response = client.post('/api/v1/audit/log', json=payload, headers=headers)
    # Will succeed even with ImmuDB disabled in testing
    assert response.status_code in [200, 201]
