"""Immudb Client Service.

This module consolidates the ImmuDB worker client functionality, including:
1. ImmudbService: A singleton client for the standalone ImmuDB worker.
2. immudb_audit: A decorator for logging API events to the worker.
3. report_blueprint: A Flask blueprint for redirecting report requests to the worker.
"""

import functools
import inspect
import json
import logging
import requests
from typing import Callable, Iterable
from cryptography.fernet import Fernet
from flask import Blueprint, current_app, redirect, request

# Initialize Logger
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. ImmudbService Class
# ---------------------------------------------------------------------------

class ImmudbService:
    """Client for the separate ImmuDB worker service."""
    
    _instance = None

    @classmethod
    def get_instance(cls):
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_auth_header(self):
        """Generate the encrypted authentication header."""
        secret_key = current_app.config.get("IMMUDB_SECRET_KEY")
        if not secret_key:
            logger.warning("IMMUDB_SECRET_KEY not configured. Request may fail.")
            return {}
        
        fernet = Fernet(secret_key)
        # Fernet tokens include a timestamp by default
        token = fernet.encrypt(b"immudb-worker-auth")
        return {"X-Auth-Token": token.decode()}

    def log_event(self, tenant_id, event_name, user_id, request_data, response_data, index_keys=None):
        """Log an event by calling the worker's REST API.
        
        Args:
            tenant_id (str): The tenant identifier.
            event_name (str): The name of the event.
            user_id (str): The user identifier.
            request_data (dict): Data from the request.
            response_data (dict): Data from the response.
            index_keys (list, optional): Keys to index.
        """
        try:
            worker_url = current_app.config.get("IMMUDB_WORKER_URL")
            worker_enabled = current_app.config.get("IMMUDB_WORKER_ENABLED")
            
            if not worker_enabled:
                return False
                
            payload = {
                "tenant_id": tenant_id,
                "event_name": event_name,
                "user_id": user_id,
                "request_data": request_data,
                "response_data": response_data,
                "index_keys": index_keys
            }
            
            # Fire and forget / best effort with short timeout
            response = requests.post(
                f"{worker_url}/audit/log", 
                json=payload, 
                headers=self._get_auth_header(),
                timeout=2
            )
            return response.status_code in (200, 201)
            
        except Exception as e:
            logger.warning(f"Failed to log event to worker: {e}")
            return False

    def query_logs(self, **kwargs):
        """Query logs from the worker's REST API."""
        try:
            worker_url = current_app.config.get("IMMUDB_WORKER_URL")
            response = requests.get(
                f"{worker_url}/audit/query", 
                params=kwargs, 
                headers=self._get_auth_header(),
                timeout=5
            )
            if response.status_code == 200:
                return response.json().get("results", [])
            return []
        except Exception as e:
            logger.warning(f"Failed to query worker: {e}")
            return []

    def lookup_surrogate_key(self, application_id):
        """Look up surrogateKey from a prior audit log for the given application.
        
        Calls the worker's /audit/surrogate-key endpoint with the application_id
        so that events like update_application (which don't carry surrogateKey in
        their payload) can still attach the UUID that was logged at creation time.
        
        Returns the surrogateKey string, or None if not found / worker unavailable.
        """
        if not application_id:
            return None
        try:
            worker_url = current_app.config.get("IMMUDB_WORKER_URL")
            worker_enabled = current_app.config.get("IMMUDB_WORKER_ENABLED")
            if not worker_enabled:
                return None
            response = requests.get(
                f"{worker_url}/audit/surrogate-key",
                params={"application_id": application_id},
                headers=self._get_auth_header(),
                timeout=2,
            )
            if response.status_code == 200:
                body = response.json()
                if "surrogate_key" in body:
                    return body["surrogate_key"] # preserves ""
                return None
        except Exception as e:
            logger.warning(f"Failed to lookup surrogate key for app {application_id}: {e}")
        return None

# ---------------------------------------------------------------------------
# 2. immudb_audit Decorator
# ---------------------------------------------------------------------------

def _extract_request_from_args_kwargs(args, kwargs):
    """Extract request data from function arguments."""
    if "data" in kwargs:
        return kwargs["data"]
    if "payload" in kwargs:
        return kwargs["payload"]
    for v in kwargs.values():
        if isinstance(v, dict):
            return v
    for a in args:
        if isinstance(a, dict):
            return a
    return None


def _extract_application_id(args, kwargs):
    """Extract application_id from decorated function arguments.
    
    For functions like update_application(application_id, data, **kwargs),
    application_id is a positional int. Checks kwargs first, then scans
    positional args for the first integer value.
    """
    if "application_id" in kwargs:
        return kwargs["application_id"]
    for a in args:
        if isinstance(a, int):
            return a
    return None


def _extract_surrogate_key(data):
    """Extract surrogateKey from form submission data.
    
    The key may live at multiple depths:
      1. data["surrogateKey"]                    – top-level
      2. data["data"]["surrogateKey"]            – nested form submission
      3. data["request_data"]["surrogateKey"]   – already-wrapped payload
      4. data["response_data"]["surrogateKey"]  – response-wrapped payload
      5. data["data"]["data"]["surrogateKey"]   – double-nested (formsflow-api wraps
                                                   the formio submission inside `data`)

    Returns the first value found (including empty strings), or None if missing.
    """
    if not isinstance(data, dict):
        return None

    # Direct top-level
    val = data.get("surrogateKey")
    if val is not None:
        return str(val)

    # Nested under "data" (most common – formsflow submission payload)
    nested = data.get("data")
    if isinstance(nested, dict):
        val = nested.get("surrogateKey")
        if val is not None:
            return str(val)
        # Double-nested (data.data.surrogateKey)
        double = nested.get("data")
        if isinstance(double, dict):
            val = double.get("surrogateKey")
            if val is not None:
                return str(val)

    # Inside request_data or response_data wrappers
    for wrapper_key in ("request_data", "response_data"):
        wrapper = data.get(wrapper_key)
        if isinstance(wrapper, dict):
            val = wrapper.get("surrogateKey")
            if val is not None:
                return str(val)
            inner = wrapper.get("data")
            if isinstance(inner, dict):
                val = inner.get("surrogateKey")
                if val is not None:
                    return str(val)

    return None


def _inject_surrogate_key(data, surrogate_key):
    """Return a shallow copy of *data* with surrogateKey hoisted to the top level.
    
    If surrogate_key is None or data is not a dict, returns data unchanged.
    Allows empty strings to be injected.
    The original dict is never mutated.
    """
    if surrogate_key is None or not isinstance(data, dict):
        return data
    result = dict(data)          # shallow copy – safe for audit logging
    result["surrogateKey"] = surrogate_key
    return result

def _extract_tenant(user, kwargs, request_data):
    """Extract tenant from multiple sources."""
    tenant = kwargs.get("tenant_key")
    if tenant:
        return tenant
    
    tenant = getattr(user, "tenant_key", None) if user else None
    if tenant:
        return tenant
    
    if isinstance(request_data, dict):
        tenant = request_data.get("tenant") or request_data.get("tenant_key")
        if tenant:
            return tenant
    
    return None

def immudb_audit(event_name: str, index_keys: Iterable[str] | None = None, **kwargs):
    """Decorator to log request/response to separate ImmuDB worker.
    
    Automatically extracts ``surrogateKey`` from the form-submission payload and
    hoists it to the top level of both ``request_data`` and ``response_data``
    before forwarding them to the ImmuDB worker.  The key is *always* added to
    ``index_keys`` so that it is indexed and queryable even when the caller
    does not explicitly list it.

    This client sends the log event via HTTP POST to the worker service.
    """
    # Ensure surrogateKey is always indexed regardless of caller-supplied keys
    _index_keys = list(index_keys) if index_keys else []
    if "surrogateKey" not in _index_keys:
        _index_keys.append("surrogateKey")

    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            is_async = inspect.iscoroutinefunction(func)
            
            # Prepare audit data before execution
            req = _extract_request_from_args_kwargs(args, kwargs)
            user = kwargs.get("user")
            tenant = _extract_tenant(user, kwargs, req)
            user_id = getattr(user, "user_name", None) if user else None
            
            # ----------------------------------------------------------------
            # Extract surrogateKey from the incoming request so we can attach
            # it to both request_data and response_data in the audit record.
            # ----------------------------------------------------------------
            # Extract surrogateKey BEFORE execution: needed because the function
            # may call _filter_sensitive_data later which strips the nested 'data'
            # sub-dict where surrogateKey lives.
            surrogate_key = _extract_surrogate_key(req) if req else None

            # Extract application_id BEFORE execution for potential fallback lookup.
            app_id = _extract_application_id(args, kwargs)

            service = ImmudbService.get_instance()

            if is_async:
                # Async wrapper
                @functools.wraps(func)
                async def async_wrapper(*args, **kwargs):
                    try:
                        res = await func(*args, **kwargs)
                        # Extract result body: handle tuples (obj, status) or (dict, status)
                        # Some services return (obj, tuple_of_dict_and_status)
                        body = None
                        if isinstance(res, (list, tuple)):
                            # Look for a dict or response object in the tuple
                            for item in res:
                                if isinstance(item, dict):
                                    body = item
                                    break
                                if isinstance(item, (list, tuple)) and len(item) > 0 and isinstance(item[0], dict):
                                    body = item[0]
                                    break
                            
                            if body is None and len(res) > 0:
                                # Fallback to first item if it's not a dict
                                payload = res[0]
                                try:
                                    body = payload if isinstance(payload, dict) else json.loads(json.dumps(payload, default=str))
                                except Exception:
                                    body = {"result": str(payload)}
                                    # Try to extract ID if it's a model
                                    if hasattr(payload, "id"):
                                        body["id"] = payload.id
                        else:
                            body = res if isinstance(res, dict) else json.loads(json.dumps(res, default=str))

                        if not isinstance(body, dict):
                            # Ensure it's a dict so we can inject surrogateKey and index it
                            prev_body = body
                            body = {"result": prev_body}
                            # 'payload' is from the res tuple or res itself
                            temp_payload = res[0] if isinstance(res, (list, tuple)) and len(res) > 0 else res
                            if hasattr(temp_payload, "id"):
                                body["id"] = temp_payload.id

                        # --- FIX: Ensure application_id is present for worker-side indexing ---
                        if isinstance(body, dict):
                            if "application_id" in _index_keys and "application_id" not in body:
                                if "id" in body:
                                    body["application_id"] = body["id"]
                                elif app_id:
                                    body["application_id"] = app_id

                        # --- SNAPSHOT AFTER execution so in-place mutations (created_by, etc) are captured ---
                        sk = surrogate_key
                        if sk is None:
                            sk = _extract_surrogate_key(req)
                        if sk is None:
                            sk = _extract_surrogate_key(body)
                        
                        logger.warning(f"[DEBUG IMMUDB] Async event={event_name}, app_id={app_id}, initial_sk={repr(sk)}")

                        # Fallback: lookup from prior audit logs using application_id
                        if sk in (None, "") and app_id:
                            sk = service.lookup_surrogate_key(app_id)
                            logger.warning(f"[DEBUG IMMUDB] Async fallback sk={repr(sk)}")
                        
                        audit_req = _inject_surrogate_key(req, sk) if req else req
                        audit_body = _inject_surrogate_key(body, sk)

                        # Log success
                        service.log_event(tenant, event_name, user_id, audit_req, audit_body, _index_keys)
                        return res
                    except Exception as exc:
                        # Log error — snapshot req at point of failure
                        sk = surrogate_key or _extract_surrogate_key(req)
                        if not sk and app_id:
                            sk = service.lookup_surrogate_key(app_id)
                        audit_req = _inject_surrogate_key(req, sk) if req else req
                        service.log_event(tenant, event_name, user_id, audit_req, {"error": str(exc), "surrogateKey": sk or ""}, _index_keys)
                        raise
                return async_wrapper
            else:
                # Sync wrapper
                try:
                    res = func(*args, **kwargs)
                    # Extract result body: handle tuples (obj, status) or (dict, status)
                    body = None
                    if isinstance(res, (list, tuple)):
                        # Look for a dict or response object in the tuple
                        for item in res:
                            if isinstance(item, dict):
                                body = item
                                break
                            if isinstance(item, (list, tuple)) and len(item) > 0 and isinstance(item[0], dict):
                                body = item[0]
                                break
                        
                        if body is None and len(res) > 0:
                            # Fallback to first item if it's not a dict
                            payload = res[0]
                            try:
                                body = payload if isinstance(payload, dict) else json.loads(json.dumps(payload, default=str))
                            except Exception:
                                body = {"result": str(payload)}
                                # Try to extract ID if it's a model
                                if hasattr(payload, "id"):
                                    body["id"] = payload.id
                    else:
                        body = res if isinstance(res, dict) else json.loads(json.dumps(res, default=str))

                    if not isinstance(body, dict):
                        # Ensure it's a dict so we can inject surrogateKey and index it
                        prev_body = body
                        body = {"result": prev_body}
                        # 'payload' is from the res tuple or res itself
                        temp_payload = res[0] if isinstance(res, (list, tuple)) and len(res) > 0 else res
                        if hasattr(temp_payload, "id"):
                            body["id"] = temp_payload.id

                    # --- FIX: Ensure application_id is present for worker-side indexing ---
                    if isinstance(body, dict):
                        if "application_id" in _index_keys and "application_id" not in body:
                            if "id" in body:
                                body["application_id"] = body["id"]
                            elif app_id:
                                body["application_id"] = app_id

                    # --- SNAPSHOT AFTER execution so in-place mutations (created_by, etc) are captured ---
                    sk = surrogate_key
                    if sk is None:
                        sk = _extract_surrogate_key(req)
                    if sk is None:
                        sk = _extract_surrogate_key(body)
                    
                    logger.warning(f"[DEBUG IMMUDB] Sync event={event_name}, app_id={app_id}, initial_sk={repr(sk)}")

                    # Fallback: lookup from prior audit logs using application_id
                    if sk in (None, "") and app_id:
                        sk = service.lookup_surrogate_key(app_id)
                        logger.warning(f"[DEBUG IMMUDB] Sync fallback sk={repr(sk)}")
                    
                    audit_req = _inject_surrogate_key(req, sk) if req else req
                    audit_body = _inject_surrogate_key(body, sk)

                    # Log success
                    service.log_event(tenant, event_name, user_id, audit_req, audit_body, _index_keys)
                    return res
                except Exception as exc:
                    # Log error — snapshot req at point of failure
                    sk = surrogate_key or _extract_surrogate_key(req)
                    if not sk and app_id:
                        sk = service.lookup_surrogate_key(app_id)
                    audit_req = _inject_surrogate_key(req, sk) if req else req
                    service.log_event(tenant, event_name, user_id, audit_req, {"error": str(exc), "surrogateKey": sk or ""}, _index_keys)
                    raise

        return wrapper
    return decorator
