#!/bin/bash
# Ensure the directories exist
mkdir -p /opt/keycloak/themes
mkdir -p /opt/keycloak/data/import
mkdir -p /opt/keycloak/providers

# Copy custom themes, realm imports, and provider jars (custom
# authenticators such as ConfigurableIdpAuthenticator and
# EpicLaunchAssertionAuthenticator live here - Keycloak only loads
# providers from its own providers/ directory, not from an arbitrary path).
cp -rf /keycloak_custom_data/themes/* /opt/keycloak/themes/
cp -rf /keycloak_custom_data/imports/* /opt/keycloak/data/import/
cp -rf /keycloak_custom_data/providers/*.jar /opt/keycloak/providers/

# Default values if the variables are not set
START_MODE=${KEYCLOAK_START_MODE:-"start"}
HTTP_PATH=${KEYCLOAK_HTTP_PATH:-"/auth"}

# Re-run the build step every start so newly added/updated provider jars are
# actually picked up. In Keycloak's non-dev "start" mode, providers must be
# baked in via `kc.sh build` - just having the jar present isn't enough,
# which is the reason a freshly added authenticator can silently fail to
# show up anywhere in the admin console.
/opt/keycloak/bin/kc.sh build

# Construct the command
COMMAND="/opt/keycloak/bin/kc.sh $START_MODE --import-realm --http-relative-path $HTTP_PATH"

# Execute the command
echo "Executing command: $COMMAND"
exec $COMMAND
