/**
 * EHR Configuration Utility
 * Centralized configuration for SMART on FHIR integration
 */

/**
 * Check if EHR integration is enabled
 * @returns {boolean} True if EHR integration is enabled
 */
export function isEhrEnabled() {
  // const enabled = (window._env_ && window._env_.REACT_APP_EHR_ENABLED) ||
  //                 process.env.REACT_APP_EHR_ENABLED;
  return true;
}

/**
 * Get SMART on FHIR configuration
 * Reads from environment variables or provides defaults
 * Falls back to extracting client_id from JWT token if not configured
 * 
 * @param {string} formId - Optional form ID for constructing redirect URI
 * @returns {Object} SMART configuration object
 */
export function getSMARTConfig(formId = null) {
  const baseRedirectUri = (window._env_ && window._env_.REACT_APP_SMART_REDIRECT_URI) ||
                          process.env.REACT_APP_SMART_REDIRECT_URI;
  
  // If no explicit redirect URI is set, use current page with formId
  let redirectUri = baseRedirectUri;
  if (!redirectUri && formId) {
    const currentPath = window.location.pathname;
    redirectUri = window.location.origin + currentPath;
  } else if (!redirectUri) {
    redirectUri = window.location.origin + window.location.pathname;
  }
  
  // Try to get client ID from environment, fall back to JWT token
  let clientId = (window._env_ && window._env_.REACT_APP_SMART_CLIENT_ID) ||
                 process.env.REACT_APP_SMART_CLIENT_ID;
  
  if (!clientId) {
    // Try to extract from JWT token in sessionStorage
    try {
      const code = sessionStorage.getItem('epic_code');
      if (code) {
        // JWT tokens have 3 parts separated by dots
        const parts = code.split('.');
        if (parts.length === 3) {
          // Decode the payload (second part)
          // Replace URL-safe base64 characters
          const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/');
          // Add padding if needed
          const padded = payload + '='.repeat(((4 - (payload.length % 4)) % 4));
          const decoded = JSON.parse(atob(padded));
          clientId = decoded.client_id || null;
        }
      }
    } catch (error) {
      // Silently fail - extraction failed
    }
  }
  
  return {
    clientId: clientId || '',
    redirectUri: redirectUri,
    scope: (window._env_ && window._env_.REACT_APP_SMART_SCOPE) ||
           process.env.REACT_APP_SMART_SCOPE ||
           // openid fhirUser requests Epic's signed id_token/fhirUser claim -
           // required for the Keycloak handoff in keycloakHandoff.js.
           'openid fhirUser launch launch/patient patient/*.read'
  };
}

/**
 * Config for handing an EHR-launched session off to Keycloak (see
 * keycloakHandoff.js). Separate from getSMARTConfig() above since these
 * point at formsflow's own services, not Epic's.
 */
export function getKeycloakHandoffConfig() {
  return {
    ehrConnectorUrl: (window._env_ && window._env_.REACT_APP_EHR_CONNECTOR_URL) ||
                     process.env.REACT_APP_EHR_CONNECTOR_URL,
    keycloakRealmUrl: (window._env_ && window._env_.REACT_APP_KEYCLOAK_EPIC_REALM_URL) ||
                      process.env.REACT_APP_KEYCLOAK_EPIC_REALM_URL,
    clientId: (window._env_ && window._env_.REACT_APP_KEYCLOAK_EPIC_CLIENT_ID) ||
              process.env.REACT_APP_KEYCLOAK_EPIC_CLIENT_ID ||
              'formsflow-epic-web',
  };
}

/**
 * Check if debug logging should be enabled
 * Based on NODE_ENV or a specific debug flag
 * 
 * @returns {boolean} True if debug logging should be enabled
 */
export function isDebugEnabled() {
  const nodeEnv = (window._env_ && window._env_.NODE_ENV) || 
                  process.env.NODE_ENV || 
                  'development';
  const debugFlag = (window._env_ && window._env_.REACT_APP_EHR_DEBUG) ||
                    process.env.REACT_APP_EHR_DEBUG;
  
  return nodeEnv === 'development' || debugFlag === 'true';
}

/**
 * Debug logger that only logs in development or when debug flag is set
 * 
 * @param {...any} args - Arguments to log
 */
export function debugLog(...args) {
  if (isDebugEnabled()) {
    console.log(...args);
  }
}

/**
 * Debug error logger
 * 
 * @param {...any} args - Arguments to log
 */
export function debugError(...args) {
  if (isDebugEnabled()) {
    console.error(...args);
  }
}

/**
 * Debug warn logger
 * 
 * @param {...any} args - Arguments to log
 */
export function debugWarn(...args) {
  if (isDebugEnabled()) {
    console.warn(...args);
  }
}
