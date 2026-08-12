/**
 * Transfer & Conversion Intelligence Platform :: the console's only route to data.
 *
 * The same rule the hand-built dashboard follows, carried into the React app:
 * this layer holds no SQL, no connection string and no metric logic. It calls
 * the governed API and hands responses back whole — provenance envelope
 * included — so every panel can render the definition, population, filters and
 * data vintage that produced it without the browser knowing what any metric
 * means.
 *
 * `tests/web_checks.py` asserts that: no SQL keyword and no registered metric
 * definition appears anywhere under `web/src`.
 *
 * Identity is forwarded, never decided. Production requests carry a short-lived
 * Keycloak bearer token; `X-Demo-User` exists only in explicit demo mode.
 * Entitlements still resolve in the API and are enforced by row-level policy.
 */

import { accessToken, authenticationMode } from "./auth";

const BASE = import.meta.env["VITE_TRANSFEROPS_API"] ?? "/api";
const AGENT = import.meta.env["VITE_TRANSFEROPS_AGENT"] ?? "/assistant";

const IDENTITY_KEY = "transferops-identity";

export function currentIdentity(): string | null {
  try {
    return localStorage.getItem(IDENTITY_KEY);
  } catch {
    return null;
  }
}

export function setIdentity(identity: string | null) {
  try {
    if (identity) localStorage.setItem(IDENTITY_KEY, identity);
    else localStorage.removeItem(IDENTITY_KEY);
  } catch {
    /* private mode: the request simply goes out unidentified */
  }
}

/** An API failure carrying the status, so callers can tell 403 from 503. */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function headers(): Promise<HeadersInit> {
  const out: Record<string, string> = { Accept: "application/json" };
  const token = await accessToken();
  if (token) out["Authorization"] = `Bearer ${token}`;
  if (authenticationMode === "demo") {
    const identity = currentIdentity();
    if (identity) out["X-Demo-User"] = identity;
  }
  return out;
}

/** Drop nulls and undefineds; the API treats an absent filter as "all". */
export function query(params: Record<string, unknown> = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, String(v)));
    else search.append(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function unwrap(response: Response) {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* a non-JSON error body is still an error */
    }
    throw new ApiError(detail, response.status);
  }
  return response.json();
}

export async function get<T>(
  path: string,
  params?: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${BASE}${path}${query(params)}`, {
    headers: await headers(),
    signal,
  });
  return unwrap(response) as Promise<T>;
}

export async function post<T>(
  path: string,
  body: unknown,
  params?: Record<string, unknown>,
): Promise<T> {
  const response = await fetch(`${BASE}${path}${query(params)}`, {
    method: "POST",
    headers: { ...(await headers()), "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return unwrap(response) as Promise<T>;
}

/** The assistant is a separate service, so it gets its own base URL. */
export async function askAssistant<T>(body: unknown): Promise<T> {
  const response = await fetch(`${AGENT}/ask`, {
    method: "POST",
    headers: { ...(await headers()), "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return unwrap(response) as Promise<T>;
}

export async function assistantModes<T>(): Promise<T> {
  const response = await fetch(`${AGENT}/modes`, { headers: await headers() });
  return unwrap(response) as Promise<T>;
}
