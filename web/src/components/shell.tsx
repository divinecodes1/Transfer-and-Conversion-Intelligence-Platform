/**
 * Transfer & Conversion Intelligence Platform :: the application shell.
 *
 * Navigation, identity, theme and connection status. Two details are load-bearing
 * rather than decorative:
 *
 *   * **The identity pill shows entitlements, not just a name.** "You are
 *     manager.auto and you can see PF_AUTO" is the difference between a user
 *     believing the portfolio is small and understanding that their view of it
 *     is scoped. Two users get two answers, and the header says so.
 *
 *   * **The connection pill shows the snapshot age.** An offline dashboard that
 *     does not say how old it is looks exactly like a live one, which is how
 *     someone makes a Monday decision on Thursday's numbers.
 */
import * as React from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BookOpen,
  ChevronDown,
  Cloud,
  CloudOff,
  Database,
  LayoutDashboard,
  Link2,
  LogOut,
  Mail,
  MessageSquare,
  Moon,
  RefreshCw,
  ShieldCheck,
  Settings,
  Sun,
  Table2,
  Timer,
  TrendingUp,
  UserCircle2,
  FlaskConical,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useConnection, useIdentity, useTheme, useWhoami } from "@/lib/app-state";
import { useAuth } from "@/lib/auth-context";
import { healthQuery } from "@/lib/marts";
import { cn } from "@/lib/utils";

type NavItem = {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  admin?: boolean;
};

const PRIMARY_NAV: NavItem[] = [
  { to: "/", label: "Portfolio", icon: LayoutDashboard },
  { to: "/projects", label: "Projects", icon: Table2 },
  { to: "/reports", label: "Reports", icon: Mail },
  { to: "/ask", label: "Ask", icon: MessageSquare },
];

const ANALYTICS_NAV: NavItem[] = [
  { to: "/distribution", label: "Distribution", icon: TrendingUp },
  { to: "/forecast-accuracy", label: "Forecast", icon: Timer },
];

const MANAGE_NAV: NavItem[] = [
  { to: "/catalogue", label: "Catalogue", icon: BookOpen },
  { to: "/ingestion", label: "Ingestion", icon: Database, admin: true },
  { to: "/connections", label: "Connections", icon: Link2, admin: true },
  { to: "/automation", label: "Automation", icon: Activity, admin: true },
  { to: "/access", label: "Access", icon: ShieldCheck, admin: true },
];

export const NAV: NavItem[] = [...PRIMARY_NAV, ...ANALYTICS_NAV, ...MANAGE_NAV];

// The demo identities the realm ships with. Selecting one is a claim, never a
// permission: the API resolves entitlements and the row-level policy enforces
// them, so switching here can only ever narrow what comes back.
const DEMO_IDENTITIES = [
  { value: "admin", label: "admin — whole portfolio" },
  { value: "manager.auto", label: "manager.auto — PF_AUTO" },
  { value: "manager.power", label: "manager.power — PF_POWER" },
];

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
    >
      {theme === "dark" ? <Sun /> : <Moon />}
    </Button>
  );
}

function relativeAge(timestamp: number | null) {
  if (!timestamp) return "never";
  const seconds = Math.round((Date.now() - timestamp) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

function ConnectionStatus() {
  const { mode, setMode, online, syncedAt, syncNow } = useConnection();
  const { data } = useQuery(healthQuery());

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => setMode(mode === "live" ? "offline" : "live")}
        disabled={!online}
        title={
          online
            ? "Toggle between live queries and the last cached snapshot"
            : "The network is unavailable; showing the last snapshot"
        }
        className={cn(
          "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium",
          mode === "live" && online
            ? "border-ok/25 bg-ok/10 text-ok"
            : "border-warn/25 bg-warn/10 text-warn",
        )}
      >
        {mode === "live" && online ? (
          <Cloud className="size-3.5" />
        ) : (
          <CloudOff className="size-3.5" />
        )}
        {mode === "live" && online ? "Live" : "Offline"}
        <span className="hidden text-muted-foreground 2xl:inline">
          {mode === "live" && online
            ? data?.data_as_of
              ? `· data ${String(data.data_as_of).slice(0, 10)}`
              : ""
            : `· snapshot ${relativeAge(syncedAt)}`}
        </span>
      </button>
      <Button variant="ghost" size="icon" onClick={syncNow} title="Sync now" aria-label="Sync now">
        <RefreshCw />
      </Button>
    </div>
  );
}

function UserMenu() {
  const { identity, switchTo } = useIdentity();
  const auth = useAuth();
  const { data, isAdmin } = useWhoami();
  const displayName = auth.user?.displayName ?? data?.username ?? identity ?? "anonymous";

  const scope = data?.portfolios?.includes("*")
    ? "all portfolios"
    : (data?.portfolios ?? []).join(", ") || "no portfolios";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2">
          <UserCircle2 />
          <span className="hidden sm:inline">{displayName}</span>
          {isAdmin ? <Badge variant="secondary">admin</Badge> : null}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-64">
        <DropdownMenuLabel>Signed in as</DropdownMenuLabel>
        <div className="px-2 pb-2 text-sm">
          <div className="font-medium">{displayName}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            Roles: {(data?.roles ?? []).join(", ") || "none"}
          </div>
          <div className="text-xs text-muted-foreground">Entitled to: {scope}</div>
          <div className="text-xs text-muted-foreground">Resolved via: {data?.source ?? "—"}</div>
        </div>
        {auth.mode === "demo" ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Switch demo identity</DropdownMenuLabel>
            {DEMO_IDENTITIES.map((option) => (
              <DropdownMenuItem
                key={option.value}
                onSelect={() => switchTo(option.value)}
                className={identity === option.value ? "font-medium" : undefined}
              >
                {option.label}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => switchTo(null)}>
              Clear identity (use the API default)
            </DropdownMenuItem>
          </>
        ) : (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => void auth.account()}>
              <Settings />
              Manage account
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => void auth.logout()}>
              <LogOut />
              Sign out
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function routeIsActive(pathname: string, to: string) {
  return to === "/" ? pathname === "/" : pathname.startsWith(to);
}

function PrimaryNavLink({ item, pathname }: { item: NavItem; pathname: string }) {
  const active = routeIsActive(pathname, item.to);
  const Icon = item.icon;

  return (
    <Link
      to={item.to}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
        active
          ? "bg-accent font-medium text-accent-foreground"
          : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
      )}
      aria-current={active ? "page" : undefined}
    >
      <Icon className="size-4" />
      <span className="hidden lg:inline">{item.label}</span>
    </Link>
  );
}

function NavGroup({
  label,
  icon: Icon,
  items,
  pathname,
}: {
  label: string;
  icon: NavItem["icon"];
  items: NavItem[];
  pathname: string;
}) {
  const active = items.some((item) => routeIsActive(pathname, item.to));

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className={cn(
            "h-8 gap-1.5 px-2.5 font-normal",
            active
              ? "bg-accent font-medium text-accent-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
          aria-label={`${label} navigation`}
        >
          <Icon className="size-4" />
          <span className="hidden lg:inline">{label}</span>
          <ChevronDown className="hidden size-3 lg:block" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-48">
        <DropdownMenuLabel>{label}</DropdownMenuLabel>
        {items.map((item) => {
          const itemActive = routeIsActive(pathname, item.to);
          const ItemIcon = item.icon;
          return (
            <DropdownMenuItem key={item.to} asChild>
              <Link
                to={item.to}
                className={itemActive ? "bg-accent font-medium text-accent-foreground" : undefined}
                aria-current={itemActive ? "page" : undefined}
              >
                <ItemIcon className="size-4" />
                {item.label}
              </Link>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function TopNav() {
  const { isAdmin } = useWhoami();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const manageItems = MANAGE_NAV.filter((item) => !item.admin || isAdmin);

  return (
    <header className="no-print sticky top-0 z-40 border-b border-border bg-surface/95 backdrop-blur">
      <div className="flex min-h-14 w-full items-center gap-4 px-5">
        <Link to="/" className="flex shrink-0 items-center gap-2 font-semibold tracking-tight">
          <Activity className="size-5 text-primary" aria-hidden="true" />
          <span className="hidden xl:inline">Transfer &amp; Conversion Intelligence Platform</span>
          <span className="xl:hidden">TCIP</span>
        </Link>

        <nav className="flex flex-1 flex-wrap items-center gap-0.5" aria-label="Main">
          {PRIMARY_NAV.slice(0, 2).map((item) => (
            <PrimaryNavLink key={item.to} item={item} pathname={pathname} />
          ))}
          <NavGroup
            label="Tracking"
            icon={TrendingUp}
            items={ANALYTICS_NAV}
            pathname={pathname}
          />
          {PRIMARY_NAV.slice(2).map((item) => (
            <PrimaryNavLink key={item.to} item={item} pathname={pathname} />
          ))}
          <NavGroup label="Admin" icon={Settings} items={manageItems} pathname={pathname} />
        </nav>

        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          <ConnectionStatus />
          <ThemeToggle />
          <UserMenu />
        </div>
      </div>
    </header>
  );
}

export function DemoDataBanner() {
  const { data } = useQuery(healthQuery());
  const { isAdmin } = useWhoami();
  const count = data?.projects;

  return (
    <div className="no-print border-b border-warn/30 bg-warn/10 px-5 py-2 text-xs">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <FlaskConical className="size-4 shrink-0 text-warn" aria-hidden="true" />
        <span className="font-medium">Demo data</span>
        <span className="text-muted-foreground">
          {count ? `${count} projects shown are` : "The projects shown are"} synthetic samples,
          not real portfolio records.
        </span>
        {isAdmin ? (
          <Link to="/ingestion" className="font-medium text-primary hover:underline">
            Import real data
          </Link>
        ) : null}
      </div>
    </div>
  );
}
