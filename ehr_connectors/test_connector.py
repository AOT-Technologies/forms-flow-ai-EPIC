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

@respx.mock
@pytest.mark.asyncio
async def test_patient_create_success():
    settings = get_settings()
    
    # Mock token request
    token_route = respx.post(settings.EPIC_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fake_token"}))
    
    # Mock Patient create endpoint
    def match_patient_create(request):
        import json
        payload = json.loads(request.content)
        assert payload["resourceType"] == "Patient"
        assert payload["name"][0]["family"] == "Doe"
        assert payload["name"][0]["given"][0] == "John"
        assert payload["identifier"][0]["value"] == "123-45-6789"  # SSN
        return httpx.Response(201, json={"id": "new_patient_id", "resourceType": "Patient", "identifier": [{"type": {"coding": [{"code": "MR"}]}, "value": "MRN-999"}]})

    patient_route = respx.post(f"{settings.EPIC_FHIR_BASE_URL}/Patient").mock(side_effect=match_patient_create)
    
    response = client.post(
        "/epic/patient-create",
        json={
            "fhirPatient": {
                "resourceType": "Patient",
                "name": [{"use": "official", "family": "Doe", "given": ["John"]}],
                "identifier": [{"system": "http://hl7.org/fhir/sid/us-ssn", "value": "123-45-6789"}]
            },
            "applicationId": "app_123"
        }
    )
    
    assert response.status_code == 200
    assert response.json()["id"] == "new_patient_id"
    assert response.json()["identifier"][0]["value"] == "MRN-999"
    assert token_route.called
    assert patient_route.called

@respx.mock
@pytest.mark.asyncio
async def test_create_document_reference_success():
    settings = get_settings()
    respx.post(settings.EPIC_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fake_token"}))
    respx.get(f"{settings.EPIC_FHIR_BASE_URL}/Encounter?patient=test_patient").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle", "entry": [{"resource": {"id": "fake_encounter", "resourceType": "Encounter"}}]})
    )
    
    def match_doc_create(request):
        import json
        payload = json.loads(request.content)
        assert payload["resourceType"] == "DocumentReference"
        assert payload["type"]["text"] == "Screening Summary"
        assert payload["content"][0]["attachment"]["title"] == "Screening Summary - Ref: KEY-123"
        return httpx.Response(201, json={"id": "doc_123", "resourceType": "DocumentReference"})

    doc_route = respx.post(f"{settings.EPIC_FHIR_BASE_URL}/DocumentReference/").mock(side_effect=match_doc_create)
    
    response = client.post(
        "/epic/documentreference-create",
        json={
            "patientId": "test_patient",
            "documentText": "Patient has mild anxiety",
            "documentTitle": "Screening Summary",
            "surrogateKey": "KEY-123"
        }
    )
    
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["result"]["id"] == "doc_123"
    assert doc_route.called

@respx.mock
@pytest.mark.asyncio
async def test_create_observation_success():
    settings = get_settings()
    respx.post(settings.EPIC_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fake_token"}))
    
    def match_obs_create(request):
        import json
        payload = json.loads(request.content)
        assert payload["resourceType"] == "Observation"
        assert payload["valueQuantity"]["value"] == 15
        assert payload["code"]["coding"][0]["code"] == "12345-6"
        return httpx.Response(201, json={"id": "obs_123", "resourceType": "Observation"})

    obs_route = respx.post(f"{settings.EPIC_FHIR_BASE_URL}/Observation").mock(side_effect=match_obs_create)
    
    response = client.post(
        "/epic/observation-create",
        json={
            "patientId": "test_patient",
            "observations": [
                {"code": "12345-6", "display": "PHQ-9 Score", "value": 15}
            ]
        }
    )
    
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["result"]["observations"][0]["id"] == "obs_123"
    assert obs_route.called

@respx.mock
@pytest.mark.asyncio
async def test_search_documents_success():
    settings = get_settings()
    respx.post(settings.EPIC_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fake_token"}))
    respx.get(f"{settings.EPIC_FHIR_BASE_URL}/DocumentReference?patient=test_patient").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle", "entry": [{"resource": {"id": "doc_1", "resourceType": "DocumentReference"}}]})
    )
    
    response = client.get("/epic/documents?patientId=test_patient")
    assert response.status_code == 200
    assert response.json()["resourceType"] == "Bundle"
    assert response.json()["entry"][0]["resource"]["id"] == "doc_1"

@respx.mock
@pytest.mark.asyncio
async def test_get_binary_success():
    settings = get_settings()
    respx.post(settings.EPIC_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fake_token"}))
    respx.get(f"{settings.EPIC_FHIR_BASE_URL}/Binary/bin_123").mock(
        return_value=httpx.Response(200, content=b"raw binary content")
    )
    
    response = client.get("/epic/binary/bin_123")
    assert response.status_code == 200
    assert response.content == b"raw binary content"

@respx.mock
@pytest.mark.asyncio
async def test_get_patient_success():
    settings = get_settings()
    respx.post(settings.EPIC_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fake_token"}))
    respx.get(f"{settings.EPIC_FHIR_BASE_URL}/Patient/pat_123").mock(
        return_value=httpx.Response(200, json={"id": "pat_123", "resourceType": "Patient"})
    )
    
    response = client.get("/epic/patient/pat_123")
    assert response.status_code == 200
    assert response.json()["id"] == "pat_123"

@respx.mock
@pytest.mark.asyncio
async def test_get_encounter_success():
    settings = get_settings()
    respx.post(settings.EPIC_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fake_token"}))
    respx.get(f"{settings.EPIC_FHIR_BASE_URL}/Encounter/enc_123").mock(
        return_value=httpx.Response(200, json={"id": "enc_123", "resourceType": "Encounter"})
    )
    
    response = client.get("/epic/encounter/enc_123")
    assert response.status_code == 200
    assert response.json()["id"] == "enc_123"

@respx.mock
@pytest.mark.asyncio
async def test_get_documentref_success():
    settings = get_settings()
    respx.post(settings.EPIC_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fake_token"}))
    respx.get(f"{settings.EPIC_FHIR_BASE_URL}/DocumentReference/doc_123").mock(
        return_value=httpx.Response(200, json={"id": "doc_123", "resourceType": "DocumentReference"})
    )
    
    response = client.get("/epic/documentref/doc_123")
    assert response.status_code == 200
    assert response.json()["id"] == "doc_123"

@respx.mock
@pytest.mark.asyncio
async def test_get_observation_success():
    settings = get_settings()
    respx.post(settings.EPIC_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fake_token"}))
    respx.get(f"{settings.EPIC_FHIR_BASE_URL}/Observation/obs_123").mock(
        return_value=httpx.Response(200, json={"id": "obs_123", "resourceType": "Observation"})
    )
    
    response = client.get("/epic/observation/obs_123")
    assert response.status_code == 200
    assert response.json()["id"] == "obs_123"

@respx.mock
@pytest.mark.asyncio
async def test_search_encounters_success():
    settings = get_settings()
    respx.post(settings.EPIC_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fake_token"}))
    respx.get(f"{settings.EPIC_FHIR_BASE_URL}/Encounter?patient=test_patient").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle", "entry": [{"resource": {"id": "enc_1", "resourceType": "Encounter"}}]})
    )
    
    response = client.get("/epic/encounters?patientId=test_patient")
    assert response.status_code == 200
    assert response.json()["resourceType"] == "Bundle"
    assert response.json()["entry"][0]["resource"]["id"] == "enc_1"

@respx.mock
@pytest.mark.asyncio
async def test_search_observations_success():
    settings = get_settings()
    respx.post(settings.EPIC_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fake_token"}))
    respx.get(f"{settings.EPIC_FHIR_BASE_URL}/Observation?patient=test_patient").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle", "entry": [{"resource": {"id": "obs_1", "resourceType": "Observation"}}]})
    )
    
    response = client.get("/epic/observations?patientId=test_patient")
    assert response.status_code == 200
    assert response.json()["resourceType"] == "Bundle"
    assert response.json()["entry"][0]["resource"]["id"] == "obs_1"
