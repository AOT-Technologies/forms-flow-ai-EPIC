package org.camunda.bpm.extension.hooks.audit;

import org.camunda.bpm.engine.delegate.DelegateExecution;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

public class AuditExecutionListenerTest {

    private AuditExecutionListener listener;
    private DelegateExecution execution;

    @BeforeEach
    void setUp() {
        listener = new AuditExecutionListener();
        execution = Mockito.mock(DelegateExecution.class);
    }

    @Test
    void testIsAuditEnabled_Default() {
        // By default, it should be enabled (unless env var overrides it during test execution)
        when(execution.hasVariable("immudb_audit_enabled")).thenReturn(false);
        assertTrue(listener.isAuditEnabled(execution));
    }

    @Test
    void testIsAuditEnabled_VariableTrue() {
        when(execution.hasVariable("immudb_audit_enabled")).thenReturn(true);
        when(execution.getVariable("immudb_audit_enabled")).thenReturn(true);
        assertTrue(listener.isAuditEnabled(execution));
    }

    @Test
    void testIsAuditEnabled_VariableFalse() {
        when(execution.hasVariable("immudb_audit_enabled")).thenReturn(true);
        when(execution.getVariable("immudb_audit_enabled")).thenReturn(false);
        assertFalse(listener.isAuditEnabled(execution));
    }

    @Test
    void testIsAuditEnabled_VariableStringTrue() {
        when(execution.hasVariable("immudb_audit_enabled")).thenReturn(true);
        when(execution.getVariable("immudb_audit_enabled")).thenReturn("true");
        assertTrue(listener.isAuditEnabled(execution));
    }

    @Test
    void testIsAuditEnabled_VariableStringFalse() {
        when(execution.hasVariable("immudb_audit_enabled")).thenReturn(true);
        when(execution.getVariable("immudb_audit_enabled")).thenReturn("false");
        assertFalse(listener.isAuditEnabled(execution));
    }
}
