FROM python:3.12-slim-bookworm

# Set labels
LABEL Name="formsflow-ehr-connectors"
LABEL Description="EHR Connectors - JWKS and main Epic connector service"

WORKDIR /forms-flow-ehr-connectors/app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose ports: 8002 (EHR Connector), 8003 (JWKS Server)
EXPOSE 8002 8003

# Setup entrypoint script
RUN chmod +x entrypoint.sh

ENTRYPOINT ["/bin/bash", "entrypoint.sh"]

