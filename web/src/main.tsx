/**
 * Transfer & Conversion Intelligence Platform :: entry point.
 *
 * The query client is configured once here. Two settings are deliberate:
 *
 *   * **Persisted to localStorage.** That is what makes offline mode real rather
 *     than cosmetic: the last answer survives a reload, so a dropped connection
 *     shows the previous snapshot with its age stated, not a page of errors.
 *
 *   * **A cache buster keyed on the API contract.** A persisted cache written by
 *     an older build can contain rows in a shape this build no longer
 *     understands. Bumping the key throws that away instead of rendering it.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { RouterProvider } from "@tanstack/react-router";
import { router } from "@/router";
import { authenticatedUser, authenticationMode, initialiseAuthentication } from "@/lib/auth";
import { AuthProvider } from "@/lib/auth-context";
import "@/styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 24 * 60 * 60 * 1000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const persister = createSyncStoragePersister({
  storage: typeof window === "undefined" ? undefined : window.localStorage,
  key: "transferops-query-cache",
});

const root = document.getElementById("root");
if (!root) throw new Error("No #root element to mount into.");
const rootElement = root;

function StartupFailure({ error }: { error: unknown }) {
  return (
    <main className="grid min-h-screen place-items-center bg-background p-6 text-foreground">
      <section className="w-full max-w-md rounded-md border border-border bg-card p-6">
        <p className="text-xs font-semibold uppercase tracking-wider text-primary">
          Authentication unavailable
        </p>
        <h1 className="mt-2 text-xl font-semibold">We could not reach the sign-in service</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Start the identity service, then try again. No credentials were submitted.
        </p>
        {import.meta.env.DEV ? (
          <pre className="mt-4 overflow-auto rounded-md bg-muted p-3 text-xs">
            {error instanceof Error ? error.message : String(error)}
          </pre>
        ) : null}
        <button
          type="button"
          className="mt-5 w-full rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
          onClick={() => window.location.reload()}
        >
          Try again
        </button>
      </section>
    </main>
  );
}

async function bootstrap() {
  try {
    // Keycloak may consume the OIDC callback parameters in the current URL, so
    // it must initialise before TanStack Router reads that URL.
    await initialiseAuthentication();
    // Metric query keys intentionally describe the query, not the person. The
    // persisted-cache buster therefore carries the verified username so a new
    // person signing in on the same browser can never hydrate the previous
    // person's entitlement-scoped results.
    const cacheIdentity = authenticatedUser()?.username ?? authenticationMode;
    createRoot(rootElement).render(
      <StrictMode>
        <AuthProvider>
          <PersistQueryClientProvider
            client={queryClient}
            persistOptions={{
              persister,
              maxAge: 24 * 60 * 60 * 1000,
              // Auth is part of the persisted contract: never reuse a cache
              // written before bearer-token scoping was introduced.
              buster: `mart-v2-auth:${cacheIdentity}`,
            }}
          >
            <RouterProvider router={router} />
          </PersistQueryClientProvider>
        </AuthProvider>
      </StrictMode>,
    );
  } catch (error) {
    createRoot(rootElement).render(<StartupFailure error={error} />);
  }
}

void bootstrap();
