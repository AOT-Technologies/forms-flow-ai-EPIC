package org.camunda.bpm.extension.hooks.audit;

import org.camunda.bpm.engine.delegate.ExecutionListener;
import org.camunda.bpm.engine.impl.bpmn.parser.AbstractBpmnParseListener;
import org.camunda.bpm.engine.impl.pvm.process.ActivityImpl;
import org.camunda.bpm.engine.impl.pvm.process.ScopeImpl;
import org.camunda.bpm.engine.impl.util.xml.Element;

/**
 * Parses BPMN definitions and automatically attaches the AuditExecutionListener
 * to all relevant flow nodes (Start, End, ServiceTask, UserTask, etc.).
 */
public class AuditParseListener extends AbstractBpmnParseListener {

    private final ExecutionListener auditListener = new AuditExecutionListener();

    @Override
    public void parseStartEvent(Element startEventElement, ScopeImpl scope, ActivityImpl startEventActivity) {
        addAuditListener(startEventActivity);
    }

    @Override
    public void parseEndEvent(Element endEventElement, ScopeImpl scope, ActivityImpl endEventActivity) {
        addAuditListener(endEventActivity);
    }

    @Override
    public void parseServiceTask(Element serviceTaskElement, ScopeImpl scope, ActivityImpl activity) {
        addAuditListener(activity);
    }

    @Override
    public void parseUserTask(Element userTaskElement, ScopeImpl scope, ActivityImpl activity) {
        addAuditListener(activity);
    }
    
    @Override
    public void parseCallActivity(Element callActivityElement, ScopeImpl scope, ActivityImpl activity) {
        addAuditListener(activity);
    }

    // Helper to add listener to both START and END of the activity execution
    private void addAuditListener(ActivityImpl activity) {
        activity.addExecutionListener(ExecutionListener.EVENTNAME_START, auditListener);
        activity.addExecutionListener(ExecutionListener.EVENTNAME_END, auditListener);
    }
}
