#!/bin/sh

# Ensure config directory exists
mkdir -p /app/config

# Extract original mail-config.properties from the JAR using the JDK 'jar' tool
mkdir -p /tmp/extract
cd /tmp/extract
jar xf /app/forms-flow-bpm.jar BOOT-INF/classes/mail-config.properties

if [ -f BOOT-INF/classes/mail-config.properties ]; then
  # Copy it as the base and append the environment-specific credentials
  cp BOOT-INF/classes/mail-config.properties /app/config/mail-config.properties
  echo "" >> /app/config/mail-config.properties
  echo "mail.user=${MAIL_USER}" >> /app/config/mail-config.properties
  echo "mail.password=${MAIL_PASSWORD}" >> /app/config/mail-config.properties
  echo "Successfully generated /app/config/mail-config.properties with mail.user and mail.password variables."
else
  echo "Warning: Could not extract mail-config.properties from JAR, using fallbacks."
fi

# Clean up temporary extraction directory
rm -rf /tmp/extract

# Move back to /app directory so JVM has a valid current working directory (CWD)
cd /app

# Start the application using PropertiesLauncher. We put /app/config first in loader.path
# so that the dynamically generated mail-config.properties is loaded from the classpath.
exec java \
  -Djava.security.egd=file:/dev/./urandom \
  -Dpolyglot.js.nashorn-compat=true \
  -Dpolyglot.engine.WarnInterpreterOnly=false \
  -Dloader.path=/app/config,/app/plugins \
  -cp /app/forms-flow-bpm.jar \
  org.springframework.boot.loader.launch.PropertiesLauncher
