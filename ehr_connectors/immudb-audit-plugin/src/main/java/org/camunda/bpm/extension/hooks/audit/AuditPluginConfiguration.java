package org.camunda.bpm.extension.hooks.audit;

import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.context.annotation.ComponentScan;

@AutoConfiguration
@ComponentScan(basePackages = "org.camunda.bpm.extension.hooks.audit")
public class AuditPluginConfiguration {
    // This class will trigger component scanning for the plugin package
    // even when loaded from an external JAR via PropertiesLauncher.
}
