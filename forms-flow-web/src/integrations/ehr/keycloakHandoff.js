/**
 * Hands an EHR-launched SMART session off to Keycloak, so a patient who
 * launched from Epic ends up with a real formsflow session - without ever
 * seeing a Keycloak login screen or holding a password.
 *
 * This deliberately does NOT use keycloak-js's own login() to start the
 * redirect: keycloak-js has no public option to attach the custom
 * `epic_assertion` param its auth request needs, so the PKCE pair here is
 * generated and tracked by hand (same code_verifier/code_challenge/state
 * mechanics keycloak-js would do internally) and completed by a small
 * static callback page (epic-callback.html) rather than keycloak-js's own
 * redirect-detection, to avoid colliding with the SMART flow's own `code`/
 * `state` handling in service.js on the same page.
 */

import { getKeycloakHandoffConfig, debugError, debugLog } from './config';

const HANDOFF_DONE_KEY = 'epic_keycloak_handoff_patient';
const PKCE_VERIFIER_KEY = 'epic_kc_code_verifier';
const KC_STATE_KEY = 'epic_kc_state';
const RETURN_TO_KEY = 'epic_kc_return_to';
// Read by PrivateRoute.jsx to know a non-patient (provider/etc) launch has
// been deliberately left alone, so it can fall back to the normal Keycloak
// login screen instead of waiting forever for a handoff that will never come.
export const HANDOFF_NOT_APPLICABLE_KEY = 'epic_handoff_not_applicable';

function base64UrlEncode(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  bytes.forEach((b) => { binary += String.fromCharCode(b); });
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function randomString(byteLength = 48) {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes.buffer);
}

async function sha256Base64Url(input) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return base64UrlEncode(digest);
}

/**
 * Call after a SMART client successfully finishes its Epic OAuth exchange.
 * No-ops (returns false) if openid/fhirUser weren't requested/granted, if
 * the handoff isn't configured, or if it already ran this session for this
 * patient - otherwise redirects the browser to Keycloak and never returns.
 *
 * @param {Object} client - the fhirclient instance returned by launchSMART()
 */
export async function completeKeycloakHandoff(client) {
  try {
    // client.user.resourceType comes straight from the id_token's fhirUser
    // claim ("Practitioner"/"Patient"/"RelatedPerson") - a Provider EHR
    // launch still carries a `patient` launch context (the chart the doctor
    // had open), so patientId alone can't tell a doctor's launch apart from
    // a patient's. Only patients get JIT-provisioned into the epic_<id>
    // identity here; anyone else falls through to the normal Keycloak
    // username/password login this page would otherwise show.
    const userType = client?.user?.resourceType || null;
    if (userType && userType !== 'Patient') {
      debugLog(`Keycloak handoff skipped: launch fhirUser is a ${userType}, not a Patient`);
      sessionStorage.setItem(HANDOFF_NOT_APPLICABLE_KEY, 'true');
      return false;
    }

    const tokenResponse = client?.state?.tokenResponse || {};
    const idToken = tokenResponse.id_token;
    const accessToken = tokenResponse.access_token;
    const iss = client?.state?.serverUrl;
    const patientId = client?.patient?.id || tokenResponse.patient;

    if (!idToken || !accessToken || !iss || !patientId) {
      debugLog(
        'Keycloak handoff skipped: missing id_token/access_token/iss/patient - ' +
        'was "openid fhirUser" included in the SMART scope and granted by Epic?'
      );
      return false;
    }

    if (sessionStorage.getItem(HANDOFF_DONE_KEY) === patientId) {
      debugLog('Keycloak handoff already completed this session for this patient');
      return false;
    }

    const { ehrConnectorUrl, keycloakRealmUrl, clientId } = getKeycloakHandoffConfig();
    if (!ehrConnectorUrl || !keycloakRealmUrl) {
      debugError(
        'Keycloak handoff not configured - set REACT_APP_EHR_CONNECTOR_URL and ' +
        'REACT_APP_KEYCLOAK_EPIC_REALM_URL'
      );
      return false;
    }

    const exchangeResponse = await fetch(`${ehrConnectorUrl}/epic/launch/exchange`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id_token: idToken,
        access_token: accessToken,
        iss,
        patient_id: patientId,
      }),
    });

    if (!exchangeResponse.ok) {
      const errorText = await exchangeResponse.text();
      throw new Error(
        `Launch exchange rejected (HTTP ${exchangeResponse.status}): ${errorText}`
      );
    }

    const { assertion } = await exchangeResponse.json();
    if (!assertion) {
      throw new Error('Launch exchange response did not include an assertion');
    }

    const codeVerifier = randomString();
    const codeChallenge = await sha256Base64Url(codeVerifier);
    const state = randomString(24);

    sessionStorage.setItem(PKCE_VERIFIER_KEY, codeVerifier);
    sessionStorage.setItem(KC_STATE_KEY, state);
    sessionStorage.setItem(RETURN_TO_KEY, window.location.href);
    sessionStorage.setItem(HANDOFF_DONE_KEY, patientId);

    const callbackUri = `${window.location.origin}/epic-callback.html`;
    const authUrl = new URL(`${keycloakRealmUrl.replace(/\/+$/, '')}/protocol/openid-connect/auth`);
    authUrl.searchParams.set('client_id', clientId);
    authUrl.searchParams.set('response_type', 'code');
    authUrl.searchParams.set('scope', 'openid');
    authUrl.searchParams.set('redirect_uri', callbackUri);
    authUrl.searchParams.set('state', state);
    authUrl.searchParams.set('code_challenge', codeChallenge);
    authUrl.searchParams.set('code_challenge_method', 'S256');
    // prompt=login only forces Keycloak to re-run the login *flow* fresh -
    // it does NOT stop the final attachSession() step from comparing against
    // whatever SSO session cookie is already sitting in this browser (staff
    // login, or a previous patient's launch). If that cookie names a
    // different user, Keycloak throws differentUserAuthenticated regardless
    // of prompt (confirmed against a live stack trace). A client-side
    // logout-first redirect can't fix this invisibly either: Keycloak's own
    // logout endpoint requires an id_token_hint (which we don't have for
    // whatever session happens to already be in this browser) or it shows a
    // "Do you want to log out?" confirmation page - so the real fix is
    // server-side, in EpicLaunchAssertionAuthenticator itself, which detaches
    // any conflicting session before establishing the patient's.
    authUrl.searchParams.set('prompt', 'login');
    // Consumed server-side by EpicLaunchAssertionAuthenticator - proves this
    // login request is backed by a verified Epic launch, without a password.
    authUrl.searchParams.set('epic_assertion', assertion);

    window.location.href = authUrl.toString();
    return true;
  } catch (error) {
    debugError('Keycloak handoff failed:', error);
    return false;
  }
}
