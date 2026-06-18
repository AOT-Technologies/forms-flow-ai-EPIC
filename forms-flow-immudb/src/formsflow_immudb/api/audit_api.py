"""REST API endpoints for audit logging."""

import logging
from flask import Blueprint, request, jsonify, current_app
from ..services.immudb_service import ImmudbService
from ..utils.auth import require_auth

logger = logging.getLogger(__name__)

audit_bp = Blueprint('audit', __name__)


@audit_bp.route('/audit/log', methods=['POST'])
@require_auth
def log_audit_event():
    """Log a single audit event.
    
    Expected JSON payload:
    {
        "tenant_id": "string",
        "event_name": "string",
        "user_id": "string",
        "request_data": {},
        "response_data": {},
        "index_keys": ["key1", "key2"]  # optional
    }
    
    Returns:
        JSON response with status
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No JSON payload provided'}), 400
        
        # Validate required fields
        required = ['event_name', 'request_data', 'response_data']
        missing = [field for field in required if field not in data]
        
        if missing:
            return jsonify({
                'error': 'Missing required fields',
                'missing_fields': missing
            }), 400
        
        service = ImmudbService.get_instance()
        
        success = service.log_event(
            tenant_id=data.get('tenant_id'),
            event_name=data['event_name'],
            user_id=data.get('user_id'),
            request_data=data['request_data'],
            response_data=data['response_data'],
            index_keys=data.get('index_keys')
        )
        
        if success:
            logger.info(f"Successfully logged event: {data['event_name']}")
            return jsonify({
                'status': 'success',
                'message': 'Event logged successfully'
            }), 201
        else:
            logger.warning(f"Failed to log event: {data['event_name']}")
            return jsonify({
                'status': 'warning',
                'message': 'Event logging failed (ImmuDB might be disabled)'
            }), 200
        
    except Exception as e:
        logger.error(f"Error in log_audit_event: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@audit_bp.route('/audit/log/batch', methods=['POST'])
@require_auth
def log_batch_events():
    """Log multiple audit events in a single request.
    
    Expected JSON payload:
    {
        "events": [
            {
                "tenant_id": "string",
                "event_name": "string",
                "user_id": "string",
                "request_data": {},
                "response_data": {},
                "index_keys": []
            },
            ...
        ]
    }
    
    Returns:
        JSON response with batch processing results
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No JSON payload provided'}), 400
        
        events = data.get('events', [])
        
        if not events:
            return jsonify({'error': 'No events provided'}), 400
        
        if not isinstance(events, list):
            return jsonify({'error': 'Events must be an array'}), 400
        
        service = ImmudbService.get_instance()
        logged_count = 0
        errors = []
        
        for idx, event in enumerate(events):
            try:
                # Validate event structure
                required = ['event_name', 'request_data', 'response_data']
                if not all(k in event for k in required):
                    errors.append({
                        'index': idx,
                        'error': 'Missing required fields'
                    })
                    continue
                
                success = service.log_event(
                    tenant_id=event.get('tenant_id'),
                    event_name=event['event_name'],
                    user_id=event.get('user_id'),
                    request_data=event['request_data'],
                    response_data=event['response_data'],
                    index_keys=event.get('index_keys')
                )
                
                if success:
                    logged_count += 1
                else:
                    errors.append({
                        'index': idx,
                        'error': 'Failed to log event'
                    })
                    
            except Exception as e:
                logger.error(f"Error logging event at index {idx}: {e}")
                errors.append({
                    'index': idx,
                    'error': str(e)
                })
        
        status_code = 201 if not errors else (207 if logged_count > 0 else 500)
        
        return jsonify({
            'status': 'completed',
            'logged': logged_count,
            'total': len(events),
            'errors': errors
        }), status_code
        
    except Exception as e:
        logger.error(f"Error in log_batch_events: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@audit_bp.route('/audit/query', methods=['GET'])
@require_auth
def query_audit_logs():
    """Query audit logs with filters.
    
    Query parameters:
        tenant_id: Filter by tenant ID
        event_name: Filter by event name
        user_id: Filter by user ID
        date_from: Start date (ISO format)
        date_to: End date (ISO format)
        limit: Maximum results (default: 100, max: 1000)
        offset: Number of results to skip (default: 0)
    
    Returns:
        JSON response with query results
    """
    try:
        # Parse query parameters
        tenant_id = request.args.get('tenant_id', '').strip()
        event_name = request.args.get('event_name', '').strip()
        user_id = request.args.get('user_id', '').strip()
        surrogate_key = request.args.get('surrogate_key', '').strip()
        date_from = request.args.get('date_from', '').strip()
        date_to = request.args.get('date_to', '').strip()
        
        # Parse pagination parameters
        try:
            limit = min(int(request.args.get('limit', 100)), 1000)
        except ValueError:
            limit = 100
        
        try:
            offset = max(int(request.args.get('offset', 0)), 0)
        except ValueError:
            offset = 0
        
        service = ImmudbService.get_instance()
        
        results = service.query_logs(
            tenant_id=tenant_id if tenant_id else None,
            event_name=event_name if event_name else None,
            user_id=user_id if user_id else None,
            surrogate_key=surrogate_key if surrogate_key else None,
            date_from=date_from if date_from else None,
            date_to=date_to if date_to else None,
            limit=limit,
            offset=offset
        )
        
        # Format results
        # Row order: id, tenant_id, event_name, user_id, surrogate_key,
        #            request_data, response_data, created_at
        formatted_results = []
        for row in results:
            formatted_results.append({
                'id': row[0],
                'tenant_id': row[1],
                'event_name': row[2],
                'user_id': row[3],
                'surrogate_key': row[4],
                'request_data': row[5],
                'response_data': row[6],
                'indexed_json': row[7],
                'created_at': row[8]
            })
        
        return jsonify({
            'status': 'success',
            'results': formatted_results,
            'count': len(formatted_results),
            'limit': limit,
            'offset': offset
        }), 200
        
    except Exception as e:
        logger.error(f"Error in query_audit_logs: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@audit_bp.route('/audit/search', methods=['GET'])
def search_audit_logs():
    """Advanced search in audit logs.
    
    This is an alias for query_audit_logs with the same functionality.
    """
    return query_audit_logs()


@audit_bp.route('/audit/surrogate-key', methods=['GET'])
@require_auth
def get_surrogate_key_for_application():
    """Get the surrogateKey UUID for a given application_id.

    Used by the formsflow-api immudb_audit decorator on events like
    update_application, where the Camunda payload doesn't carry surrogateKey.
    The decorator calls this endpoint to retrieve the UUID that was stored
    in the create_application audit log for the same application.

    Query parameters:
        application_id: Integer application ID to look up (required)

    Returns:
        JSON: { "surrogate_key": "<uuid or empty string>" }
    """
    try:
        raw = request.args.get('application_id', '').strip()
        if not raw:
            return jsonify({'error': 'application_id is required'}), 400

        try:
            application_id = int(raw)
        except ValueError:
            return jsonify({'error': 'application_id must be an integer'}), 400

        service = ImmudbService.get_instance()
        sk = service.get_surrogate_key_for_application(application_id)

        return jsonify({'surrogate_key': sk or ''}), 200

    except Exception as e:
        logger.error(f"Error in get_surrogate_key_for_application: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@audit_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring.
    
    Returns:
        JSON response with service health status
    """
    try:
        service = ImmudbService.get_instance()
        
        return jsonify({
            'status': 'healthy',
            'service': 'forms-flow-immudb',
            'immudb_enabled': service.enabled
        }), 200
        
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        return jsonify({
            'status': 'unhealthy',
            'service': 'forms-flow-immudb',
            'error': str(e)
        }), 503
