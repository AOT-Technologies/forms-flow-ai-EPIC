import httpx
import base64
import logging
import uuid
from datetime import datetime, timezone
from src.config import get_settings

import jwt  # PyJWT

logger = logging.getLogger(__name__)


class EpicService:
    def __init__(self):
        self.settings = get_settings()
        self.client = httpx.AsyncClient(
            base_url=self.settings.EPIC_FHIR_BASE_URL,
            timeout=self.settings.EPIC_TIMEOUT,
        )

    def _generate_client_jwt(self) -> str:
        """
        Generate a signed JWT for Epic's private_key_jwt client authentication.

        Per Epic's SMART Backend Services (Backend OAuth 2.0) spec:
          - alg: RS384
          - Header:  { alg, typ, kid }
          - Payload: { iss, sub, aud, jti, iat, nbf, exp }

        https://fhir.epic.com/Documentation?docId=oauth2tutorial&section=cloud-based-app
        """
        now = int(datetime.now(tz=timezone.utc).timestamp())
        payload = {
            "iss": self.settings.EPIC_CLIENT_ID,
            "sub": self.settings.EPIC_CLIENT_ID,
            "aud": self.settings.EPIC_TOKEN_URL,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "nbf": now,
            "exp": now + 300,  # 5 minutes; Epic max is 5 min
        }
        headers = {
            "alg": "RS384",
            "typ": "JWT",
            "kid": self.settings.EPIC_KID,
        }
        import codecs
        private_key_pem = codecs.decode(
            self.settings.EPIC_PRIVATE_KEY, "unicode_escape"
        )

        logger.debug(f"Creating JWT for client_id={self.settings.EPIC_CLIENT_ID}, kid={self.settings.EPIC_KID}")

        token = jwt.encode(
            payload,
            private_key_pem,
            algorithm="RS384",
            headers=headers,
        )
        return token

    async def get_access_token(self) -> dict:
        """
        Request an access token from Epic using private_key_jwt authentication
        (SMART Backend Services / Backend OAuth 2.0 flow).
        """
        client_assertion = self._generate_client_jwt()

        payload = {
            "grant_type": "client_credentials",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": client_assertion,
            # Requesting necessary scopes including Search (.s) and restricted category
            "scope": "system/DocumentReference.c system/DocumentReference.read system/Binary.read system/Patient.read system/Encounter.read",
        }

        logger.info(f"Requesting access token from {self.settings.EPIC_TOKEN_URL} (private_key_jwt)")

        async with httpx.AsyncClient(timeout=self.settings.EPIC_TIMEOUT) as client:
            try:
                response = await client.post(
                    self.settings.EPIC_TOKEN_URL,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if response.status_code != 200:
                    logger.error(
                        f"Failed to get access token: HTTP {response.status_code} — {response.text}"
                    )
                response.raise_for_status()
                data = response.json()
                logger.info(
                    f"Successfully obtained access token (expires_in={data.get('expires_in')}s, "
                    f"scope={data.get('scope')})"
                )
                return data
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"HTTP error during token request: {e.response.status_code} — {e.response.text}"
                )
                raise
            except Exception as e:
                logger.error(f"Unexpected error during token request: {str(e)}")
                raise

    async def get_latest_encounter(self, patient_id: str, token: str) -> str:
        """Fetch the most recent encounter ID."""
        logger.info(f"Fetching an Encounter for patient {patient_id}...")
        try:
            # FIX: Removed the trailing slash before the '?'
            # Epic R4 is strict: /Encounter?patient=... NOT /Encounter/?patient=...
            url = f"/Encounter?patient={patient_id}"

            response = await self.client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/fhir+json",
                },
            )
            response.raise_for_status()
            data = response.json()

            # Epic returns a Bundle. Extract the first Encounter ID.
            if data.get("resourceType") == "Bundle" and "entry" in data:
                for entry in data.get("entry", []):
                    res = entry.get("resource", {})
                    if res.get("resourceType") == "Encounter":
                        encounter_id = res.get("id")
                        logger.info(f"Successfully found Encounter: {encounter_id}")
                        return encounter_id

            logger.warning(f"Could not find any encounters for patient {patient_id}.")
            return None
        except Exception as e:
            logger.error(f"Error fetching encounter: {str(e)}")
            return None

    async def send_approval_status(
        self, patient_id: str, consent_text: str, surrogate_key: str = None, approved_at: str = None
    ):
        """
        Send a general DocumentReference (Patient Media / Consent) to Epic.
        No Encounter context needed with explicit scope authorization.
        """
        if not approved_at:
            approved_at = datetime.now(tz=timezone.utc).isoformat()

        token_data = await self.get_access_token()
        token = token_data["access_token"]

        # Fetch latest encounter ID for the patient
        encounter_id = await self.get_latest_encounter(patient_id, token)
        if not encounter_id:
            logger.warning(f"No encounter found for patient {patient_id}. Epic may reject this.")

        # Build the exact payload for a general patient consent
        document_reference = {
            "resourceType": "DocumentReference",
            "status": "current",
            "masterIdentifier": {
                "system": "http://formsflow.ai/surrogate-key",
                "value": surrogate_key
            } if surrogate_key else None,
            "identifier": [
                {
                    "system": "http://formsflow.ai/surrogate-key",
                    "value": surrogate_key
                }
            ] if surrogate_key else [],
            "type": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "11506-3",
                        "display": "Progress note",
                    }
                ],
                "text": "Patient Consent Form",
            },
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category",
                            "code": "clinical-note",
                            "display": "Clinical Note",
                        }
                    ]
                }
            ],
            "subject": {"reference": f"Patient/{patient_id}"},
            "author": [
                {
                    "reference": "Practitioner/eSo9eP0mV3eFB3pTR6e53jQ3",
                    "display": "Ambulatory, James",
                }
            ],
            "date": approved_at,
            "content": [
                {
                    "attachment": {
                        "contentType": "text/plain",
                        "data": base64.b64encode(
                            (consent_text + (f" The surrogate Key is {surrogate_key}" if surrogate_key else "")).encode()
                        ).decode(),
                        "title": f"Patient Consent Form - Ref: {surrogate_key}" if surrogate_key else "Patient Consent Form",
                    }
                }
            ],
            "context": {
                "encounter": [{"reference": f"Encounter/{encounter_id}"}]
            } if encounter_id else {},
        }

        import json
        logger.info(f"Sending DocumentReference to Epic: {json.dumps(document_reference, indent=2)}")
        
        try:
            response = await self.client.post(
                "/DocumentReference/",
                json=document_reference,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/fhir+json",
                    "Accept": "application/fhir+json",
                },
            )

            if response.status_code != 201:
                logger.error(f"Epic rejected the payload: {response.text}")

            response.raise_for_status()
            logger.info("Successfully posted Approval to Epic.")

            try:
                if response.headers.get("content-type", "").startswith("application/json"):
                    return response.json()
                else:
                    return {
                        "status": "success",
                        "message": "DocumentReference created in Epic",
                        "status_code": response.status_code,
                        "id": response.headers.get("Location", "").split("/")[-1],
                    }
            except Exception:
                return {
                    "status": "success",
                    "message": "DocumentReference created (no JSON body returned)",
                    "status_code": response.status_code,
                }

        except httpx.HTTPStatusError as e:
            # This will show you exactly why Epic rejected the Encounter or Patient
            logger.error(f"HTTP Error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error sending DocumentReference: {str(e)}")
            raise

    async def search_documents(self, patient_id: str):
        """
        Search for DocumentReferences for a patient.
        """
        token_data = await self.get_access_token()
        token = token_data["access_token"]
        
        url = f"/DocumentReference?patient={patient_id}"
        logger.info(f"Searching DocumentReferences for patient {patient_id}...")
        
        try:
            response = await self.client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/fhir+json",
                },
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP Error searching documents: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error searching documents: {str(e)}")
            raise

    async def get_binary(self, binary_id: str):
        """
        Fetch a Binary file from Epic.
        """
        token_data = await self.get_access_token()
        token = token_data["access_token"]
        
        url = f"/Binary/{binary_id}"
        logger.info(f"Fetching Binary {binary_id}...")
        
        try:
            response = await self.client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/fhir+json",
                },
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP Error fetching binary: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching binary: {str(e)}")
            raise
