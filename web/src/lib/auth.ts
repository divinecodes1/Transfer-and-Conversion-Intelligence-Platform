/**
 * Transfer & Conversion Intelligence Platform :: browser authentication.
 *
 * The console uses Keycloak's Authorization Code flow with PKCE. Credentials,
 * verification links and password-reset tokens stay on Keycloak pages; the
 * browser receives only a short-lived access token and keeps it in memory.
 */
import Keycloak, { type KeycloakTokenParsed } from "keycloak-js";

export type AuthenticationMode = "demo" | "oidc";

const configuredMode = (import.meta.env["VITE_TRANSFEROPS_AUTH"] ?? "enforce")
  .trim()
  .toLowerCase();

export const authenticationMode: AuthenticationMode =
  configuredMode === "demo" ? "demo" : "oidc";

const keycloak = new Keycloak({
  url: import.meta.env["VITE_KEYCLOAK_URL"] ?? "http://localhost:8080",
  realm: import.meta.env["VITE_KEYCLOAK_REALM"] ?? "transferops",
  clientId: import.meta.env["VITE_KEYCLOAK_CLIENT_ID"] ?? "transferops-api",
});

let initialised = false;

export type AuthenticatedUser = {
  username: string;
  displayName: string;
  email: string | null;
};

function claims(): KeycloakTokenParsed | undefined {
  return keycloak.tokenParsed;
}

export function authenticatedUser(): AuthenticatedUser | null {
  if (authenticationMode === "demo") return null;
  const token = claims();
  if (!keycloak.authenticated || !token) return null;
  const username = String(token["preferred_username"] ?? token.sub ?? "user");
  const displayName = String(token["name"] ?? username);
  const email = token["email"] ? String(token["email"]) : null;
  return { username, displayName, email };
}

export async function initialiseAuthentication(): Promise<void> {
  if (authenticationMode === "demo" || initialised) return;

  const authenticated = await keycloak.init({
    onLoad: "login-required",
    flow: "standard",
    pkceMethod: "S256",
    checkLoginIframe: false,
    enableLogging: import.meta.env.DEV,
  });
  initialised = true;

  if (!authenticated) {
    await keycloak.login({ redirectUri: window.location.href });
    return;
  }

  keycloak.onTokenExpired = () => {
    void keycloak.updateToken(30).catch(() =>
      keycloak.login({ redirectUri: window.location.href }),
    );
  };
}

/** Return a fresh access token without ever persisting it to browser storage. */
export async function accessToken(): Promise<string | null> {
  if (authenticationMode === "demo") return null;
  if (!keycloak.authenticated) return null;
  try {
    await keycloak.updateToken(30);
  } catch {
    await keycloak.login({ redirectUri: window.location.href });
    return null;
  }
  return keycloak.token ?? null;
}

export async function reauthenticate(): Promise<void> {
  if (authenticationMode === "demo") return;
  await keycloak.login({ redirectUri: window.location.href });
}

export async function createAccount(): Promise<void> {
  if (authenticationMode === "demo") return;
  await keycloak.register({ redirectUri: window.location.origin });
}

export async function manageAccount(): Promise<void> {
  if (authenticationMode === "demo") return;
  await keycloak.accountManagement();
}

export async function signOut(): Promise<void> {
  if (authenticationMode === "demo") return;
  await keycloak.logout({ redirectUri: window.location.origin });
}
