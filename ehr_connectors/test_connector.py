import pytest
import respx
import httpx
from fastapi.testclient import TestClient
from src.main import app
from src.config import get_settings

client = TestClient(app)

@respx.mock
@pytest.mark.asyncio
async def test_approve_to_epic_success():
    settings = get_settings()
    
    # Mock token request
    token_route = respx.post(settings.EPIC_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fake_token"}))
    
    # Mock Encounter search
    encounter_route = respx.get(
        f"{settings.EPIC_FHIR_BASE_URL}/Encounter?patient=test_patient"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "entry": [
                    {"resource": {"id": "fake_encounter", "resourceType": "Encounter"}}
                ],
            },
        )
    )

    # Mock DocumentReference request (with trailing slash)
    def match_doc_request(request):
        import json
        payload = json.loads(request.content)
        assert "context" in payload
        assert "encounter" in payload["context"]
        assert payload["context"]["encounter"][0]["reference"] == "Encounter/fake_encounter"
        assert payload["type"]["coding"][0]["code"] == "11506-3"
        assert payload["category"][0]["coding"][0]["code"] == "clinical-note"
        return httpx.Response(201, json={"id": "123", "resourceType": "DocumentReference"})

    doc_route = respx.post(f"{settings.EPIC_FHIR_BASE_URL}/DocumentReference/").mock(side_effect=match_doc_request)
    
    response = client.post(
        "/epic/approve",
        json={
            "patientId": "test_patient",
            "consentText": "test consent text",
            "approvedAt": "2024-10-22T10:00:00Z"
        }
    )
    
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["result"]["id"] == "123"
    assert token_route.called
    assert encounter_route.called
    assert doc_route.called

@respx.mock
@pytest.mark.asyncio
async def test_approve_to_epic_with_surrogate_key():
    settings = get_settings()
    
    # Mock token request
    respx.post(settings.EPIC_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fake_token"}))
    
    # Mock Encounter search
    respx.get(
        f"{settings.EPIC_FHIR_BASE_URL}/Encounter?patient=test_patient"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "entry": [
                    {"resource": {"id": "fake_encounter", "resourceType": "Encounter"}}
                ],
            },
        )
    )

    # Mock DocumentReference request and verify payload
    def match_payload(request):
        import json
        payload = json.loads(request.content)
        assert "masterIdentifier" in payload
        assert payload["masterIdentifier"]["value"] == "TEST-KEY-123"
        assert "identifier" in payload
        assert payload["identifier"][0]["value"] == "TEST-KEY-123"
        assert payload["identifier"][0]["system"] == "http://formsflow.ai/surrogate-key"
        assert "context" in payload
        assert "encounter" in payload["context"]
        assert payload["context"]["encounter"][0]["reference"] == "Encounter/fake_encounter"
        assert payload["type"]["coding"][0]["code"] == "11506-3"
        assert payload["category"][0]["coding"][0]["code"] == "clinical-note"
        assert payload["content"][0]["attachment"]["title"] == "Patient Consent Form - Ref: TEST-KEY-123"
        
        # Verify base64 data contains surrogate key
        import base64 as py_base64
        decoded_text = py_base64.b64decode(payload["content"][0]["attachment"]["data"]).decode()
        assert "test consent text" in decoded_text
        assert "The surrogate Key is TEST-KEY-123" in decoded_text
        
        return httpx.Response(201, json={"id": "456", "resourceType": "DocumentReference"})

    doc_route = respx.post(f"{settings.EPIC_FHIR_BASE_URL}/DocumentReference/").mock(side_effect=match_payload)
    
    response = client.post(
        "/epic/approve",
        json={
            "patientId": "test_patient",
            "consentText": "test consent text",
            "surrogateKey": "TEST-KEY-123",
            "approvedAt": "2024-10-22T10:00:00Z"
        }
    )
    
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["result"]["id"] == "456"
    assert doc_route.called

@pytest.mark.asyncio
async def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
