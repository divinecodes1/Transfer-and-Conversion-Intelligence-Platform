/**
 * Transfer & Conversion Intelligence Platform :: routes.
 *
 * Code-based route definitions rather than file-system routing with a codegen
 * step. One fewer generated artefact to keep in sync, and the whole route table
 * — including which screens are administrative — is readable in one place.
 *
 * Admin screens are gated here *and* at the API. The gate below is a courtesy so
 * a non-admin does not walk into a wall of 403s; the gate that matters is the
 * one on the server, because a check the browser performs is a check the browser
 * can skip.
 */
import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  useParams,
  useRouterState,
} from "@tanstack/react-router";
import { Activity, LoaderCircle, LogOut, RefreshCw, ShieldAlert } from "lucide-react";
import { Toaster } from "sonner";
import { AiAssistant } from "@/components/ai";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FilterBar } from "@/components/FilterBar";
import { DemoDataBanner, TopNav } from "@/components/shell";
import {
  ConnectionProvider,
  FilterProvider,
  IdentityProvider,
  ThemeProvider,
  useWhoami,
} from "@/lib/app-state";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { AccessScreen } from "@/routes/access";
import { AskScreen } from "@/routes/ask";
import { AutomationScreen } from "@/routes/automation";
import { CatalogueScreen } from "@/routes/catalogue";
import { ConnectionsScreen } from "@/routes/connections";
import { DistributionScreen } from "@/routes/distribution";
import { ForecastAccuracyScreen } from "@/routes/forecast-accuracy";
import { IngestionScreen } from "@/routes/ingestion";
import { OverviewScreen } from "@/routes/overview";
import { ProjectDetailScreen } from "@/routes/project-detail";
import { ProjectsScreen } from "@/routes/projects";
import { ReportsScreen } from "@/routes/reports";

function Shell() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const showWorkspaceScope = [
    "/",
    "/projects",
    "/distribution",
    "/forecast-accuracy",
    "/reports",
    "/ask",
  ].some((path) => (path === "/" ? pathname === "/" : pathname.startsWith(path)));

  return (
    <ThemeProvider>
      <IdentityProvider>
        <AuthorisationBoundary>
          <ConnectionProvider>
            <FilterProvider>
              <div className="min-h-screen bg-background">
                <TopNav />
                {showWorkspaceScope ? (
                  <>
                    <DemoDataBanner />
                    <FilterBar />
                  </>
                ) : null}
                <main className="w-full p-5">
                  <Outlet />
                </main>
                <AiAssistant />
                <Toaster position="bottom-left" />
              </div>
            </FilterProvider>
          </ConnectionProvider>
        </AuthorisationBoundary>
      </IdentityProvider>
    </ThemeProvider>
  );
}

function AuthorisationBoundary({ children }: { children: React.ReactNode }) {
  const identity = useWhoami();
  const { mode, user, login, logout } = useAuth();

  if (identity.isLoading) {
    return (
      <main className="grid min-h-screen place-items-center bg-background text-foreground">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <LoaderCircle className="size-5 animate-spin text-primary" />
          Confirming your access…
        </div>
      </main>
    );
  }

  if (mode === "oidc" && identity.error) {
    const status = identity.error instanceof ApiError ? identity.error.status : 0;
    const pending = status === 403;
    const unavailable = status === 0 || status >= 500;
    return (
      <main className="grid min-h-screen place-items-center bg-background p-6 text-foreground">
        <Card className="w-full max-w-lg">
          <CardContent className="p-7">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Activity className="size-5 text-primary" />
              Transfer &amp; Conversion Intelligence Platform
            </div>
            <div className="mt-8 grid size-11 place-items-center rounded-md bg-accent text-primary">
              <ShieldAlert className="size-5" />
            </div>
            <h1 className="mt-4 text-xl font-semibold">
              {pending
                ? "Your account is verified"
                : unavailable
                  ? "Analytics API is offline"
                  : "Your session needs attention"}
            </h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              {pending
                ? "Your identity is ready, but this restricted platform still needs an administrator to assign your role and portfolio access."
                : unavailable
                  ? "The analytics API is unavailable. Start or restore the API service, then retry. Your Keycloak sign-in is still valid."
                  : "The analytics service did not accept this session. Sign in again to obtain a fresh, verified session."}
            </p>
            {user ? (
              <div className="mt-5 rounded-md border border-border bg-muted/40 p-3 text-sm">
                <div className="font-medium">{user.displayName}</div>
                <div className="text-muted-foreground">{user.email ?? user.username}</div>
              </div>
            ) : null}
            <div className="mt-6 flex flex-wrap gap-2">
              {pending ? null : unavailable ? (
                <Button onClick={() => void identity.refetch()}>
                  <RefreshCw />
                  Retry connection
                </Button>
              ) : (
                <Button onClick={() => void login()}>Sign in again</Button>
              )}
              <Button variant="outline" onClick={() => void logout()}>
                <LogOut />
                Sign out
              </Button>
            </div>
          </CardContent>
        </Card>
      </main>
    );
  }

  return <>{children}</>;
}

const rootRoute = createRootRoute({
  component: Shell,
  notFoundComponent: () => (
    <Card>
      <CardContent className="p-6 text-sm text-muted-foreground">
        No such screen. Use the navigation above.
      </CardContent>
    </Card>
  ),
});

/** Courtesy gate. The server is the boundary; this is the explanation. */
function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { isAdmin, isLoading } = useWhoami();
  if (isLoading) return null;
  if (!isAdmin) {
    return (
      <Card className="border-warn/25 bg-warn/5">
        <CardContent className="flex items-start gap-3 p-5">
          <ShieldAlert className="mt-0.5 size-5 text-warn" />
          <div className="text-sm">
            <div className="font-medium text-warn">Administrator access required</div>
            <p className="mt-1 text-muted-foreground">
              This screen needs the <span className="num">PLATFORM_ADMIN</span> role. Your current
              identity does not hold it — switch identity from the user menu, or ask an
              administrator to grant it.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }
  return <>{children}</>;
}

// Generic over the path so the literal survives into the route tree. A plain
// `path: string` widens it, and every `<Link to="/projects">` in the app then
// fails to typecheck against a route table that no longer knows the route.
const screen = <TPath extends string>(path: TPath, component: () => React.ReactNode) =>
  createRoute({ getParentRoute: () => rootRoute, path, component });

const indexRoute = screen("/", OverviewScreen);
const projectsRoute = screen("/projects", ProjectsScreen);
const distributionRoute = screen("/distribution", DistributionScreen);
const forecastRoute = screen("/forecast-accuracy", ForecastAccuracyScreen);
const reportsRoute = screen("/reports", ReportsScreen);
const askRoute = screen("/ask", AskScreen);
const catalogueRoute = screen("/catalogue", CatalogueScreen);

const projectDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId",
  component: function ProjectDetailRoute() {
    const { projectId } = useParams({ from: "/projects/$projectId" });
    return <ProjectDetailScreen projectId={projectId} />;
  },
});

const admin = <TPath extends string>(path: TPath, Component: () => React.ReactNode) =>
  createRoute({
    getParentRoute: () => rootRoute,
    path,
    component: () => (
      <RequireAdmin>
        <Component />
      </RequireAdmin>
    ),
  });

const ingestionRoute = admin("/ingestion", IngestionScreen);
const connectionsRoute = admin("/connections", ConnectionsScreen);
const automationRoute = admin("/automation", AutomationScreen);
const accessRoute = admin("/access", AccessScreen);

const routeTree = rootRoute.addChildren([
  indexRoute,
  projectsRoute,
  projectDetailRoute,
  distributionRoute,
  forecastRoute,
  reportsRoute,
  askRoute,
  catalogueRoute,
  ingestionRoute,
  connectionsRoute,
  automationRoute,
  accessRoute,
]);

export const router = createRouter({ routeTree, defaultPreload: "intent" });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
