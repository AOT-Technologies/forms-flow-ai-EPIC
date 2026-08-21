package com.formsflow.idm.authenticator;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.PublicKey;
import java.security.Signature;
import java.time.Duration;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import org.keycloak.authentication.AuthenticationFlowContext;
import org.keycloak.authentication.AuthenticationFlowError;
import org.keycloak.authentication.Authenticator;
import org.keycloak.jose.jwk.JWK;
import org.keycloak.jose.jwk.JWKParser;
import org.keycloak.jose.jws.JWSInput;
import org.keycloak.models.AuthenticatorConfigModel;
import org.keycloak.models.ClientModel;
import org.keycloak.models.GroupModel;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.models.RoleModel;
import org.keycloak.models.SingleUseObjectProvider;
import org.keycloak.models.UserModel;
import org.keycloak.models.UserSessionModel;
import org.keycloak.services.managers.AuthenticationManager;
import org.keycloak.util.JsonSerialization;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Verifies the `epic_assertion` JWT that ehr_connectors mints (see its
 * /epic/launch/exchange endpoint and LaunchService) after independently
 * verifying an Epic-issued id_token from the interactive patient/provider
 * EHR-launch flow.
 *
 * On success this JIT-provisions (or reuses) a credential-less Keycloak
 * user for the patient and logs them straight in - no form is ever
 * rendered here, the same way ConfigurableIdpAuthenticator's action()
 * calls context.success() without further prompting.
 *
 * This never touches EPIC_PRIVATE_KEY/EPIC_KID or anything Epic-facing -
 * it only verifies a signature ehr_connectors made with its own, separate
 * launch-assertion key, fetched from ehr_connectors' own JWKS endpoint.
 */
public class EpicLaunchAssertionAuthenticator implements Authenticator {

	private static final Logger logger = LoggerFactory.getLogger(EpicLaunchAssertionAuthenticator.class);

	private static final String EXPECTED_AUDIENCE = "formsflow-keycloak";
	private static final String USERNAME_PREFIX = "epic_";
	private static final long JWKS_CACHE_TTL_MILLIS = 10 * 60 * 1000L;
	private static final long REPLAY_GUARD_TTL_SECONDS = 120L; // comfortably covers the assertion's own 60s exp

	// Authenticator instances are shared/reused across requests (see the
	// Factory's static singleton), so this cache must stay thread-safe.
	private final AtomicReference<CachedJwks> jwksCache = new AtomicReference<>();

	private static final class CachedJwks {
		final Map<String, JWK> keysByKid;
		final long fetchedAt;

		CachedJwks(Map<String, JWK> keysByKid, long fetchedAt) {
			this.keysByKid = keysByKid;
			this.fetchedAt = fetchedAt;
		}
	}

	@Override
	public void authenticate(AuthenticationFlowContext context) {
		String assertion = context.getUriInfo().getQueryParameters().getFirst("epic_assertion");
		if (assertion == null || assertion.isBlank()) {
			logger.warn("EpicLaunchAssertionAuthenticator: no epic_assertion query parameter present");
			context.failure(AuthenticationFlowError.INVALID_CREDENTIALS);
			return;
		}

		AuthenticatorConfigModel configModel = context.getAuthenticatorConfig();
		String jwksUrl = configModel != null
				? configModel.getConfig().get(EpicLaunchAssertionAuthenticatorFactory.JWKS_URL)
				: null;
		String realmRoleName = configModel != null
				? configModel.getConfig().getOrDefault(EpicLaunchAssertionAuthenticatorFactory.REALM_ROLE, "epic-patient")
				: "epic-patient";

		if (jwksUrl == null || jwksUrl.isBlank()) {
			logger.error("EpicLaunchAssertionAuthenticator is not configured with a JWKS URL");
			context.failure(AuthenticationFlowError.INTERNAL_ERROR);
			return;
		}

		try {
			Map<String, Object> claims = verifyAndDecode(assertion, jwksUrl);

			String jti = (String) claims.get("jti");
			if (jti == null || jti.isBlank()) {
				throw new SecurityException("assertion is missing jti");
			}
			if (!claimUnusedAndMarkSeen(context.getSession(), jti)) {
				throw new SecurityException("assertion has already been used (possible replay)");
			}

			String audience = (String) claims.get("aud");
			if (!EXPECTED_AUDIENCE.equals(audience)) {
				throw new SecurityException("unexpected aud claim: " + audience);
			}

			Object expClaim = claims.get("exp");
			long exp = expClaim instanceof Number ? ((Number) expClaim).longValue() : 0L;
			if (exp <= System.currentTimeMillis() / 1000L) {
				throw new SecurityException("assertion has expired");
			}

			String patientId = (String) claims.get("patientId");
			if (patientId == null || patientId.isBlank()) {
				throw new SecurityException("assertion is missing patientId");
			}
			String fhirUser = (String) claims.get("fhirUser");

			// Keycloak's own AuthenticationProcessor.attachSession() runs after
			// this method returns and throws differentUserAuthenticated if the
			// browser's existing SSO session cookie names a different user than
			// the one we're about to set - regardless of prompt=login on the
			// auth request (that only forces the login *flow* to re-run, it
			// doesn't touch this later check). A stale staff login, or a
			// previous patient's session in the same browser, would otherwise
			// surface as a generic "Unexpected error" page. Detach it first.
			detachConflictingSession(context, USERNAME_PREFIX + patientId);

			UserModel user = findOrCreatePatientUser(context, patientId, fhirUser, realmRoleName);
			context.setUser(user);
			context.success();
		} catch (Exception e) {
			logger.warn("EpicLaunchAssertionAuthenticator: rejecting assertion - {}", e.getMessage());
			context.failure(AuthenticationFlowError.INVALID_CREDENTIALS);
		}
	}

	/**
	 * Verifies the assertion's RS256 signature against ehr_connectors' JWKS
	 * (matched by `kid`) and returns its decoded claims. Throws on any
	 * failure - callers must treat that as an outright rejection.
	 */
	private Map<String, Object> verifyAndDecode(String assertion, String jwksUrl) throws Exception {
		JWSInput jwsInput = new JWSInput(assertion);
		String kid = jwsInput.getHeader().getKeyId();
		if (kid == null) {
			throw new SecurityException("assertion header is missing kid");
		}

		PublicKey publicKey = getPublicKey(jwksUrl, kid);
		if (publicKey == null) {
			throw new SecurityException("no matching key found in JWKS for kid=" + kid);
		}

		Signature signature = Signature.getInstance("SHA256withRSA");
		signature.initVerify(publicKey);
		signature.update(jwsInput.getEncodedSignatureInput().getBytes(StandardCharsets.UTF_8));
		if (!signature.verify(jwsInput.getSignature())) {
			throw new SecurityException("signature verification failed");
		}

		return jwsInput.readJsonContent(Map.class);
	}

	private PublicKey getPublicKey(String jwksUrl, String kid) throws IOException, InterruptedException {
		CachedJwks cached = jwksCache.get();
		long now = System.currentTimeMillis();
		if (cached == null || (now - cached.fetchedAt) > JWKS_CACHE_TTL_MILLIS || !cached.keysByKid.containsKey(kid)) {
			// Also covers key rotation: an unrecognized kid forces a re-fetch
			// rather than waiting out the full TTL.
			cached = fetchJwks(jwksUrl);
			jwksCache.set(cached);
		}

		JWK jwk = cached.keysByKid.get(kid);
		return jwk == null ? null : JWKParser.create(jwk).toPublicKey();
	}

	@SuppressWarnings("unchecked")
	private CachedJwks fetchJwks(String jwksUrl) throws IOException, InterruptedException {
		HttpClient httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
		HttpRequest request = HttpRequest.newBuilder(URI.create(jwksUrl)).GET().build();
		HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
		if (response.statusCode() != 200) {
			throw new IOException("Failed to fetch JWKS from " + jwksUrl + ": HTTP " + response.statusCode());
		}

		Map<String, Object> parsed = JsonSerialization.readValue(response.body(), Map.class);
		Object keysObj = parsed.get("keys");
		Map<String, JWK> byKid = new HashMap<>();
		if (keysObj instanceof Iterable) {
			for (Object keyObj : (Iterable<?>) keysObj) {
				String keyJson = JsonSerialization.writeValueAsString(keyObj);
				JWK jwk = JsonSerialization.readValue(keyJson, JWK.class);
				if (jwk.getKeyId() != null) {
					byKid.put(jwk.getKeyId(), jwk);
				}
			}
		}
		return new CachedJwks(byKid, System.currentTimeMillis());
	}

	/**
	 * Uses Keycloak's built-in single-use-object store (the same SPI backing
	 * one-time action tokens), so replay protection works out of the box
	 * across a multi-node cluster with no new infrastructure to run.
	 *
	 * @return false if this jti was already claimed (i.e. a replay)
	 */
	private boolean claimUnusedAndMarkSeen(KeycloakSession session, String jti) {
		SingleUseObjectProvider store = session.getProvider(SingleUseObjectProvider.class);
		if (store.get(jti) != null) {
			return false;
		}
		store.put(jti, REPLAY_GUARD_TTL_SECONDS, Collections.emptyMap());
		return true;
	}

	/**
	 * If this browser already carries a valid Keycloak SSO session (identity
	 * cookie) for a DIFFERENT user than the one we're about to establish,
	 * log that session out server-side and expire the cookie - otherwise
	 * Keycloak's own attachSession() rejects this login outright rather than
	 * silently switching identities out from under an existing session.
	 * A no-op if there's no existing session, or it already is this user.
	 */
	private void detachConflictingSession(AuthenticationFlowContext context, String expectedUsername) {
		KeycloakSession session = context.getSession();
		RealmModel realm = context.getRealm();

		AuthenticationManager.AuthResult existing = AuthenticationManager.authenticateIdentityCookie(session, realm, true);
		if (existing == null) {
			return;
		}
		UserModel existingUser = existing.getUser();
		if (existingUser != null && expectedUsername.equals(existingUser.getUsername())) {
			return;
		}

		logger.info(
				"EpicLaunchAssertionAuthenticator: detaching existing session for '{}' before establishing '{}'",
				existingUser != null ? existingUser.getUsername() : "unknown", expectedUsername);
		UserSessionModel existingSession = existing.getSession();
		if (existingSession != null) {
			AuthenticationManager.backchannelLogout(session, existingSession, true);
		}
		AuthenticationManager.expireIdentityCookie(session);
	}

	private UserModel findOrCreatePatientUser(AuthenticationFlowContext context, String patientId, String fhirUser,
			String realmRoleName) {
		KeycloakSession session = context.getSession();
		RealmModel realm = context.getRealm();
		String username = USERNAME_PREFIX + patientId;

		UserModel user = session.users().getUserByUsername(realm, username);
		if (user == null) {
			try {
				user = session.users().addUser(realm, username);
			} catch (Exception e) {
				// Handles the double-launch race: two near-simultaneous logins
				// for the same patient both see "no user" and both try to
				// create one. Whichever loses the race falls back to the
				// user the winner just created, instead of failing outright.
				user = session.users().getUserByUsername(realm, username);
				if (user == null) {
					throw new RuntimeException("Failed to find-or-create user " + username, e);
				}
			}
			user.setEnabled(true);
			// This realm's User Profile marks email/firstName/lastName as
			// required - without these, Keycloak forces an "Update Account
			// Information" prompt after login regardless of what this
			// authenticator does, defeating the whole point of a silent,
			// password-less flow. Placeholder values, not real patient data.
			user.setEmail(username + "@epic-patient.formsflow.local");
			user.setEmailVerified(true);
			user.setFirstName("Epic");
			user.setLastName("Patient");
			// No credential is ever set on this account - it's reachable only
			// via a verified Epic launch assertion, never a password.
			RoleModel role = realm.getRole(realmRoleName);
			if (role != null) {
				user.grantRole(role);
			} else {
				logger.warn("Realm role '{}' does not exist - user {} was created without it", realmRoleName, username);
			}

			// The realm role above is only for our own future gating (e.g.
			// showing/hiding Epic-only forms) - it means nothing to formsflow's
			// own backend, which maps a fixed set of forms-flow-web CLIENT
			// roles to Form.io role ids (see forms-flow-api's
			// get_role_ids_from_user_groups()). Without one of those, the
			// backend's /formio/roles call has nothing to map and errors out,
			// which is what was leaving the form route stuck on a spinner.
			grantClientRoleIfExists(realm, user, "forms-flow-web", "create_submissions", username);
			grantClientRoleIfExists(realm, user, "forms-flow-web", "view_submissions", username);
			// EHR-launched patients also need the Tasks page to work, unlike a
			// normal unprivileged client user - grant task access too so
			// PrivateRoute's ReviewerRoute gate (viewTasks || manageTasks ||
			// viewDashboards) doesn't show Access Denied for this flow.
			grantClientRoleIfExists(realm, user, "forms-flow-web", "view_tasks", username);
			grantClientRoleIfExists(realm, user, "forms-flow-web", "manage_tasks", username);
			// view_tasks/manage_tasks only satisfy the Tasks *page's* own
			// route gate - the actual task list is populated via a separate
			// call to forms-flow-api's GET /filter/user, which is gated by
			// its own @auth.has_one_of_roles([MANAGE_ALL_FILTERS,
			// VIEW_FILTERS]) decorator. Without this, that call 401s for
			// every Epic patient, the filter list never loads, and the
			// Tasks page silently falls back to an empty/default state -
			// independent of anything on the BPMN or Camunda side.
			grantClientRoleIfExists(realm, user, "forms-flow-web", "view_filters", username);
		}

		// Re-established per user request after removing it during the task-
		// visibility investigation: kept as a plain group membership only -
		// nothing in the BPMN references it as a candidateGroups value, so it
		// has no bearing on task assignment/visibility (that's driven purely
		// by assignee, via the orQueries filter fix) or on the SSO handoff.
		joinGroupIfExists(session, realm, user, "epic-patient", username);

		user.setSingleAttribute("patientId", patientId);
		if (fhirUser != null) {
			user.setSingleAttribute("fhirUser", fhirUser);
		}

		return user;
	}

	/**
	 * Joins the user to a Keycloak Group matched by simple name (assumed
	 * unique within the realm). No-ops if the group doesn't exist yet or the
	 * user is already a member.
	 */
	private void joinGroupIfExists(KeycloakSession session, RealmModel realm, UserModel user, String groupName,
			String username) {
		GroupModel group = session.groups().getGroupsStream(realm)
				.filter(g -> groupName.equals(g.getName()))
				.findFirst()
				.orElse(null);
		if (group == null) {
			logger.warn("Keycloak group '{}' does not exist - user {} was not added to it", groupName, username);
			return;
		}
		if (!user.isMemberOf(group)) {
			user.joinGroup(group);
		}
	}

	private void grantClientRoleIfExists(RealmModel realm, UserModel user, String clientId, String roleName,
			String username) {
		ClientModel client = realm.getClientByClientId(clientId);
		if (client == null) {
			logger.warn("Client '{}' does not exist - cannot grant role '{}' to user {}", clientId, roleName, username);
			return;
		}
		RoleModel role = client.getRole(roleName);
		if (role == null) {
			logger.warn("Client role '{}' on client '{}' does not exist - user {} was created without it", roleName,
					clientId, username);
			return;
		}
		user.grantRole(role);
	}

	@Override
	public void action(AuthenticationFlowContext context) {
		// authenticate() never renders a form, so there is no user-submitted
		// action to handle here.
	}

	@Override
	public boolean requiresUser() {
		return false;
	}

	@Override
	public boolean configuredFor(KeycloakSession session, RealmModel realm, UserModel user) {
		return true;
	}

	@Override
	public void setRequiredActions(KeycloakSession session, RealmModel realm, UserModel user) {
	}

	@Override
	public void close() {
	}
}
