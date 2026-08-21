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

    async def create_document_reference(
        self,
        patient_id: str,
        document_text: str,
        document_title: str,
        loinc_code: str = "11506-3",
        loinc_display: str = "Progress note",
        surrogate_key: str = None,
        document_date: str = None,
    ):
        """
        Build and POST a general DocumentReference to Epic.

        Generalized from the original consent-approval document builder so
        it can be reused by any write-back that needs to record free-text
        content against a patient (e.g. consent approvals, screening
        summaries), not just consent.
        """
        if not document_date:
            document_date = datetime.now(tz=timezone.utc).isoformat()

        token_data = await self.get_access_token()
        token = token_data["access_token"]

        # Fetch latest encounter ID for the patient
        encounter_id = await self.get_latest_encounter(patient_id, token)
        if not encounter_id:
            logger.warning(f"No encounter found for patient {patient_id}. Epic may reject this.")

        # Build the DocumentReference payload
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
                        "code": loinc_code,
                        "display": loinc_display,
                    }
                ],
                "text": document_title,
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
            "date": document_date,
            "content": [
                {
                    "attachment": {
                        "contentType": "text/plain",
                        "data": base64.b64encode(
                            (document_text + (f" The surrogate Key is {surrogate_key}" if surrogate_key else "")).encode()
                        ).decode(),
                        "title": f"{document_title} - Ref: {surrogate_key}" if surrogate_key else document_title,
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
            logger.info("Successfully posted DocumentReference to Epic.")

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

    async def send_approval_status(
        self, patient_id: str, consent_text: str, surrogate_key: str = None, approved_at: str = None
    ):
        """
        Send a general DocumentReference (Patient Media / Consent) to Epic.
        No Encounter context needed with explicit scope authorization.
        """
        return await self.create_document_reference(
            patient_id=patient_id,
            document_text=consent_text,
            document_title="Patient Consent Form",
            surrogate_key=surrogate_key,
            document_date=approved_at,
        )

    async def create_observation(
        self, patient_id: str, observations: list, effective_date: str = None
    ):
        """
        Build and POST one FHIR Observation resource per entry in
        `observations` to Epic. Each entry is a dict with `code` (LOINC
        code), `display` (text), and `value` (numeric). Posts one
        Observation per entry rather than a transaction Bundle, mirroring
        create_patient's single-resource-per-call shape.
        """
        if not effective_date:
            effective_date = datetime.now(tz=timezone.utc).isoformat()

        token_data = await self.get_access_token()
        token = token_data["access_token"]

        results = []
        for obs in observations:
            observation_resource = {
                "resourceType": "Observation",
                "status": "final",
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": obs["code"],
                            "display": obs.get("display", ""),
                        }
                    ],
                    "text": obs.get("display", ""),
                },
                "subject": {"reference": f"Patient/{patient_id}"},
                "effectiveDateTime": effective_date,
                "valueQuantity": {
                    "value": obs["value"],
                },
            }

            logger.info(f"Sending Observation to Epic: {observation_resource}")

            try:
                response = await self.client.post(
                    "/Observation",
                    json=observation_resource,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/fhir+json",
                        "Accept": "application/fhir+json",
                    },
                )

                if response.status_code != 201:
                    logger.error(f"Epic rejected the Observation payload: {response.text}")

                response.raise_for_status()
                logger.info(f"Successfully posted Observation ({obs['code']}) to Epic.")

                try:
                    if response.headers.get("content-type", "").startswith("application/json"):
                        results.append(response.json())
                    else:
                        results.append({
                            "status": "success",
                            "message": "Observation created in Epic",
                            "status_code": response.status_code,
                            "id": response.headers.get("Location", "").split("/")[-1],
                        })
                except Exception:
                    results.append({
                        "status": "success",
                        "message": "Observation created (no JSON body returned)",
                        "status_code": response.status_code,
                    })

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP Error creating observation: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Unexpected error creating observation: {str(e)}")
                raise

        return {"observations": results}

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

    async def get_patient(self, patient_id: str):
        """
        Fetch a single Patient from Epic.
        """
        token_data = await self.get_access_token()
        token = token_data["access_token"]
        
        url = f"/Patient/{patient_id}"
        logger.info(f"Fetching Patient {patient_id}...")
        
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
            logger.error(f"HTTP Error fetching patient: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching patient: {str(e)}")
            raise

    async def get_encounter(self, encounter_id: str):
        """
        Fetch a single Encounter from Epic.
        """
        token_data = await self.get_access_token()
        token = token_data["access_token"]
        
        url = f"/Encounter/{encounter_id}"
        logger.info(f"Fetching Encounter {encounter_id}...")
        
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
            logger.error(f"HTTP Error fetching encounter: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching encounter: {str(e)}")
            raise

    async def get_documentref(self, docref_id: str):
        """
        Fetch a single DocumentReference from Epic.
        """
        token_data = await self.get_access_token()
        token = token_data["access_token"]
        
        url = f"/DocumentReference/{docref_id}"
        logger.info(f"Fetching DocumentReference {docref_id}...")
        
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
            logger.error(f"HTTP Error fetching document reference: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching document reference: {str(e)}")
            raise

    async def get_observation(self, observation_id: str):
        """
        Fetch a single Observation resource by ID from Epic.
        """
        token_data = await self.get_access_token()
        token = token_data["access_token"]

        url = f"/Observation/{observation_id}"
        logger.info(f"Fetching Observation {observation_id} from Epic...")

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
            logger.error(f"HTTP Error fetching observation {observation_id}: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching observation {observation_id}: {str(e)}")
            raise

    async def search_encounters(self, patient_id: str):
        """
        Search for Encounter resources for a patient.
        """
        token_data = await self.get_access_token()
        token = token_data["access_token"]
        
        url = f"/Encounter?patient={patient_id}"
        logger.info(f"Searching Encounters for patient {patient_id}...")
        
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
            logger.error(f"HTTP Error searching encounters: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error searching encounters: {str(e)}")
            raise

    async def search_observations(self, patient_id: str):
        """
        Search for Observation resources for a patient.
        """
        token_data = await self.get_access_token()
        token = token_data["access_token"]

        url = f"/Observation?patient={patient_id}"
        logger.info(f"Searching Observations for patient {patient_id}...")

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
            logger.error(f"HTTP Error searching observations: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error searching observations: {str(e)}")
            raise

    async def create_patient(self, fhir_patient: dict):
        """
        Create a Patient resource in Epic.
        """
        token_data = await self.get_access_token()
        token = token_data["access_token"]
        
        logger.info(f"Creating Patient in Epic... {fhir_patient}")
        try:
            response = await self.client.post(
                "/Patient",
                json=fhir_patient,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/fhir+json",
                    "Accept": "application/fhir+json",
                },
            )
            
            if response.status_code != 201:
                logger.error(f"Epic rejected Patient creation payload: {response.text}")
            
            response.raise_for_status()
            logger.info(f"Successfully created Patient in Epic. Response: {response.json()}")
            
            try:
                content_type = response.headers.get("content-type", "").lower()
                if "json" in content_type:
                    return response.json()
                else:
                    # Parse Location header to get the ID if JSON is not returned
                    location = response.headers.get("Location", "")
                    patient_id = ""
                    if location:
                        parts = location.split("/")
                        if "_history" in parts:
                            idx = parts.index("_history")
                            patient_id = parts[idx - 1]
                        else:
                            patient_id = parts[-1]
                    return {
                        "status": "success",
                        "message": "Patient created in Epic",
                        "status_code": response.status_code,
                        "id": patient_id,
                    }
            except Exception:
                return {
                    "status": "success",
                    "message": "Patient created (no JSON body returned)",
                    "status_code": response.status_code,
                }
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP Error creating patient: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating patient: {str(e)}")
            raise
