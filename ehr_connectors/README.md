# EHR Connector Service

A secure, server-side bridge between **FormsFlow.ai** and **Electronic Health Record (EHR)** systems (e.g., Epic). This service enables BPMN workflows to securely communicate form statuses and data back to the EHR using the SMART on FHIR protocol.

## Purpose
Previously, sending "Approved" status back to the EHR was handled by the frontend, which posed security risks and lacked reliability for automated workflows. This service moves that logic to a secure Python FastAPI backend that can be called directly by **Camunda Service Tasks**.

## Features
- **Secure Communication**: Implements **SMART Backend Services (OAuth2 Private Key JWT)** authentication for server-to-server FHIR API access.
- **FHIR Integration**: Implements `DocumentReference` resource submission to Epic.
- **JWKS Support**: Built-in tools to generate RSA key pairs and serve a Public JWK Set (JWKS) endpoint.
- **BPMN Ready**: Designed to be called via Camunda's `http-connector`.
- **Extensible**: Built as a generic bridge that can be expanded to support more FHIR resources (Observations, Appointments, etc.) in the future.

## Getting Started

### Prerequisites
- Python 3.9+
- Client ID from your EHR provider (e.g., Epic App Orchard) registered for "Backend Services" or "System" access.

### Installation
1. Navigate to the service directory:
   ```bash
   cd ehr_connectors
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Configuration
1. Create a `.env` file in the `ehr_connectors` directory based on `.env.example`.
2. Generate your secure keys (see [Authentication](#authentication-jwks) below).

## Authentication (JWKS)
Epic and other SMART-on-FHIR providers require **Private Key JWT** authentication for backend services. You must generate an RSA key pair and provide the public key to Epic.

### 1. Generate Keys
Run the utility script to generate an RSA-384 key pair:
```bash
python generate_keys.py
```
This will:
- Create `private_key.pem` (your secret key).
- Create `jwks.json` (your public key set).
- Print the `EPIC_KID` and `EPIC_PRIVATE_KEY` values for your `.env` file.

### 2. Host the JWKS Endpoint
Epic needs to fetch your public key. You can host this locally for development using the included server:
```bash
python jwks_server.py
```
The server will be available at `http://localhost:8003/.well-known/jwks.json`.
> [!TIP]
> Use **ngrok** to expose this URL as HTTPS if the EHR portal requires a public URL: `ngrok http 8003`.

### 3. Register with EHR
Copy the contents of `jwks.json` or the public URL of your JWKS endpoint and provide it to the Epic on FHIR portal under your application settings.

## Running the Service
Start the main connector service:
```bash
python -m src.main
```
The service will be available at `http://localhost:8002`. View API documentation at `http://localhost:8002/docs`.

## End-to-End Workflow

### 1. Form Submission
A user launches a form from within the EHR (SMART on FHIR launch). The form is pre-filled with patient context.

### 2. Approval Workflow
Upon form submission, a Camunda process is triggered. An "Approver" reviews the submission.

### 3. Service Task Execution
Once approved, the BPMN process reaches a **Service Task** configured to call this connector.

**Service Task Configuration:**
- **Connector ID**: `http-connector`
- **URL**: `http://<ehr-connector-host>:8002/epic/approve`
- **Method**: `POST`
- **Payload**:
  ```json
  {
    "patientId": "${patientId}",
    "consentText": "Patient has approved the consent form.",
    "approvedAt": "${approvedAt}"
  }
  ```

### 4. EHR Update
The EHR Connector signs a JWT using your private key, requests a secure token from Epic, and POSTs a `DocumentReference` to the patient's record.

## Development and Testing
Run unit tests with pytest:
```bash
pytest test_connector.py
```

## Security
- **Private Key JWT**: Uses industry-standard asymmetric signing for token requests.
- **Server-Side**: OAuth secrets and private keys are never exposed to the browser.
- **Scoped Access**: Uses specific FHIR scopes (e.g., `system/DocumentReference.c`) to limit permissions.
