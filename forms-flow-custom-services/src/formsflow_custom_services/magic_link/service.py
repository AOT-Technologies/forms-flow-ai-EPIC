import os
import requests
import jwt
import threading
import time
from datetime import datetime, timedelta, timezone
from flask import current_app
from formsflow_custom_services.magic_link.utils import (
    generate_token, hash_token, build_magic_link, create_jwt,
    extract_form_id, extract_submission_id, get_kc_admin_token, get_formio_token
)

# Structure: { hashed_token: { "email": str, "process_instance_id": str, "iss": str, "aud": str, "expires_at": datetime, "used": bool } }
_token_store: dict = {}

# Simple in-memory blacklist for revoked JWTs (or magic link tokens)
_revocation_list: set = set()


def _get_expiry() -> datetime:
    minutes = current_app.config.get('MAGIC_LINK_EXPIRY_MINUTES', 15)
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def _expiry_minutes() -> int:
    return current_app.config.get('JWT_EXPIRY_MINUTES', 2880)  # Default to 48h


# ── Internal helpers ────────────────────────────────────────────────────────

def _set_task_variables_async(pid: str, variables: dict) -> None:
    """
    Sets task-level variables asynchronously in a background thread to avoid
    deadlocks with the active synchronous Camunda transaction.
    Retries up to 5 times if the task is not yet created.
    """
    app_instance = current_app._get_current_object()

    def run():
        with app_instance.app_context():
            # Wait a brief moment for the synchronous transaction calling us to complete and commit
            time.sleep(1.0)
            
            bpm_api = current_app.config.get('BPM_API_URL')
            kc_token = get_kc_admin_token()
            task_list_url = f"{bpm_api}/engine-rest-ext/v1/task?processInstanceId={pid}"
            
            max_retries = 20
            for attempt in range(max_retries):
                try:
                    current_app.logger.info(
                        f"[Attempt {attempt+1}/{max_retries}] Fetching active tasks for processInstanceId: {pid}"
                    )
                    task_res = requests.get(
                        task_list_url,
                        headers={"Authorization": f"Bearer {kc_token}"}
                    )
                    if not task_res.ok:
                        current_app.logger.warning(
                            f"Failed to fetch tasks (HTTP {task_res.status_code}): {task_res.text}. Retrying in 1s..."
                        )
                        time.sleep(1.0)
                        continue
                    
                    tasks = task_res.json()
                    if not tasks:
                        current_app.logger.warning(
                            f"No active tasks found yet for processInstanceId: {pid}. Retrying in 1s..."
                        )
                        time.sleep(1.0)
                        continue
                    
                    task_id = tasks[0].get('id')
                    current_app.logger.info(f"Found active task {task_id} for processInstanceId: {pid}")
                    
                    # Set the variables on the task
                    success = True
                    for name, val in variables.items():
                        var_url = f"{bpm_api}/engine-rest-ext/task/{task_id}/variables/{name}"
                        payload = {"value": val, "type": "String"}
                        
                        current_app.logger.info(f"Setting task variable '{name}' at {var_url}")
                        res = requests.put(
                            var_url,
                            json=payload,
                            headers={"Authorization": f"Bearer {kc_token}", "Content-Type": "application/json"}
                        )
                        if not res.ok:
                            current_app.logger.error(
                                f"Failed to set task variable '{name}' on task {task_id} (HTTP {res.status_code}): {res.text}"
                            )
                            success = False
                            break
                    
                    if success:
                        current_app.logger.info(f"Successfully set task variables in Camunda on attempt {attempt+1}")
                        return
                    
                    time.sleep(1.0)
                    
                except Exception as e:
                    current_app.logger.error(f"Error setting task variables on {pid}: {str(e)}")
                    time.sleep(1.0)
                    
            current_app.logger.error(f"Failed to set task variables after {max_retries} attempts.")

    # Start the thread and detach it
    threading.Thread(target=run, daemon=True).start()


def _delete_process_variable(pid: str, name: str) -> None:
    bpm_api = current_app.config.get('BPM_API_URL')
    kc_token = get_kc_admin_token()
    url = f"{bpm_api}/engine-rest-ext/process-instance/{pid}/variables"
    current_app.logger.info(f"Deleting process variable '{name}' for processInstanceId: {pid} at {url}")
    payload = {
        "deletions": [name]
    }
    res = requests.post(url, json=payload, headers={"Authorization": f"Bearer {kc_token}", "Content-Type": "application/json"})
    # 404 means variable or process instance is already gone — both are acceptable outcomes
    if not res.ok and res.status_code != 404:
        current_app.logger.warning(f"Failed to delete process variable '{name}' on {pid}: {res.status_code} {res.text}")


# ── Public service functions ────────────────────────────────────────────────

def request_magic_link(email: str, process_instance_id: str, iss: str = None, aud: str = None, token_expiry: int = None) -> dict:
    """
    Generate a magic link that contains a signed JWT directly.
    """
    expiry_minutes = token_expiry if token_expiry is not None else _expiry_minutes()
    current_app.logger.info(
        f"Generating magic link for email: {email}, processInstanceId: {process_instance_id}, "
        f"iss: {iss}, aud: {aud}, expiry: {expiry_minutes}m"
    )
    current_app.logger.info(
        f"Request Payload: {{'email': '{email}', 'processInstanceId': '{process_instance_id}', "
        f"'iss': '{iss}', 'aud': '{aud}'}}"
    )
    # _invalidate_tokens_for_email(email)

    payload = {
        'sub': email,
        'email': email,
        'processInstanceId': process_instance_id,
        'iss': iss or "surgical-portal-service",
        'aud': aud or "public-patient-intake"
    }
    jwt_token = create_jwt(payload, expiry_minutes=expiry_minutes)

    # Construct link with JWT as token
    magic_link = build_magic_link(jwt_token)

    # Store secure token in Camunda task variables programmatically (asynchronously to avoid transaction race conditions)
    _set_task_variables_async(process_instance_id, {
        "token": jwt_token
    })

    _token_store[hash_token(jwt_token)] = {
        'email': email,
        'process_instance_id': process_instance_id,
        'iss': payload['iss'],
        'aud': payload['aud'],
        'token_expiry': token_expiry,
        'expires_at': datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes),
        'used': False,
    }

    current_app.logger.info(f"Generated magic link: {magic_link}")
    return {
        'message': 'Magic link generated successfully.',
        'magic_link': magic_link,
        'token': jwt_token,
        'expires_in_minutes': expiry_minutes,
    }


def verify_magic_link(raw_token: str) -> tuple[dict, int]:
    """
    [DEPRECATED] Use get-form directly with the token.
    """
    return {'message': 'Verification is now automatic in get-form.'}, 200


def get_form_details(token: str) -> tuple[dict, int]:
    """
    Fetch Form.io details directly using a JWT token.
    Matches server.js logic.
    """
    current_app.logger.info(f"[get-form][STEP 0] Received token: {token[:20]}... (length: {len(token)})")
    try:
        # STEP 1: JWT decode
        secret = current_app.config.get('JWT_SECRET_KEY')
        current_app.logger.info(f"[get-form][STEP 1] Decoding JWT with secret key (preview): {str(secret)[:6]}...")
        try:
            decoded = jwt.decode(token, secret, algorithms=['HS256'], options={"verify_aud": False, "verify_iss": False})
        except jwt.InvalidTokenError as e:
            current_app.logger.error(f"[get-form][STEP 1] FAILED — JWT decode error: {str(e)}")
            return {'error': 'invalid_token', 'message': f'Invalid session token: {str(e)}'}, 401

        process_instance_id = decoded.get('processInstanceId')
        current_app.logger.info(f"[get-form][STEP 1] PASSED — Decoded payload: {decoded}")

        if not process_instance_id:
            current_app.logger.error("[get-form][STEP 1] FAILED — No processInstanceId in JWT payload")
            return {'error': 'invalid_token', 'message': 'Invalid session token: missing processInstanceId'}, 401

        # STEP 2: In-memory token store check
        token_hash = hash_token(token)
        record = _token_store.get(token_hash)
        current_app.logger.info(f"[get-form][STEP 2] In-memory record found: {record is not None}")
        if record:
            current_app.logger.info(f"[get-form][STEP 2] Record: used={record.get('used')}, expires_at={record.get('expires_at')}")
            if record.get('used'):
                current_app.logger.warning("[get-form][STEP 2] FAILED — token already used (in-memory)")
                return {'error': 'token_revoked', 'message': 'Your access link has already been used and is now expired.'}, 401

            now = datetime.now(timezone.utc)
            if record.get('expires_at') and now > record['expires_at']:
                current_app.logger.warning(f"[get-form][STEP 2] FAILED — token expired (in-memory). now={now}, expires_at={record['expires_at']}")
                return {'error': 'token_expired', 'message': 'Your access link has expired.'}, 401
        current_app.logger.info("[get-form][STEP 2] PASSED — in-memory check ok")

        # STEP 3: Revocation list check
        in_revocation = token in _revocation_list or token_hash in _revocation_list
        current_app.logger.info(f"[get-form][STEP 3] Token in revocation list: {in_revocation}")
        if in_revocation:
            current_app.logger.warning("[get-form][STEP 3] FAILED — token is revoked")
            return {'error': 'token_revoked', 'message': 'Your access link has been revoked or used.'}, 401
        current_app.logger.info("[get-form][STEP 3] PASSED — not revoked")

        # STEP 4: Keycloak + Form.io tokens
        bpm_api = current_app.config.get('BPM_API_URL')
        form_api = current_app.config.get('FORMIO_DEFAULT_PROJECT_URL')
        current_app.logger.info(f"[get-form][STEP 4] Config — BPM_API_URL: {bpm_api}, FORMIO_URL: {form_api}")
        kc_token = get_kc_admin_token()
        formio_token = get_formio_token()
        current_app.logger.info(f"[get-form][STEP 4] PASSED — KC token: {kc_token[:10]}..., Formio token: {formio_token[:10]}...")

        # STEP 5: Fetch active Camunda task
        task_url = f"{bpm_api}/engine-rest-ext/v1/task?processInstanceId={process_instance_id}"
        current_app.logger.info(f"[get-form][STEP 5] Calling Camunda task API: {task_url}")
        task_res = requests.get(task_url, headers={"Authorization": f"Bearer {kc_token}"})
        current_app.logger.info(f"[get-form][STEP 5] Camunda response: HTTP {task_res.status_code} — {task_res.text}")
        task_res.raise_for_status()
        tasks = task_res.json()
        if not tasks:
            current_app.logger.warning(f"[get-form][STEP 5] FAILED — No active tasks for processInstanceId: {process_instance_id}")
            return {'error': 'no_task', 'message': 'This access link has already been used or is no longer valid.'}, 404

        task = tasks[0]
        task_id = task.get('id')
        current_app.logger.info(f"[get-form][STEP 5] PASSED — Found {len(tasks)} task(s), using task_id: {task_id}")

        # STEP 6: Fetch task variables
        vars_url = f"{bpm_api}/engine-rest-ext/v1/task/{task_id}/variables"
        current_app.logger.info(f"[get-form][STEP 6] Fetching task variables: {vars_url}")
        vars_res = requests.get(vars_url, headers={"Authorization": f"Bearer {kc_token}"})
        current_app.logger.info(f"[get-form][STEP 6] Variables response: HTTP {vars_res.status_code}")
        if not vars_res.ok:
            current_app.logger.error(f"[get-form][STEP 6] FAILED — Could not fetch variables for task {task_id}: {vars_res.text}")
            return {'error': 'token_expired', 'message': 'Failed to retrieve workflow process variables.'}, 401

        variables = vars_res.json()
        current_app.logger.info(f"[get-form][STEP 6] PASSED — Got {len(variables)} variables. Keys: {list(variables.keys())}")

        # STEP 7: Token binding check (Camunda stored token vs provided token)
        stored_token = variables.get('token', {}).get('value')
        current_app.logger.info(f"[get-form][STEP 7] Stored token in Camunda: {'<missing>' if not stored_token else stored_token[:20] + '...'}")
        current_app.logger.info(f"[get-form][STEP 7] Provided token:           {token[:20]}...")
        if not stored_token:
            current_app.logger.warning(f"[get-form][STEP 7] FAILED — 'token' variable missing in Camunda task {task_id}. Available keys: {list(variables.keys())}")
            return {'error': 'token_not_found', 'message': 'This access link has already been used or is no longer valid.'}, 401
        if stored_token != token:
            current_app.logger.warning(f"[get-form][STEP 7] FAILED — Token mismatch on task {task_id}")
            return {'error': 'token_mismatch', 'message': 'This access link has already been used or is no longer valid.'}, 401
        current_app.logger.info("[get-form][STEP 7] PASSED — Token binding validated")

        # STEP 8: Extract form URL
        form_url_value = variables.get('formUrl', {}).get('value')
        current_app.logger.info(f"[get-form][STEP 8] formUrl from Camunda: {form_url_value}")
        if not form_url_value:
            current_app.logger.error("[get-form][STEP 8] FAILED — 'formUrl' variable missing in Camunda task")
            return {'error': 'missing_form_url', 'message': 'No form URL associated with this process.'}, 500

        form_id = extract_form_id(form_url_value)
        submission_id = extract_submission_id(form_url_value)
        current_app.logger.info(f"[get-form][STEP 8] PASSED — form_id: {form_id}, submission_id: {submission_id}")

        # STEP 9: Fetch form schema from Form.io
        current_app.logger.info(f"[get-form][STEP 9] Fetching form schema: {form_api}/form/{form_id}")
        form_res = requests.get(f"{form_api}/form/{form_id}", headers={"x-jwt-token": formio_token})
        current_app.logger.info(f"[get-form][STEP 9] Form schema response: HTTP {form_res.status_code}")
        form_res.raise_for_status()
        schema = form_res.json()
        current_app.logger.info("[get-form][STEP 9] PASSED — Form schema fetched")

        # STEP 10: Fetch submission prefill data
        prefill = {}
        if submission_id:
            current_app.logger.info(f"[get-form][STEP 10] Fetching submission prefill: {form_api}/form/{form_id}/submission/{submission_id}")
            sub_res = requests.get(f"{form_api}/form/{form_id}/submission/{submission_id}", headers={"x-jwt-token": formio_token})
            current_app.logger.info(f"[get-form][STEP 10] Submission response: HTTP {sub_res.status_code}")
            sub_res.raise_for_status()
            prefill = sub_res.json().get('data', {})
            current_app.logger.info(f"[get-form][STEP 10] PASSED — Prefill keys: {list(prefill.keys())}")
        else:
            current_app.logger.info("[get-form][STEP 10] No submission_id — skipping prefill fetch")

        current_app.logger.info(f"[get-form][DONE] Returning form details. taskId={task_id}, formId={form_id}")
        return {
            'schema': schema,
            'prefill': prefill,
            'taskId': task.get('id'),
            'formId': form_id
        }, 200

    except jwt.ExpiredSignatureError:
        return {'error': 'expired_token', 'message': 'Session token has expired.'}, 401
    except jwt.InvalidTokenError:
        return {'error': 'invalid_token', 'message': 'Invalid session token.'}, 401
    except Exception as e:
        current_app.logger.error(f"FETCH ERROR: {str(e)}")
        return {'error': 'fetch_failed', 'message': str(e)}, 500


def submit_form_details(token: str, data: dict, task_id: str, form_id: str) -> tuple[dict, int]:
    """
    Submits data to Form.io and completes the Camunda task.
    Similar to POST /submit-form in server.js.
    """
    try:
        secret = current_app.config.get('JWT_SECRET_KEY')
        try:
            decoded = jwt.decode(token, secret, algorithms=['HS256'], options={"verify_aud": False, "verify_iss": False})
        except jwt.InvalidTokenError as e:
            return {'error': 'invalid_token', 'message': f'Invalid session token: {str(e)}'}, 401

        process_instance_id = decoded.get('processInstanceId')
        if not process_instance_id:
            return {'error': 'invalid_token', 'message': 'Invalid session token: missing processInstanceId'}, 401

        # 1. Validate using our in-memory token store as an optional fast-fail check
        token_hash = hash_token(token)
        record = _token_store.get(token_hash)
        if record:
            if record.get('used'):
                current_app.logger.warning("Token validation failed during submit: token has already been used (in-memory).")
                return {'error': 'token_revoked', 'message': 'Your access link has already been used and is now expired.'}, 401

            now = datetime.now(timezone.utc)
            if record.get('expires_at') and now > record['expires_at']:
                current_app.logger.warning("Token validation failed during submit: token has expired (in-memory).")
                return {'error': 'token_expired', 'message': 'Your access link has expired.'}, 401

        if token in _revocation_list or token_hash in _revocation_list:
            current_app.logger.warning("Token validation failed during submit: token is revoked.")
            return {'error': 'token_revoked', 'message': 'Session token has been revoked.'}, 401

        # FormsFlow Config
        bpm_api = current_app.config.get('BPM_API_URL')
        form_api = current_app.config.get('FORMIO_DEFAULT_PROJECT_URL')
        kc_token = get_kc_admin_token()
        auth_admin_header = {"Authorization": f"Bearer {kc_token}"}
        formio_header = {"x-jwt-token": get_formio_token()}

        # Retrieve formUrl and token from Camunda task variables using the provided task_id
        submission_id = None
        application_id = None
        if task_id:
            try:
                vars_url = f"{bpm_api}/engine-rest-ext/v1/task/{task_id}/variables"
                current_app.logger.info(f"Retrieving task variables from Camunda: {vars_url}")
                vars_res = requests.get(vars_url, headers=auth_admin_header)
                vars_res.raise_for_status()
                variables = vars_res.json()

                # Validate task variable 'token' matches the provided token
                stored_token = variables.get('token', {}).get('value')
                if not stored_token:
                    current_app.logger.warning(f"Validation Failed: No 'token' variable found in Camunda Task {task_id} during submit. Available: {list(variables.keys())}")
                    return {'error': 'token_not_found', 'message': 'This access link has already been used or is no longer valid.'}, 401
                    
                if stored_token != token:
                    current_app.logger.warning(f"Validation Failed: Token mismatch on Task {task_id} during submit. Provided: {token[:20]}... Stored: {stored_token[:20]}...")
                    return {'error': 'token_mismatch', 'message': 'This access link has already been used or is no longer valid.'}, 401
                    
                current_app.logger.info("Task variable 'token' validation successful during submit.")

                form_url_value = variables.get('formUrl', {}).get('value')
                submission_id = extract_submission_id(form_url_value)
                current_app.logger.info(f"Extracted submission_id from Camunda: {submission_id}")

                application_id = variables.get('applicationId', {}).get('value')
                current_app.logger.info(f"Extracted applicationId from Camunda: {application_id}")
            except Exception as e:
                # If we returned 401 from inside the try block, it won't raise an exception.
                # But we should ensure we return any returned tuple from inside the try block:
                current_app.logger.error(f"Could not retrieve task variables to extract submission_id: {str(e)}")
                return {'error': 'submit_failed', 'message': 'Failed to retrieve workflow process variables.'}, 500

        # 1. Submit/Update Formio
        # If the caller passed the full Form.io submission object (with _id, form, metadata, data)
        # extract just the inner 'data' (form fields). Otherwise use as-is.
        form_fields = data.get('data', data) if isinstance(data, dict) and '_id' in data else data
        req_body = {"data": form_fields}

        if submission_id:
            # Update existing submission using PUT
            url = f"{form_api}/form/{form_id}/submission/{submission_id}"
            current_app.logger.info(f"Updating Form.io submission (PUT). URL: {url}")
            current_app.logger.info(f"Form.io Request Payload: {req_body}")
            form_res = requests.put(url, json=req_body, headers=formio_header)
        else:
            # Fallback to creating a new submission using POST
            url = f"{form_api}/form/{form_id}/submission"
            current_app.logger.info(f"Submitting new Form.io submission (POST). URL: {url}")
            current_app.logger.info(f"Form.io Request Payload: {req_body}")
            form_res = requests.post(url, json=req_body, headers=formio_header)

        current_app.logger.info(f"Form.io Response Status: {form_res.status_code}")
        current_app.logger.info(f"Form.io Response Body: {form_res.text}")
        form_res.raise_for_status()

        if not submission_id:
            submission_id = form_res.json().get('_id')

        # 2. Complete Camunda Task
        # FormsFlow uses the extended api with /submit-form, not /complete
        variables = {key: {"value": val} for key, val in form_fields.items()
                     if isinstance(val, (str, int, float, bool)) or val is None}

        # The Camunda BPMN workflow expects an 'action' variable (e.g. 'Approved', 'Rejected')
        # If the form didn't provide one, default to 'Approved' (which satisfies the gateway logic).
        action_val = form_fields.get("action") or form_fields.get("reviewerAction") or form_fields.get("actionType") or "Approved"
        variables["action"] = {"value": action_val}

        complete_body = {"variables": variables}

        # Use FormsFlow's standard submit-form endpoint
        submit_url = f"{bpm_api}/engine-rest-ext/task/{task_id}/submit-form"
        current_app.logger.info(f"Calling Camunda submit-form API: {submit_url} with variables keys: {list(variables.keys())}")
        complete_res = requests.post(submit_url, json=complete_body, headers=auth_admin_header)
        current_app.logger.info(f"Camunda complete Response Status: {complete_res.status_code}")
        current_app.logger.info(f"Camunda complete Response Body: {complete_res.text}")

        if not complete_res.ok:
            current_app.logger.error(f"Camunda submit-form FAILED [{complete_res.status_code}]: {complete_res.text}")
            current_app.logger.error(f"Camunda submit-form payload sent: {complete_body}")
            return {'error': 'submit_failed', 'message': f'Camunda error [{complete_res.status_code}]: {complete_res.text}'}, 500
        else:
            current_app.logger.info(f"Camunda task {task_id} completed successfully.")

        # 3. Update Application & History in forms-flow-api (non-anonymous submission trace)
        formsflow_api_url = current_app.config.get('FORMSFLOW_API_URL')
        if formsflow_api_url and application_id:
            try:
                new_form_url = f"{form_api}/form/{form_id}/submission/{submission_id}"
                # Use the action value (e.g. "Approved") for the completed application status
                app_status = action_val
                if not app_status:
                    app_status = "Approved"

                # 1. Update Application Status
                app_url = f"{formsflow_api_url}/application/{application_id}"
                app_payload = {
                    "applicationStatus": app_status,
                    "formUrl": new_form_url
                }
                current_app.logger.info(f"Updating application in forms-flow-api: {app_url} with payload {app_payload}")
                app_res = requests.put(app_url, json=app_payload, headers=auth_admin_header)
                if not app_res.ok:
                    current_app.logger.error(f"Failed to update application {application_id} in forms-flow-api (HTTP {app_res.status_code}): {app_res.text}")
                else:
                    current_app.logger.info(f"Successfully updated application {application_id} in forms-flow-api.")

                # 2. Record submission in Application History
                history_url = f"{formsflow_api_url}/application/{application_id}/history"
                history_payload = {
                    "applicationStatus": app_status,
                    "formUrl": new_form_url,
                    "submittedBy": decoded.get('email', 'patient@example.com')
                }
                current_app.logger.info(f"Creating application history in forms-flow-api: {history_url} with payload {history_payload}")
                history_res = requests.post(history_url, json=history_payload, headers=auth_admin_header)
                if not history_res.ok:
                    current_app.logger.error(f"Failed to create history for application {application_id} in forms-flow-api (HTTP {history_res.status_code}): {history_res.text}")
                else:
                    current_app.logger.info(f"Successfully created history for application {application_id} in forms-flow-api.")
            except Exception as e:
                current_app.logger.error(f"Error registering application submission in forms-flow-api: {str(e)}")

        # 4. Invalidate token after successful submission
        _delete_process_variable(process_instance_id, "token")
        revoke_token(token)

        return {'message': 'Success'}, 200

    except Exception as e:
        current_app.logger.error(f"SUBMIT ERROR: {str(e)}")
        return {'error': 'submit_failed', 'message': str(e)}, 500


def resend_magic_link(email: str) -> tuple[dict, int]:
    """
    Find original process_instance_id for the email and issue a new magic link.
    """
    existing_record = None
    for record in reversed(list(_token_store.values())):
        if record['email'] == email:
            existing_record = record
            break

    if not existing_record:
        return {'error': 'no_history', 'message': 'No previous magic link found for this email.'}, 404

    res = request_magic_link(
        email,
        process_instance_id=existing_record['process_instance_id'],
        iss=existing_record.get('iss'),
        aud=existing_record.get('aud'),
        token_expiry=existing_record.get('token_expiry'),
    )
    return res, 200


def revoke_token(token: str) -> tuple[dict, int]:
    """
    Manually revoke a magic link token OR a JWT session token.
    """
    token_hash = hash_token(token)
    if token_hash in _token_store:
        _token_store[token_hash]['used'] = True

    _revocation_list.add(token)       # Store JWT raw
    _revocation_list.add(token_hash)  # Store magic link hash

    return {'message': 'Token revoked successfully.'}, 200


def _invalidate_tokens_for_email(email: str) -> None:
    for record in _token_store.values():
        if record['email'] == email and not record['used']:
            record['used'] = True
