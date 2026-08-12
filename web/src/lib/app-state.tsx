/**
 * Transfer & Conversion Intelligence Platform :: the console's shared state.
 *
 * Four small contexts, all of them deliberately thin:
 *
 *   Theme       light / dark, stored, applied before first paint by index.html
 *   Identity    which demo user the browser presents; never what they may see
 *   Filters     the one filter scope every screen and every AI surface reads
 *   Connection  live vs offline, and how old the offline snapshot is
 *
 * The identity context is worth being precise about. It selects a *claim*, not a
 * permission: the header goes to the API, the API resolves entitlements, and the
 * row-level policy enforces them. Nothing here decides what anyone can see, and
 * switching identity in the browser cannot widen a scope — it can only ask a
 * different question and get a smaller answer.
 */
import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { currentIdentity, setIdentity } from "./api";
import { useAuth } from "./auth-context";
import { whoamiQuery, type Filters } from "./marts";

// ---- Theme -----------------------------------------------------------------
type Theme = "light" | "dark";
const THEME_KEY = "transferops-theme";

const ThemeContext = React.createContext<{
  theme: Theme;
  setTheme: (theme: Theme) => void;
}>({ theme: "light", setTheme: () => {} });

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = React.useState<Theme>(() =>
    typeof document !== "undefined" && document.documentElement.classList.contains("dark")
      ? "dark"
      : "light",
  );

  const setTheme = React.useCallback((next: Theme) => {
    setThemeState(next);
    document.documentElement.classList.toggle("dark", next === "dark");
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* private mode: the choice simply does not survive a reload */
    }
  }, []);

  return <ThemeContext value={{ theme, setTheme }}>{children}</ThemeContext>;
}

export const useTheme = () => React.use(ThemeContext);

// ---- Identity --------------------------------------------------------------
const IdentityContext = React.createContext<{
  identity: string | null;
  switchTo: (identity: string | null) => void;
}>({ identity: null, switchTo: () => {} });

export function IdentityProvider({ children }: { children: React.ReactNode }) {
  const { mode, user } = useAuth();
  const [identity, setLocal] = React.useState<string | null>(() =>
    mode === "oidc" ? user?.username ?? null : currentIdentity(),
  );
  const queryClient = useQueryClient();

  const switchTo = React.useCallback(
    (next: string | null) => {
      if (mode === "oidc") return;
      setIdentity(next);
      setLocal(next);
      // Every cached answer was scoped to the previous identity. Keeping any of
      // it would show one user another user's numbers, which is the single worst
      // thing a client-side cache can do in an entitlement-scoped system.
      queryClient.clear();
    },
    [mode, queryClient],
  );

  return <IdentityContext value={{ identity, switchTo }}>{children}</IdentityContext>;
}

export const useIdentity = () => React.use(IdentityContext);

/** Who the platform says you are, and what you may see. */
export function useWhoami() {
  const { identity } = useIdentity();
  // The identity is part of the key: two identities are two different answers,
  // and sharing a cache entry between them would show one user another's scope.
  const query = useQuery({ ...whoamiQuery(), queryKey: ["whoami", identity ?? "default"] });
  const roles = query.data?.roles ?? [];
  return {
    ...query,
    roles,
    isAdmin: roles.includes("PLATFORM_ADMIN"),
    isAnalyst: roles.includes("PLATFORM_ADMIN") || roles.includes("ANALYST"),
  };
}

// ---- Filters ---------------------------------------------------------------
const FilterContext = React.createContext<{
  filters: Filters;
  setFilters: (next: Filters) => void;
  reset: () => void;
}>({ filters: {}, setFilters: () => {}, reset: () => {} });

const FILTER_KEYS = ["fiscal_year", "site", "transfer_type", "portfolio", "complexity"] as const;

/** Read the scope out of the URL, so a filtered view is a shareable link. */
function fromSearch(): Filters {
  const params = new URLSearchParams(window.location.search);
  const out: Filters = {};
  for (const key of FILTER_KEYS) {
    const value = params.get(key);
    if (!value) continue;
    if (key === "fiscal_year") out.fiscal_year = Number(value);
    else out[key] = value;
  }
  return out;
}

export function FilterProvider({ children }: { children: React.ReactNode }) {
  const [filters, setFiltersState] = React.useState<Filters>(fromSearch);

  const setFilters = React.useCallback((next: Filters) => {
    setFiltersState(next);
    // Mirrored into the URL so "the numbers I was looking at" is a link someone
    // can send, rather than a screenshot and a description of which dropdowns
    // to set. That is the whole answer to "he knows the filters, future users
    // won't".
    const params = new URLSearchParams(window.location.search);
    for (const key of FILTER_KEYS) {
      const value = next[key];
      if (value === null || value === undefined || value === "") params.delete(key);
      else params.set(key, String(value));
    }
    const search = params.toString();
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${search ? `?${search}` : ""}`,
    );
  }, []);

  const reset = React.useCallback(() => setFilters({}), [setFilters]);

  return <FilterContext value={{ filters, setFilters, reset }}>{children}</FilterContext>;
}

export const useFilters = () => React.use(FilterContext);

// ---- Connection mode -------------------------------------------------------
export type ConnectionMode = "live" | "offline";

const ConnectionContext = React.createContext<{
  mode: ConnectionMode;
  setMode: (mode: ConnectionMode) => void;
  online: boolean;
  syncedAt: number | null;
  syncNow: () => void;
}>({
  mode: "live",
  setMode: () => {},
  online: true,
  syncedAt: null,
  syncNow: () => {},
});

const SYNC_KEY = "transferops-synced-at";

export function ConnectionProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [mode, setModeState] = React.useState<ConnectionMode>("live");
  const [online, setOnline] = React.useState(() =>
    typeof navigator === "undefined" ? true : navigator.onLine,
  );
  const [syncedAt, setSyncedAt] = React.useState<number | null>(() => {
    try {
      const stored = localStorage.getItem(SYNC_KEY);
      return stored ? Number(stored) : null;
    } catch {
      return null;
    }
  });

  // The network is the source of truth about the network. Flipping the mode
  // automatically means a dropped connection shows the last snapshot instead of
  // a page of error cards — and the header says which it is looking at.
  React.useEffect(() => {
    const goOnline = () => {
      setOnline(true);
      setModeState("live");
    };
    const goOffline = () => {
      setOnline(false);
      setModeState("offline");
    };
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  React.useEffect(() => {
    queryClient.setDefaultOptions({
      queries: {
        networkMode: mode === "offline" ? "offlineFirst" : "online",
        staleTime: mode === "offline" ? Infinity : 30_000,
        refetchOnWindowFocus: mode === "live",
      },
    });
  }, [mode, queryClient]);

  const stamp = React.useCallback(() => {
    const now = Date.now();
    setSyncedAt(now);
    try {
      localStorage.setItem(SYNC_KEY, String(now));
    } catch {
      /* private mode: the snapshot age is simply not remembered */
    }
  }, []);

  const syncNow = React.useCallback(() => {
    setModeState("live");
    void queryClient.invalidateQueries().then(stamp);
  }, [queryClient, stamp]);

  const setMode = React.useCallback(
    (next: ConnectionMode) => {
      setModeState(next);
      if (next === "live") syncNow();
      else stamp();
    },
    [stamp, syncNow],
  );

  return (
    <ConnectionContext value={{ mode, setMode, online, syncedAt, syncNow }}>
      {children}
    </ConnectionContext>
  );
}

export const useConnection = () => React.use(ConnectionContext);
