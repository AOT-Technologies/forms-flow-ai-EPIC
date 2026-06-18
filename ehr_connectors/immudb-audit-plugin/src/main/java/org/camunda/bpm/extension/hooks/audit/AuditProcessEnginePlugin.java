package org.camunda.bpm.extension.hooks.audit;

// Removed redundant import since they are in the same package
import org.camunda.bpm.engine.impl.cfg.AbstractProcessEnginePlugin;
import org.camunda.bpm.engine.impl.cfg.ProcessEngineConfigurationImpl;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.ArrayList;

/**
 * Process Engine Plugin to register the AuditParseListener.
 * Annotated with @Component to be automatically picked up by Spring Boot.
 */
@Component
public class AuditProcessEnginePlugin extends AbstractProcessEnginePlugin {

    private static final Logger LOGGER = LoggerFactory.getLogger(AuditProcessEnginePlugin.class);

    @Override
    public void preInit(ProcessEngineConfigurationImpl processEngineConfiguration) {
        LOGGER.info("Initializing Immudb Audit Plugin...");
        if (processEngineConfiguration.getCustomPostBPMNParseListeners() == null) {
            processEngineConfiguration.setCustomPostBPMNParseListeners(new ArrayList<>());
        }
        processEngineConfiguration.getCustomPostBPMNParseListeners().add(new AuditParseListener());
        LOGGER.info("Immudb Audit Plugin initialized and ParseListener registered.");
    }
}
