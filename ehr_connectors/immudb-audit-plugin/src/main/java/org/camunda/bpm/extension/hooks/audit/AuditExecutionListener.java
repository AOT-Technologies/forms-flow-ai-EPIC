package org.camunda.bpm.extension.hooks.audit;

import org.camunda.bpm.engine.delegate.DelegateExecution;
import org.camunda.bpm.engine.delegate.ExecutionListener;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

/**
 * Global Execution Listener that logs all BPMN events to the Immudb Service.
 */
public class AuditExecutionListener implements ExecutionListener {

    private static final Logger LOGGER = LoggerFactory.getLogger(AuditExecutionListener.class);

    // Configuration: Read from environment variables with safe defaults
    private static final String IMMUDB_SERVICE_URL = System.getenv("IMMUDB_SERVICE_URL") != null
            ? System.getenv("IMMUDB_SERVICE_URL")
            : "http://forms-flow-immudb:5001/api/v1/audit/log";

    private static final String IMMUDB_AUTH_TOKEN = System.getenv("IMMUDB_AUTH_TOKEN");

    // Audit Toggle Configuration
    private static final String IMMUDB_AUDIT_VARIABLE_NAME = System.getenv("IMMUDB_AUDIT_VARIABLE_NAME") != null
            ? System.getenv("IMMUDB_AUDIT_VARIABLE_NAME")
            : "immudb_audit_enabled";

    private static final boolean IMMUDB_AUDIT_ENABLED_DEFAULT = System.getenv("IMMUDB_AUDIT_ENABLED_DEFAULT") == null
            || Boolean.parseBoolean(System.getenv("IMMUDB_AUDIT_ENABLED_DEFAULT"));

    private static final ObjectMapper objectMapper = new ObjectMapper();
    private static final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();

    @Override
    public void notify(DelegateExecution execution) throws Exception {
        if (!isAuditEnabled(execution)) {
            if (LOGGER.isDebugEnabled()) {
                LOGGER.debug("Immudb audit is disabled for process instance: " + execution.getProcessInstanceId());
            }
            return;
        }

        try {
            // 1. Prepare Request Data (Metadata about the flow event)
            Map<String, Object> requestData = new HashMap<>();
            requestData.put("processInstanceId", execution.getProcessInstanceId());
            requestData.put("processDefinitionId", execution.getProcessDefinitionId());
            requestData.put("businessKey", execution.getProcessBusinessKey());
            requestData.put("activityId", execution.getCurrentActivityId());
            requestData.put("activityName", execution.getCurrentActivityName());
            requestData.put("eventName", execution.getEventName());
            requestData.put("timestamp", Instant.now().toString());

            // Add surrogate key for end-to-end traceability
            if (execution.hasVariable("surrogateKey")) {
                requestData.put("surrogateKey", execution.getVariable("surrogateKey"));
            }

            if (execution.hasVariable("patientId")) {
                requestData.put("patientId", execution.getVariable("patientId"));
            }

            if (execution.hasVariable("request")) {
                requestData.put("connectorRequest", execution.getVariable("request"));
            }

            // 2. Prepare Response Data
            Map<String, Object> responseData = new HashMap<>();
            
            // Add surrogate key for end-to-end traceability
            if (execution.hasVariable("surrogateKey")) {
                responseData.put("surrogateKey", execution.getVariable("surrogateKey"));
            }

            if (execution.hasVariable("patientId")) {
                responseData.put("patientId", execution.getVariable("patientId"));
            }
            
            if (execution.hasVariable("response")) {
                responseData.put("connectorResponse", execution.getVariable("response"));
            }

            // 3. Final Payload structure for Immudb API
            Map<String, Object> finalPayload = new HashMap<>();
            String eventName = execution.getEventName();
            finalPayload.put("event_name", "BPMN_" + (eventName != null ? eventName.toUpperCase() : "UNKNOWN") + "_"
                    + (execution.getCurrentActivityId() != null ? execution.getCurrentActivityId() : "NONE"));
            
            // Add surrogate key at top level for easier querying and traceability
            if (execution.hasVariable("surrogateKey")) {
                finalPayload.put("surrogateKey", execution.getVariable("surrogateKey"));
            }
            
            finalPayload.put("request_data", requestData);
            finalPayload.put("response_data", responseData);
            finalPayload.put("tenant_id", "default");
            finalPayload.put("user_id", "system");

            // 4. Send to Immudb Service Asynchronously
            sendToImmudb(finalPayload);

        } catch (Throwable t) {
            LOGGER.error("Failed to capture audit log for activity: " + execution.getCurrentActivityId(), t);
        }
    }

    private void sendToImmudb(Map<String, Object> data) {
        try {
            String jsonPayload = objectMapper.writeValueAsString(data);

            HttpRequest.Builder requestBuilder = HttpRequest.newBuilder()
                    .uri(URI.create(IMMUDB_SERVICE_URL))
                    .timeout(Duration.ofSeconds(10))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(jsonPayload));

            // Add Authorization header if token exists
            if (IMMUDB_AUTH_TOKEN != null && !IMMUDB_AUTH_TOKEN.isEmpty()) {
                requestBuilder.header("Authorization", "Bearer " + IMMUDB_AUTH_TOKEN);
                requestBuilder.header("X-Auth-Token", IMMUDB_AUTH_TOKEN);
            }

            httpClient.sendAsync(requestBuilder.build(), HttpResponse.BodyHandlers.ofString())
                    .thenAccept(response -> {
                        if (response.statusCode() >= 400) {
                            LOGGER.warn("Immudb service returned error: " + response.statusCode() + " - "
                                    + response.body());
                        }
                    })
                    .exceptionally(ex -> {
                        LOGGER.error("Failed to send log to Immudb service", ex);
                        return null;
                    });

        } catch (Exception e) {
            LOGGER.error("Failed to prepare audit log for Immudb service", e);
        }
    }

    /**
     * Checks if auditing is enabled for the current execution.
     * Priority:
     * 1. Process Variable (if exists)
     * 2. Global Default (environment variable IMMUDB_AUDIT_ENABLED_DEFAULT)
     */
    boolean isAuditEnabled(DelegateExecution execution) {
        if (execution.hasVariable(IMMUDB_AUDIT_VARIABLE_NAME)) {
            Object variable = execution.getVariable(IMMUDB_AUDIT_VARIABLE_NAME);
            if (variable instanceof Boolean) {
                return (Boolean) variable;
            } else if (variable instanceof String) {
                return Boolean.parseBoolean((String) variable);
            }
        }
        return IMMUDB_AUDIT_ENABLED_DEFAULT;
    }
}
