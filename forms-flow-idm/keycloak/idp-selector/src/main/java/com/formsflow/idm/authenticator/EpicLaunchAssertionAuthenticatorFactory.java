package com.formsflow.idm.authenticator;

import static org.keycloak.provider.ProviderConfigProperty.STRING_TYPE;

import java.util.Arrays;
import java.util.List;

import org.keycloak.authentication.Authenticator;
import org.keycloak.authentication.AuthenticatorFactory;
import org.keycloak.models.AuthenticationExecutionModel;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.provider.ProviderConfigProperty;

public class EpicLaunchAssertionAuthenticatorFactory implements AuthenticatorFactory {

	public static final String ID = "epic-launch-assertion-authenticator";

	static final String JWKS_URL = "jwksUrl";
	static final String REALM_ROLE = "realmRole";

	private static final Authenticator AUTHENTICATOR_INSTANCE = new EpicLaunchAssertionAuthenticator();

	@Override
	public Authenticator create(KeycloakSession keycloakSession) {
		return AUTHENTICATOR_INSTANCE;
	}

	@Override
	public String getDisplayType() {
		return "Epic Launch Assertion";
	}

	@Override
	public boolean isConfigurable() {
		return true;
	}

	@Override
	public AuthenticationExecutionModel.Requirement[] getRequirementChoices() {
		return new AuthenticationExecutionModel.Requirement[] { AuthenticationExecutionModel.Requirement.REQUIRED };
	}

	@Override
	public boolean isUserSetupAllowed() {
		return false;
	}

	@Override
	public String getHelpText() {
		return "formsflow.ai addon: verifies an ehr_connectors-issued launch assertion (proving a "
				+ "completed, verified Epic EHR-launch) and JIT-logs in a credential-less patient user - "
				+ "no username/password form is ever shown.";
	}

	@Override
	public List<ProviderConfigProperty> getConfigProperties() {
		ProviderConfigProperty jwksUrl = new ProviderConfigProperty();
		jwksUrl.setType(STRING_TYPE);
		jwksUrl.setName(JWKS_URL);
		jwksUrl.setLabel("ehr_connectors JWKS URL");
		jwksUrl.setHelpText("URL serving the JWKS that verifies the launch-assertion signature "
				+ "(ehr_connectors' jwks_server.py, e.g. https://.../.well-known/jwks.json)");

		ProviderConfigProperty realmRole = new ProviderConfigProperty();
		realmRole.setType(STRING_TYPE);
		realmRole.setName(REALM_ROLE);
		realmRole.setLabel("Realm role to grant");
		realmRole.setHelpText("Realm role assigned to JIT-provisioned Epic patient users (default: epic-patient)");

		return Arrays.asList(jwksUrl, realmRole);
	}

	@Override
	public String getReferenceCategory() {
		return null;
	}

	@Override
	public void init(org.keycloak.Config.Scope scope) {
	}

	@Override
	public void postInit(KeycloakSessionFactory keycloakSessionFactory) {
	}

	@Override
	public void close() {
	}

	@Override
	public String getId() {
		return ID;
	}
}
