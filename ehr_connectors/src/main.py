from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from src.services.epic_service import EpicService
from src.services.launch_service import LaunchService, LaunchExchangeError
from src.config import get_settings
from pydantic import BaseModel
from typing import Optional, List, Union

import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="EHR Connector API")

# /epic/launch/exchange (and the FHIR viewer's other /epic/* routes) are
# called directly from the browser (keycloakHandoff.js), a different origin
# than this API - without CORS headers the browser silently blocks the
# request client-side ("TypeError: Failed to fetch"), before it ever shows
# up as a meaningful error in ehr_connectors' own logs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    body = await request.body()
    logger.error(f"Request validation failed: {exc.errors()} | Body: {body.decode(errors='ignore')}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": body.decode(errors='ignore')}
    )

epic_service = EpicService()
launch_service = LaunchService()

class LaunchExchangeRequest(BaseModel):
    id_token: str
    access_token: str
    iss: str
    patient_id: str

class ApprovalRequest(BaseModel):
    patientId: str
    consentText: str
    surrogateKey: Optional[str] = None
    approvedAt: Optional[str] = None

class PatientCreateRequest(BaseModel):
    fhirPatient: dict
    reviewerComments: Optional[str] = None
    notes: Optional[str] = None
    applicationId: Optional[Union[str, int]] = None

class DocumentReferenceRequest(BaseModel):
    patientId: str
    applicationId: Optional[Union[str, int]] = None
    surrogateKey: Optional[str] = None
    documentText: str
    documentTitle: str
    documentDate: Optional[str] = None

class ObservationItem(BaseModel):
    code: str
    display: Optional[str] = None
    value: float

class ObservationRequest(BaseModel):
    patientId: str
    applicationId: Optional[Union[str, int]] = None
    observations: List[ObservationItem]

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/epic/launch/exchange")
async def epic_launch_exchange(request: LaunchExchangeRequest):
    """
    Verify an Epic-issued id_token from the interactive patient/provider
    EHR-launch flow, and mint a short-lived internal assertion that
    Keycloak's EpicLaunchAssertionAuthenticator can independently verify.

    This is what lets an EHR-launched patient end up with a real formsflow
    session without ever seeing a Keycloak login screen or holding a
    password - every step here is a cryptographic signature check, either
    Epic's (the id_token) or ours (the assertion this returns).
    """
    try:
        assertion = await launch_service.exchange(
            id_token=request.id_token,
            access_token=request.access_token,
            iss=request.iss,
            patient_id=request.patient_id,
        )
        return {"assertion": assertion}
    except LaunchExchangeError as e:
        logger.warning(f"Launch exchange rejected: {e}")
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error during launch exchange: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Launch exchange failed")

@app.post("/epic/approve")
async def approve_to_epic(request: ApprovalRequest):
    """
    Endpoint to be called by Service Task to send approval status to Epic.
    """
    logger.info(f"Received approval request for patient: {request.patientId}")
    try:
        result = await epic_service.send_approval_status(
            patient_id=request.patientId,
            consent_text=request.consentText,
            surrogate_key=request.surrogateKey,
            approved_at=request.approvedAt
        )
        logger.info(f"Successfully sent approval status to Epic for patient: {request.patientId}")
        return {"ok": True, "result": result}
    except Exception as e:
        logger.error(f"Error in approve_to_epic for patient {request.patientId}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send status to Epic: {str(e)}")

@app.post("/epic/patient-create")
async def create_patient_endpoint(request: PatientCreateRequest):
    """
    Endpoint to be called by Service Task to create a patient in Epic.
    """
    logger.info(f"Received patient creation request for Application: {request.applicationId}")
    try:
        result = await epic_service.create_patient(
            fhir_patient=request.fhirPatient
        )
        logger.info(f"Successfully created patient in Epic. Application: {request.applicationId}")
        return result
    except Exception as e:
        logger.error(f"Error in create_patient_endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create patient: {str(e)}")

@app.post("/epic/documentreference-create")
async def create_document_reference_endpoint(request: DocumentReferenceRequest):
    """
    Endpoint to be called by a Service Task to write a general
    DocumentReference to Epic (e.g. a screening summary), independent of
    the consent-specific /epic/approve endpoint.
    """
    logger.info(f"Received DocumentReference creation request for patient: {request.patientId}")
    try:
        result = await epic_service.create_document_reference(
            patient_id=request.patientId,
            document_text=request.documentText,
            document_title=request.documentTitle,
            surrogate_key=request.surrogateKey,
            document_date=request.documentDate,
        )
        logger.info(f"Successfully created DocumentReference in Epic for patient: {request.patientId}")
        return {"ok": True, "result": result}
    except Exception as e:
        logger.error(f"Error in create_document_reference_endpoint for patient {request.patientId}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create DocumentReference: {str(e)}")

@app.post("/epic/observation-create")
async def create_observation_endpoint(request: ObservationRequest):
    """
    Endpoint to be called by a Service Task to write one or more
    Observation resources to Epic (e.g. PHQ-9/GAD-7 total scores).
    """
    logger.info(f"Received Observation creation request for patient: {request.patientId}")
    try:
        result = await epic_service.create_observation(
            patient_id=request.patientId,
            observations=[obs.dict() for obs in request.observations],
        )
        logger.info(f"Successfully created {len(request.observations)} Observation(s) in Epic for patient: {request.patientId}")
        return {"ok": True, "result": result}
    except Exception as e:
        logger.error(f"Error in create_observation_endpoint for patient {request.patientId}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create Observation: {str(e)}")

@app.get("/epic/documents")
async def search_documents_endpoint(patientId: str):
    """
    Search DocumentReferences for a patient.
    """
    try:
        result = await epic_service.search_documents(patient_id=patientId)
        return result
    except Exception as e:
        logger.error(f"Error in search_documents for patient {patientId}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to search documents in Epic: {str(e)}")

@app.get("/epic/binary/{binary_id}")
async def get_binary_endpoint(binary_id: str):
    """
    Fetch a Binary file and return it.
    """
    try:
        content = await epic_service.get_binary(binary_id=binary_id)
        return Response(content=content, media_type="application/octet-stream")
    except Exception as e:
        logger.error(f"Error in get_binary for id {binary_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch Binary from Epic: {str(e)}")

@app.get("/epic/patient/{patient_id}")
async def get_patient_endpoint(patient_id: str):
    try:
        result = await epic_service.get_patient(patient_id=patient_id)
        return result
    except Exception as e:
        logger.error(f"Error in get_patient for patient {patient_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch Patient from Epic: {str(e)}")

@app.get("/epic/encounter/{encounter_id}")
async def get_encounter_endpoint(encounter_id: str):
    try:
        result = await epic_service.get_encounter(encounter_id=encounter_id)
        return result
    except Exception as e:
        logger.error(f"Error in get_encounter for encounter {encounter_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch Encounter from Epic: {str(e)}")

@app.get("/epic/documentref/{docref_id}")
async def get_documentref_endpoint(docref_id: str):
    try:
        result = await epic_service.get_documentref(docref_id=docref_id)
        return result
    except Exception as e:
        logger.error(f"Error in get_documentref for docref {docref_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch DocumentReference from Epic: {str(e)}")

@app.get("/epic/observation/{observation_id}")
async def get_observation_endpoint(observation_id: str):
    try:
        result = await epic_service.get_observation(observation_id=observation_id)
        return result
    except Exception as e:
        logger.error(f"Error in get_observation for observation {observation_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch Observation from Epic: {str(e)}")

@app.get("/epic/encounters")
async def search_encounters_endpoint(patientId: str):
    try:
        result = await epic_service.search_encounters(patient_id=patientId)
        return result
    except Exception as e:
        logger.error(f"Error in search_encounters for patient {patientId}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to search encounters in Epic: {str(e)}")

@app.get("/epic/observations")
async def search_observations_endpoint(patientId: str):
    """
    Search for Observation resources (e.g. PHQ-9/GAD-7 scores) for a patient.
    """
    try:
        result = await epic_service.search_observations(patient_id=patientId)
        return result
    except Exception as e:
        logger.error(f"Error in search_observations for patient {patientId}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to search observations in Epic: {str(e)}")

# HTML Fallbacks to serve SPA client routing
from fastapi.responses import HTMLResponse

@app.get("/patient", response_class=HTMLResponse)
@app.get("/patient/{path:path}", response_class=HTMLResponse)
@app.get("/documentref", response_class=HTMLResponse)
@app.get("/documentref/{path:path}", response_class=HTMLResponse)
@app.get("/encounter", response_class=HTMLResponse)
@app.get("/encounter/{path:path}", response_class=HTMLResponse)
@app.get("/observation", response_class=HTMLResponse)
@app.get("/observation/{path:path}", response_class=HTMLResponse)
async def serve_spa_index():
    import os
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

# Mount static files at the root
app.mount("/", StaticFiles(directory="src/static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
