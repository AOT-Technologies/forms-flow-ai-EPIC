import { launchSMART, getPatient, fetchPatientData } from "./service";
import { debugError, debugLog } from "./config";
import { completeKeycloakHandoff } from "./keycloakHandoff";

/**
 * Send consent document to Epic FHIR server
 * @param {Object} submissionData - Form submission data
 * @returns {Promise<Object>} Result with ok status and response body
 */
export async function sendConsentDocumentToEpic(submissionData) {
  const submission = submissionData || {};

  if (submission.approved !== true) {
    return { skipped: true, reason: "Not approved" };
  }

  const client = window.__formsflowSmartClient;

  if (!client) {
    throw new Error(
      "SMART client not initialized. " +
      "Ensure you launched from Epic with ?isEHR=true " +
      "parameter or called window.formsflowEhr.initializeSMART()"
    );
  }

  const patientId =
    client.patient?.id || client.state?.tokenResponse?.patient;

  if (!patientId) {
    throw new Error("No patient in SMART context. Patient ID could not be extracted from SMART client.");
  }

  const approvedAt = submission.approvedAt || new Date().toISOString();

  const documentReferencePayload = {
    resourceType: "DocumentReference",
    status: "current",
    type: {
      coding: [
        {
          system: "http://loinc.org",
          code: "59284-0",
          display: "Consent"
        }
      ]
    },
    subject: {
      reference: `Patient/${patientId}`
    },
    date: approvedAt,
    author: [
      {
        reference:
          client.user?.id
            ? `Practitioner/${client.user.id}`
            : `Patient/${patientId}`
      }
    ],
    content: [
      {
        attachment: {
          contentType: "text/plain",
          data: btoa(submission.consentText || "Patient consent approved"),
          title: "Patient Consent Form"
        }
      }
    ],
    context: {
      period: {
        start: approvedAt
      }
    }
  };

  try {
    const response = await client.request({
      url: "DocumentReference",
      method: "POST",
      headers: {
        "Content-Type": "application/fhir+json"
      },
      body: JSON.stringify(documentReferencePayload)
    });

    return {
      ok: true,
      status: 201,
      body: response
    };
  } catch (error) {
    return {
      ok: false,
      status: error.status || 500,
      error: error.message,
      body: error
    };
  }
}

/**
 * Initialize SMART on FHIR client automatically
 * Called during app initialization if isEHR flag is present
 */
async function initializeSMART() {
  try {
    if (typeof window === "undefined") {
      debugError("Window object not available for SMART initialization");
      return null;
    }

    // Get configuration from window or environment. REACT_APP_EPIC_* falls
    // back to REACT_APP_SMART_* (the ones actually configured in
    // deployment/docker/.env, also used by launch.html/config.js) rather
    // than a separate hardcoded default - two parallel, differently-named
    // config surfaces for the same SMART app was leaving this path
    // unconfigured even though the "real" one was set.
    const clientId =
      window._env_?.REACT_APP_EPIC_CLIENT_ID ||
      process.env.REACT_APP_EPIC_CLIENT_ID ||
      window._env_?.REACT_APP_SMART_CLIENT_ID ||
      process.env.REACT_APP_SMART_CLIENT_ID;
    let redirectUri =
      window._env_?.REACT_APP_EPIC_REDIRECT_URI ||
      process.env.REACT_APP_EPIC_REDIRECT_URI ||
      window._env_?.REACT_APP_SMART_REDIRECT_URI ||
      process.env.REACT_APP_SMART_REDIRECT_URI;
    const defaultScope =
      window._env_?.REACT_APP_SMART_SCOPE ||
      process.env.REACT_APP_SMART_SCOPE ||
      "openid fhirUser launch patient/Patient.read patient/Observation.read";
    const scope =
      window._env_?.REACT_APP_EPIC_SCOPE ||
      process.env.REACT_APP_EPIC_SCOPE ||
      defaultScope;

    // Fallback: If no redirect URI is configured, construct it from the current location
    if (!redirectUri && typeof window !== "undefined") {
      redirectUri = window.location.origin + window.location.pathname;
      debugLog(
        "No redirect URI configured. Calculated fallback redirectUri:",
        redirectUri
      );
    }

    if (!clientId || !redirectUri) {
      debugError("Epic configuration missing: clientId or redirectUri not set");
      return null;
    }

    // Launch SMART client
    debugLog("Initializing SMART client", { clientId });
    const client = await launchSMART(clientId, redirectUri, scope);

    // Store client on window for use by other components
    if (client) {
      window.__formsflowSmartClient = client;
      debugLog(
        "SMART client initialized successfully",
        { patientId: client.patient?.id }
      );

      // Trade the completed Epic login for a real formsflow session - see
      // keycloakHandoff.js. This redirects the browser away on success, so
      // nothing after it on this page load will run in that case.
      completeKeycloakHandoff(client).catch((err) => {
        debugError("Keycloak handoff failed", err);
      });
    }

    return client;
  } catch (error) {
    debugError("Failed to initialize SMART client", error);
    return null;
  }
}

/**
 * Register EHR integrations on window object
 */
function registerEhrIntegrationsOnWindow() {
  if (typeof window === "undefined") return;

  window.formsflowEhr = window.formsflowEhr || {};
  window.formsflowEhr.sendConsentToEpic = sendConsentDocumentToEpic;
  window.formsflowEhr.launchSMART = launchSMART;
  window.formsflowEhr.getPatient = getPatient;
  window.formsflowEhr.fetchPatientData = fetchPatientData;
  window.formsflowEhr.initializeSMART = initializeSMART;
}

// Register EHR integrations when module loads
registerEhrIntegrationsOnWindow();

// Auto-initialize SMART client if isEHR flag is set
if (typeof window !== "undefined") {
  const urlParams = new URLSearchParams(window.location.search);
  const isEHR = urlParams.get("isEHR") === "true" || urlParams.get("isEHR") === "";
  
  if (isEHR && window.formsflowEhr?.initializeSMART) {
    // Use setTimeout to ensure window is fully initialized
    setTimeout(() => {
      window.formsflowEhr.initializeSMART().catch(err => {
        debugError("Auto-initialization of SMART client failed", err);
      });
    }, 0);
  }
}
