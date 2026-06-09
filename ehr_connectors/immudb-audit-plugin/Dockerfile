# Stage 1: Build the Maven project
FROM maven:3.8.1-openjdk-17-slim AS builder
WORKDIR /forms-flow-immudb-plugin/app
COPY pom.xml .
COPY src ./src
RUN mvn clean package -DskipTests

# Stage 2: Create a minimal sidecar image
FROM alpine:3.18
LABEL Name="formsflow-immudb-plugin"
LABEL Description="ImmuDB Audit Plugin for Camunda"

WORKDIR /forms-flow-immudb-plugin/app

COPY --from=builder /forms-flow-immudb-plugin/app/target/immudb-audit-plugin-*.jar ./audit-plugin.jar
CMD ["sh", "-c", "mkdir -p /shared-plugins && cp audit-plugin.jar /shared-plugins/audit-plugin.jar"]
