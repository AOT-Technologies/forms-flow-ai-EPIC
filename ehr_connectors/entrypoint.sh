#!/bin/bash

# If SERVICE_TYPE is "jwks", run only the JWKS server
if [ "$SERVICE_TYPE" = "jwks" ]; then
    echo "Starting JWKS Server on port ${JWKS_PORT:-8003}..."
    exec python jwks_server.py
# If SERVICE_TYPE is "connector", run only the EHR Connector API
elif [ "$SERVICE_TYPE" = "connector" ]; then
    echo "Starting EHR Connector API on port ${PORT:-8002}..."
    exec python -m src.main
# Otherwise (default), run both
else
    echo "Starting both JWKS Server and EHR Connector API..."
    
    # Run both in the background and record their PIDs
    python jwks_server.py &
    PID_JWKS=$!
    
    python -m src.main &
    PID_CONN=$!
    
    # Function to shut down both
    cleanup() {
        echo "Shutting down processes..."
        kill -TERM $PID_JWKS 2>/dev/null
        kill -TERM $PID_CONN 2>/dev/null
    }
    
    # Handle termination signals
    trap cleanup SIGINT SIGTERM EXIT
    
    # Wait for either process to terminate
    wait -n
    
    # Exit with the status of the terminated process
    exit $?
fi
