from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from src.services.epic_service import EpicService
from src.config import get_settings
from pydantic import BaseModel
from typing import Optional

import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="EHR Connector API")
epic_service = EpicService()

class ApprovalRequest(BaseModel):
    patientId: str
    consentText: str
    surrogateKey: Optional[str] = None
    approvedAt: Optional[str] = None

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

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

# Mount static files at the root
app.mount("/", StaticFiles(directory="src/static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
