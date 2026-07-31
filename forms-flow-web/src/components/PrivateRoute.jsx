/* eslint-disable no-unused-vars */
import React, { useEffect, Suspense, useMemo, useCallback } from "react";
import { Route, Switch, Redirect, useParams } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";
import {
  BASE_ROUTE,
  getRoute,
  DRAFT_ENABLED,
  MULTITENANCY_ENABLED,
  KEYCLOAK_AUTH_URL,
  Keycloak_Client,
  KEYCLOAK_REALM,
  ENABLE_APPLICATIONS_MODULE,
  ENABLE_DASHBOARDS_MODULE,
  ENABLE_FORMS_MODULE,
  ENABLE_PROCESSES_MODULE,
  ENABLE_TASKS_MODULE,
  LANGUAGE,
} from "../constants/constants";
import { KeycloakService, StorageService } from "@formsflow/service";
import Keycloak from "keycloak-js";
import { getKeycloakHandoffConfig } from "../integrations/ehr/config";
import { HANDOFF_NOT_APPLICABLE_KEY } from "../integrations/ehr/keycloakHandoff";
import {
  setUserAuth,
  setUserRole,
  setUserToken,
  setUserDetails,
} from "../actions/bpmActions";
import { setLanguage } from "../actions/languageSetAction";

import Loading from "../containers/Loading";
import NotFound from "./NotFound";
import {
  setTenantFromId,
  validateTenant,
} from "../apiManager/services/tenantServices";

// Lazy imports is having issues with micro-front-end build

import SubmitFormRoutes from "./../routes/Submit/Forms";
import DesignFormRoutes from "./../routes/Design/Forms";
import ServiceFlow from "./ServiceFlow";
import DashboardPage from "./Dashboard";
import InsightsPage from "./Insights";
import Application from "./Application";
import DesignProcessRoutes from "./../routes/Design/Process";
import Drafts from "./Draft";
import {
  BPM_API_URL_WITH_VERSION,
  WEB_BASE_URL,
  WEB_BASE_CUSTOM_URL,
  CUSTOM_SUBMISSION_URL,
} from "../apiManager/endpoints/config";
import { AppConfig } from "../config";
import { getFormioRoleIds } from "../apiManager/services/userservices";
import AccessDenied from "./AccessDenied";
import useUserRoles from "../constants/permissions";
import PropTypes from "prop-types";
export const kcServiceInstance = (tenantId = null) => {
  return KeycloakService.getInstance(
    KEYCLOAK_AUTH_URL,
    KEYCLOAK_REALM,
    tenantId ? `${tenantId}-${Keycloak_Client}` : Keycloak_Client
  );
};

const EPIC_ACCESS_TOKEN_KEY = "epic_kc_access_token";
const EPIC_REFRESH_TOKEN_KEY = "epic_kc_refresh_token";
const EPIC_ID_TOKEN_KEY = "epic_kc_id_token";

/**
 * Adopts a completed EHR-launch Keycloak session (tokens stashed by
 * epic-callback.html) as a real, authenticated session for this app -
 * without going through KeycloakService.initKeycloak(), which would call
 * its own keycloak-js .init() against the CURRENT page URL. On an
 * EHR-launched page that URL still carries the SMART flow's own leftover
 * `code`/`state` (from Epic/the sandbox), and keycloak-js has no way to
 * tell that isn't its own OAuth callback - it sends it to Keycloak's token
 * endpoint, gets rejected, and the whole init() rejects with no fallback.
 *
 * Returns null (no-op) if no completed handoff is waiting in sessionStorage
 * - the caller should then skip initKeycloak() entirely rather than risk
 * that same collision, and simply wait for the next page load (post-handoff)
 * to try again.
 */
const adoptEpicSession = async () => {
  const accessToken = sessionStorage.getItem(EPIC_ACCESS_TOKEN_KEY);
  if (!accessToken) {
    return null;
  }

  const refreshToken = sessionStorage.getItem(EPIC_REFRESH_TOKEN_KEY);
  const idToken = sessionStorage.getItem(EPIC_ID_TOKEN_KEY);
  sessionStorage.removeItem(EPIC_ACCESS_TOKEN_KEY);
  sessionStorage.removeItem(EPIC_REFRESH_TOKEN_KEY);
  sessionStorage.removeItem(EPIC_ID_TOKEN_KEY);

  const { clientId } = getKeycloakHandoffConfig();
  const kc = new Keycloak({
    url: KEYCLOAK_AUTH_URL,
    realm: KEYCLOAK_REALM,
    clientId,
  });

  let authenticated;
  try {
    authenticated = await kc.init({
      token: accessToken,
      refreshToken,
      idToken,
      pkceMethod: "S256",
      checkLoginIframe: false,
    });
  } catch (e) {
    console.error("Failed to adopt Epic-launched Keycloak session", e);
    return null;
  }
  if (!authenticated) {
    return null;
  }

  // Route access (permissions.js) is gated on the flat client-role claim
  // (create_submissions, view_tasks, etc.) that the realm's custom mapper
  // writes as `role` - not realm_access.roles, which only ever holds
  // realm-level roles like epic-patient/offline_access and would make every
  // ReviewerRoute/ClientRoute check fail regardless of granted client roles.
  const roles = kc.tokenParsed?.roles || kc.tokenParsed?.role || kc.tokenParsed?.client_roles || [];
  StorageService.save(StorageService.User.USER_ROLE, JSON.stringify(roles));
  StorageService.save(StorageService.User.AUTH_TOKEN, kc.token);

  const userData = await kc.loadUserInfo().catch(() => kc.tokenParsed);
  StorageService.save(StorageService.User.USER_DETAILS, JSON.stringify(userData));

  return {
    getToken: () => kc.token,
    isAuthenticated: () => true,
    getUserData: () => userData,
    userData,
    userLogout: () => kc.logout(),
    tokenParsed: kc.tokenParsed,
  };
};

const setApiBaseUrlToLocalStorage = () => {
  localStorage.setItem("bpmApiUrl", BPM_API_URL_WITH_VERSION);
  localStorage.setItem("formioApiUrl", AppConfig.projectUrl);
  localStorage.setItem("formsflow.ai.url", window.location.origin);
  localStorage.setItem("formsflow.ai.api.url", WEB_BASE_URL);
  localStorage.setItem("customApiUrl", WEB_BASE_CUSTOM_URL);
  localStorage.setItem("customSubmissionUrl", CUSTOM_SUBMISSION_URL);
};

const PrivateRoute = React.memo((props) => {
  const { publish, subscribe, getKcInstance } = props;
  const dispatch = useDispatch();
  const isAuth = useSelector((state) => state.user.isAuthenticated);
  const userRoles = useSelector((state) => state.user.roles || []);
  const { tenantId } = useParams();
  const selectedLanguage = useSelector((state) => state.user.lang);
  const tenant = useSelector((state) => state.tenants);
  const [authError, setAuthError] = React.useState(false);
  const [kcInstance, setKcInstance] = React.useState(getKcInstance());
  const [tenantValid, setTenantValid] = React.useState(true);
  const [formioTokenSet, setFormioTokenSet] = React.useState(false);
  const ROUTE_TO = getRoute(tenantId);
  const {
    createDesigns,
    createSubmissions,
    viewDesigns,
    viewSubmissions,
    viewTasks,
    manageTasks,
    viewDashboards,
    manageDashBoardAuthorizations,
    manageRoles,
    manageUsers,
    manageLinks,
    analyzeSubmissionView,
    analyzeMetricsView,
    manageAdvancedWorkFlows,
    reviewerViewHistory,
    analyzeSubmissionsViewHistory,
  } = useUserRoles();

  const BASE_ROUTE_PATH = (() => {
    if (viewTasks || manageTasks) return ROUTE_TO.TASK;
    if (createSubmissions || viewSubmissions) return ROUTE_TO.FORM;
    if (createDesigns || viewDesigns) return ROUTE_TO.FORMFLOW;
    if (manageAdvancedWorkFlows) return ROUTE_TO.SUBFLOW;
    if (
      manageDashBoardAuthorizations ||
      manageRoles ||
      manageUsers ||
      manageLinks
    )
      return ROUTE_TO.ADMIN;
    if (analyzeSubmissionView) return ROUTE_TO.ANALYZESUBMISSIONS;
    if (analyzeMetricsView) return ROUTE_TO.METRICS;
    if (viewDashboards) return ROUTE_TO.DASHBOARDS;
    return ROUTE_TO.NOTFOUND;
  })();

  const authenticate = (instance, store) => {
    setKcInstance(instance);
    store.dispatch(
      setUserRole(JSON.parse(StorageService.get(StorageService.User.USER_ROLE)))
    );
    dispatch(setUserAuth(instance.isAuthenticated()));
    store.dispatch(setUserToken(instance.getToken()));
    // Set Cammunda/Formio Base URL
    setApiBaseUrlToLocalStorage();

    // Get formio roles
    store.dispatch(
      getFormioRoleIds((err) => {
        if (err) {
          console.error(err);
          setFormioTokenSet(false);
        } else {
          store.dispatch(
            setUserDetails(
              JSON.parse(StorageService.get(StorageService.User.USER_DETAILS))
            )
          );
          setFormioTokenSet(true);
        }
      })
    );
  };

  const keycloakInitialize = useCallback(() => {
    let instance = tenantId ? kcServiceInstance(tenantId) : kcServiceInstance();
    if (props.store) {
      if (kcInstance) {
        authenticate(kcInstance, props.store);
      } else {
        const urlParams = new URLSearchParams(window.location.search);
        const isEHR = urlParams.get("isEHR") === "true" || urlParams.get("isEHR") === "";

        const fallBackToNormalLogin = () => {
          // Don't call this for the leftover code/state still on the URL
          // mid patient-handoff - see adoptEpicSession()'s doc comment for
          // why that collides. By the time we get here, either the launch
          // was determined not to be a patient at all, or we've waited long
          // enough that there's nothing left to adopt.
          instance.initKeycloak((authenticated) => {
            if (!authenticated) {
              setAuthError(true);
            } else {
              publish("FF_AUTH", instance);
              authenticate(instance, props.store);
            }
          });
        };

        if (isEHR) {
          // A Provider (or other non-patient) EHR launch deliberately skips
          // the Epic->Keycloak handoff (see keycloakHandoff.js) and never
          // redirects anywhere - so this can't just wait for a handoff that
          // is never coming. Poll briefly for either a completed patient
          // handoff or that explicit skip signal, then fall back to the
          // normal login screen either way once time's up.
          const ADOPT_RETRY_MS = 500;
          const ADOPT_MAX_ATTEMPTS = 10;
          const tryAdopt = (attemptsLeft) => {
            adoptEpicSession().then((epicInstance) => {
              if (epicInstance) {
                publish("FF_AUTH", epicInstance);
                authenticate(epicInstance, props.store);
                return;
              }
              const notApplicable = sessionStorage.getItem(HANDOFF_NOT_APPLICABLE_KEY) === "true";
              if (notApplicable) {
                // Non-patient (Provider, etc) EHR launch. instance.initKeycloak()
                // hardcodes onLoad:"check-sso" (see @formsflow/service), which
                // would silently adopt whatever Keycloak session already
                // happens to be sitting in this browser - a different
                // patient's, a stale staff session - rather than requiring
                // this user's own credentials. keycloak-js's own .login()
                // requires .init() to have already run at least once (it
                // throws reading internal endpoint state otherwise), so run
                // the existing check-sso init first, then force a real
                // username/password challenge in its callback regardless of
                // what check-sso silently found. Stripping isEHR from the
                // redirect URI means the return trip is an ordinary staff
                // visit, completed by the normal (non-EHR) path below exactly
                // as it already is today.
                const redirectUri = window.location.origin + window.location.pathname;
                instance.initKeycloak(() => {
                  instance.kc.login({ prompt: "login", redirectUri });
                });
              } else if (attemptsLeft <= 0) {
                fallBackToNormalLogin();
              } else {
                setTimeout(() => tryAdopt(attemptsLeft - 1), ADOPT_RETRY_MS);
              }
            });
          };
          tryAdopt(ADOPT_MAX_ATTEMPTS);
          return;
        }

        fallBackToNormalLogin();
      }
    }
  }, [props.store, kcInstance, tenantId]);

  useEffect(() => {
    if (tenantId && MULTITENANCY_ENABLED) {
      validateTenant(tenantId)
        .then((res) => {
          if (!res.data.tenantKeyExist) {
            setTenantValid(false);
          } else {
            setTenantValid(true);

            if (tenantId && props.store) {
              let currentTenant = sessionStorage.getItem("tenantKey");
              if (currentTenant && currentTenant !== tenantId) {
                sessionStorage.clear();
                localStorage.clear();
              }
              sessionStorage.setItem("tenantKey", tenantId);
              dispatch(setTenantFromId(tenantId));
              keycloakInitialize();
            }
          }
        })
        .catch((err) => {
          console.error("Error validating tenant", err);
          setTenantValid(false);
        });
    } else {
      keycloakInitialize();
    }
  }, [tenantId, props.store, dispatch]);

  useEffect(() => {
    if (kcInstance) {
      const lang =
        kcInstance?.userData?.locale ||
        tenant?.tenantData?.details?.locale ||
        selectedLanguage ||
        LANGUAGE;
      dispatch(setLanguage(lang));
    }
    else {   
        dispatch(setLanguage(localStorage.getItem('lang') ?? 'en'));    
    }
  }, [kcInstance, tenant?.tenantData]);

  // Add effect to check for formio token on mount and when isAuth changes
  useEffect(() => {
    if (isAuth) {
      const formioToken = localStorage.getItem("formioToken");
      setFormioTokenSet(!!formioToken);
    }
  }, [isAuth]);

  const DesignerRoute = useMemo(
    () =>
      ({ component: Component, ...rest }) =>
        (
          <Route
            {...rest}
            render={(props) =>
              createDesigns || viewDesigns || manageAdvancedWorkFlows ? (
                <Component {...props} />
              ) : (
                <AccessDenied userRoles={userRoles} />
              )
            }
          />
        ),
    [userRoles]
  );

  const AnalyzeRoute = useMemo(
    () =>
      ({ component: Component, ...rest }) =>
        (
          <Route
            {...rest}
            render={(props) =>
              viewDashboards || analyzeSubmissionView || analyzeMetricsView ? (
                <Component {...props} />
              ) : (
                <AccessDenied userRoles={userRoles} />
              )
            }
          />
        ),
    [userRoles]
  );

  const ReviewerRoute = useMemo(
    () =>
      ({ component: Component, ...rest }) =>
        (
          <Route
            {...rest}
            render={(props) =>
              viewTasks || manageTasks || viewDashboards ? (
                <Component {...props} />
              ) : (
                <AccessDenied userRoles={userRoles} />
              )
            }
          />
        ),
    [userRoles]
  );

  const ClientReviewerRoute = useMemo(
    () =>
      ({ component: Component, ...rest }) =>
        (
          <Route
            {...rest}
            render={(props) =>
              viewSubmissions || analyzeSubmissionView ? (
                <Component {...props} />
              ) : (
                <AccessDenied userRoles={userRoles} />
              )
            }
          />
        ),
    [userRoles]
  );

  const DraftRoute = useMemo(
    () =>
      ({ component: Component, ...rest }) =>
        (
          <Route
            {...rest}
            render={(props) =>
              DRAFT_ENABLED && viewSubmissions ? (
                <Component {...props} />
              ) : (
                <AccessDenied userRoles={userRoles} />
              )
            }
          />
        ),
    [userRoles]
  );

  const ClientRoute = useMemo(
    () =>
      ({ component: Component, ...rest }) =>
        (
          <Route
            {...rest}
            render={(props) =>
              createSubmissions || viewSubmissions ||  analyzeSubmissionsViewHistory ||
              reviewerViewHistory ? (
                <Component {...props} />
              ) : (
                <AccessDenied userRoles={userRoles} />
              )
            }
          />
        ),
    [userRoles]
  );

  ClientRoute.propTypes = {
    component: PropTypes.elementType.isRequired,
  };

  if (!tenantValid) {
    return <NotFound />;
  }

  return (
    <>
      {authError ? (
        <AccessDenied userRoles={userRoles} />
      ) : isAuth ? (
        <Suspense fallback={<Loading />}>
          <Switch>
            {ENABLE_FORMS_MODULE && formioTokenSet && (
              <ClientRoute path={ROUTE_TO.FORM} component={SubmitFormRoutes} />
            )}
            {ENABLE_FORMS_MODULE && !formioTokenSet && (
              <Route path={ROUTE_TO.FORM}>
                <Loading />
              </Route>
            )}
            {ENABLE_FORMS_MODULE && (
              <DesignerRoute
                path={ROUTE_TO.FORM_CREATE}
                component={DesignFormRoutes}
              />
            )}
            {ENABLE_FORMS_MODULE && (
              <DesignerRoute
                path={ROUTE_TO.FORMFLOW}
                component={DesignFormRoutes}
              />
            )}
            {ENABLE_APPLICATIONS_MODULE && (
              <DraftRoute path={ROUTE_TO.DRAFT} component={Drafts} />
            )}
            {ENABLE_APPLICATIONS_MODULE && (
              <ClientReviewerRoute
                path={ROUTE_TO.APPLICATION}
                component={Application}
              />
            )}
            {ENABLE_PROCESSES_MODULE  && (
              <DesignerRoute
                path={ROUTE_TO.SUBFLOW}
                component={DesignProcessRoutes}
              />
            )}
            {ENABLE_PROCESSES_MODULE  && (
              <DesignerRoute
                path={ROUTE_TO.DECISIONTABLE}
                component={DesignProcessRoutes}
              />
            )}

            {ENABLE_DASHBOARDS_MODULE && (
              <AnalyzeRoute path={ROUTE_TO.METRICS} component={DashboardPage} />
            )}
            {ENABLE_DASHBOARDS_MODULE && (
              <AnalyzeRoute
                path={ROUTE_TO.DASHBOARDS}
                component={InsightsPage}
              />
            )}

            {ENABLE_TASKS_MODULE && (
              <ReviewerRoute path={ROUTE_TO.TASK_OLD} component={ServiceFlow} />
            )}
           <Route exact path={ROUTE_TO.TASK} />
            <Route exact path={ROUTE_TO.ADMIN} />
            {/* * This route is used to redirect the user to the correct base route
             * based on their roles. If the user has no roles, they will be redirected
             * to the not found page.
             */}
            <Route exact path={ROUTE_TO.ANALYZESUBMISSIONS} />
            <Route exact path={BASE_ROUTE}>
              {userRoles.length && <Redirect to={BASE_ROUTE_PATH} />}
            </Route>
            <Route path={ROUTE_TO.NOTFOUND} exact={true} component={NotFound} />
            <Redirect from="*" to={ROUTE_TO.NOTFOUND} />
          </Switch>
        </Suspense>
      ) : (
        <Loading />
      )}
    </>
  );
});

export default PrivateRoute;
