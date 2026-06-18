# Immudb Audit Plugin for Camunda

This plugin automatically captures BPMN events in Camunda and logs them to a standalone Immudb worker service for immutable auditing.

## Features
- **Zero-Code Instrumentation**: Automatically attaches to all Start Events, End Events, Service Tasks, User Tasks, and Call Activities.
- **Data Capture**: Captures process metadata (Instance ID, Activity Name, Timestamp) and connector variables (`request`/`response`).
- **Immutable Storage**: Sends data to `forms-flow-immudb` for tamper-proof logging.
- **Highly Compatible**: Built for Camunda 7.21 (Spring Boot 3.3) and Java 17+.

---

## 🏗️ Development & Build

### Prerequisites
- Java 17 or higher.
- Maven 3.8+.

### Project Structure
The code follows the required Camunda package structure:
`src/main/java/org/camunda/bpm/extension/hooks/audit/`

### Build Command
Run this command in the plugin directory to generate the JAR:
```powershell
mvn clean package -DskipTests
```
The output will be found at `target/immudb-audit-plugin-1.0.0-SNAPSHOT.jar`.

---

## 🚀 Deployment (End-to-End)

Follow these steps to deploy the plugin to your `forms-flow-bpm` environment.

### 1. Prepare the Plugin JAR
After building, copy the JAR to your deployment location (e.g., your `docker` folder):
```powershell
mkdir deployment/docker/plugins
copy ehr_connectors/immudb-audit-plugin/target/immudb-audit-plugin-1.0.0-SNAPSHOT.jar deployment/docker/plugins/audit-plugin.jar
```

### 2. Configure docker-compose.yml
Update the `forms-flow-bpm` service configuration:

1.  **Mount the Volume**:
    ```yaml
    volumes:
      - ./plugins/audit-plugin.jar:/app/plugins/audit-plugin.jar
    ```
2.  **Add Environment Variables**:
    ```yaml
    environment:
      - IMMUDB_SERVICE_URL=http://<YOUR_IP>:5001/api/v1/audit/log
      - IMMUDB_AUTH_TOKEN=<YOUR_AUTH_TOKEN>
      # --- New Configuration (Optional) ---
      - IMMUDB_AUDIT_VARIABLE_NAME=immudb_audit_enabled  # Variable to check in BPMN
      - IMMUDB_AUDIT_ENABLED_DEFAULT=true               # Global toggle
    ```

### 3. Usage: Control Logging per Process
You can now control which processes are logged to Immudb using a process variable:

- **Disable Logging**: Set a process variable `immudb_audit_enabled` (Boolean or String) to `false`.
    - To disable the **entire process**, pass this variable when starting the instance.
    - To disable logging **mid-flow**, use a Script Task or Listener to set the variable.
- **Enabled (Default)**: If the variable is missing or set to `true`, logging proceeds as usual.

### 4. Override Entrypoint
    Force Spring to use `PropertiesLauncher` to load external JARs:
    ```yaml
    entrypoint: ["java", "-Djava.security.egd=file:/dev/./urandom", "-Dloader.path=/app/plugins", "-cp", "/app/forms-flow-bpm.jar", "org.springframework.boot.loader.launch.PropertiesLauncher"]
    ```

### 5. Restart Services
```powershell
docker-compose up -d --force-recreate forms-flow-bpm
```

---

## 🔍 Verification
Once the service starts, verify the installation in the logs:

```powershell
docker logs forms-flow-bpm | findstr "Immudb"
```

**Correct Output:**
```text
default - 2026-02-18 04:24:26 - Initializing Immudb Audit Plugin...
default - 2026-02-18 04:24:26 - Immudb Audit Plugin initialized and ParseListener registered.
```

---

## 📂 Important Files
- `AuditProcessEnginePlugin.java`: The entry point that registers the listeners.
- `AuditParseListener.java`: Hooks into the BPMN parser to find flow nodes.
- `AuditExecutionListener.java`: Sends the actual event data to the API.
- `META-INF/services/...`: SPI registration for Camunda to discover the plugin.
