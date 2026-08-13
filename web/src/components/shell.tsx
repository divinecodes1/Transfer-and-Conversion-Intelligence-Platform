/** Enterprise application chrome for Transfer Intelligence. */
import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import {
  Activity,
  Bell,
  BookOpen,
  BrainCircuit,
  ChevronDown,
  ClipboardCheck,
  Cloud,
  CloudOff,
  Database,
  FlaskConical,
  Gauge,
  HelpCircle,
  Link2,
  LogOut,
  Mail,
  Menu,
  Moon,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sun,
  Table2,
  Timer,
  TrendingUp,
  UserCircle2,
  Waypoints,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
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

type NavSection = {
  label: string;
  items: NavItem[];
};

const NAV_SECTIONS: NavSection[] = [
  {
    label: "Overview",
    items: [{ to: "/", label: "Command Center", icon: Gauge }],
  },
  {
    label: "Transfer Management",
    items: [
      { to: "/projects", label: "Transfer Portfolio", icon: Table2 },
      { to: "/readiness", label: "Readiness", icon: ClipboardCheck },
    ],
  },
  {
    label: "Performance",
    items: [
      { to: "/distribution", label: "Cycle-time Distribution", icon: TrendingUp },
      { to: "/forecast-accuracy", label: "Forecast vs Actual", icon: Timer },
      { to: "/network", label: "Transfer Network", icon: Waypoints },
    ],
  },
  {
    label: "AI Intelligence",
    items: [{ to: "/ask", label: "AI Copilot", icon: BrainCircuit }],
  },
  {
    label: "Reporting",
    items: [{ to: "/reports", label: "Management Reports", icon: Mail }],
  },
  {
    label: "Knowledge",
    items: [{ to: "/catalogue", label: "Metric Catalogue", icon: BookOpen }],
  },
  {
    label: "Operations",
    items: [
      { to: "/ingestion", label: "Data Ingestion", icon: Database, admin: true },
      { to: "/connections", label: "Connections", icon: Link2, admin: true },
      { to: "/automation", label: "AI Operations", icon: Activity, admin: true },
      { to: "/access", label: "Users & Access", icon: ShieldCheck, admin: true },
    ],
  },
];

export const NAV = NAV_SECTIONS.flatMap((section) => section.items);

const DEMO_IDENTITIES = [
  { value: "admin", label: "admin — whole portfolio" },
  { value: "manager.auto", label: "manager.auto — PF_AUTO" },
  { value: "manager.power", label: "manager.power — PF_POWER" },
];

function routeIsActive(pathname: string, to: string) {
  return to === "/" ? pathname === "/" : pathname.startsWith(to);
}

function relativeAge(timestamp: number | null) {
  if (!timestamp) return "not synced";
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

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

function ConnectionStatus() {
  const { mode, setMode, online, syncedAt, syncNow } = useConnection();
  const { data } = useQuery(healthQuery());
  const live = mode === "live" && online;

  return (
    <div className="hidden items-center gap-1 lg:flex">
      <button
        type="button"
        onClick={() => setMode(live ? "offline" : "live")}
        disabled={!online}
        className={cn(
          "inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-xs",
          live ? "text-ok" : "text-warn",
        )}
        title="Toggle live and cached data"
      >
        {live ? <Cloud className="size-3.5" /> : <CloudOff className="size-3.5" />}
        <span>
          <span className="font-medium">{live ? "Live data" : "Cached data"}</span>
          <span className="ml-1 text-muted-foreground">
            {live && data?.data_as_of
              ? `· ${String(data.data_as_of).slice(0, 10)}`
              : `· ${relativeAge(syncedAt)}`}
          </span>
        </span>
      </button>
      <Button variant="ghost" size="icon" onClick={syncNow} title="Refresh data" aria-label="Refresh data">
        <RefreshCw />
      </Button>
    </div>
  );
}

function NotificationsMenu() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Notifications" title="Notifications">
          <Bell />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel>Notifications</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <div className="px-2 py-5 text-center text-xs text-muted-foreground">
          No unread operational notifications.
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu() {
  const { identity, switchTo } = useIdentity();
  const auth = useAuth();
  const { data, isAdmin } = useWhoami();
  const displayName = auth.user?.displayName ?? data?.username ?? identity ?? "anonymous";
  const initials = displayName
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
  const scope = data?.portfolios?.includes("*")
    ? "all portfolios"
    : (data?.portfolios ?? []).join(", ") || "no portfolios";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="h-10 gap-2 px-2">
          <span className="grid size-7 place-items-center rounded-full bg-accent text-xs font-semibold text-primary">
            {initials || <UserCircle2 className="size-4" />}
          </span>
          <span className="hidden max-w-40 truncate text-left xl:block">
            <span className="block text-xs font-medium">{displayName}</span>
            <span className="block text-[10px] uppercase tracking-wide text-muted-foreground">
              {isAdmin ? "Administrator" : "Portfolio user"}
            </span>
          </span>
          <ChevronDown className="hidden size-3 xl:block" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-72">
        <DropdownMenuLabel>Signed in as</DropdownMenuLabel>
        <div className="px-2 pb-2 text-sm">
          <div className="font-medium">{displayName}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            Roles: {(data?.roles ?? []).join(", ") || "none"}
          </div>
          <div className="text-xs text-muted-foreground">Entitled to: {scope}</div>
        </div>
        {auth.mode === "demo" ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Switch demo identity</DropdownMenuLabel>
            {DEMO_IDENTITIES.map((option) => (
              <DropdownMenuItem key={option.value} onSelect={() => switchTo(option.value)}>
                {option.label}
              </DropdownMenuItem>
            ))}
          </>
        ) : (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => void auth.account()}>
              <Settings /> Manage account
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => void auth.logout()}>
              <LogOut /> Sign out
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function GlobalSearch() {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [value, setValue] = React.useState("");

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <form
      className="relative hidden w-full max-w-xl md:block"
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        const query = value.trim();
        if (query) window.location.assign(`/projects?search=${encodeURIComponent(query)}`);
      }}
    >
      <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-muted-foreground" />
      <Input
        ref={inputRef}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        className="h-9 bg-secondary/60 pl-9 pr-16"
        placeholder="Search transfers, projects, sites, technologies…"
        aria-label="Global search"
      />
      <kbd className="pointer-events-none absolute right-2.5 top-2 rounded border border-border bg-surface px-1.5 py-0.5 text-[10px] text-muted-foreground">
        Ctrl K
      </kbd>
    </form>
  );
}

function AppHeader({ onMenu }: { onMenu: () => void }) {
  return (
    <header className="no-print sticky top-0 z-50 flex h-16 items-center border-b border-border bg-surface px-4 lg:px-6">
      <div className="flex w-full items-center gap-4">
        <Button variant="ghost" size="icon" className="lg:hidden" onClick={onMenu} aria-label="Open navigation">
          <Menu />
        </Button>
        <Link to="/" className="flex w-[224px] shrink-0 items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-md bg-primary text-primary-foreground">
            <Activity className="size-5" />
          </span>
          <span>
            <span className="block text-sm font-semibold tracking-tight">Transfer Intelligence</span>
            <span className="hidden text-[10px] uppercase tracking-[0.12em] text-muted-foreground 2xl:block">
              Operations intelligence
            </span>
          </span>
        </Link>
        <div className="flex flex-1 justify-center">
          <GlobalSearch />
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          <ConnectionStatus />
          <NotificationsMenu />
          <Button asChild variant="ghost" size="icon" title="Help and metric definitions">
            <Link to="/catalogue" aria-label="Help and metric definitions">
              <HelpCircle />
            </Link>
          </Button>
          <ThemeToggle />
          <UserMenu />
        </div>
      </div>
    </header>
  );
}

function SidebarSection({ section, pathname, onNavigate, isAdmin }: { section: NavSection; pathname: string; onNavigate: () => void; isAdmin: boolean }) {
  const items = section.items.filter((item) => !item.admin || isAdmin);
  const [open, setOpen] = React.useState(true);
  if (items.length === 0) return null;

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between px-4 py-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground hover:text-foreground"
        aria-expanded={open}
      >
        {section.label}
        <ChevronDown className={cn("size-3 transition-transform", open ? "" : "-rotate-90")} />
      </button>
      {open ? (
        <nav className="space-y-0.5" aria-label={section.label}>
          {items.map((item) => {
            const active = routeIsActive(pathname, item.to);
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative flex items-center gap-3 px-4 py-2 text-[13px] transition-colors",
                  active
                    ? "bg-accent font-medium text-primary before:absolute before:inset-y-1 before:left-0 before:w-[3px] before:rounded-r before:bg-primary"
                    : "text-muted-foreground hover:bg-secondary hover:text-foreground",
                )}
              >
                <Icon className="size-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      ) : null}
    </div>
  );
}

function AppSidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const { isAdmin } = useWhoami();

  return (
    <>
      {open ? (
        <button
          type="button"
          className="no-print fixed inset-0 z-40 bg-foreground/20 lg:hidden"
          onClick={onClose}
          aria-label="Close navigation"
        />
      ) : null}
      <aside
        className={cn(
          "no-print fixed inset-y-0 left-0 z-50 flex w-[248px] flex-col border-r border-border bg-surface pt-16 transition-transform lg:sticky lg:top-16 lg:z-30 lg:h-[calc(100vh-4rem)] lg:translate-x-0 lg:pt-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
        aria-label="Primary navigation"
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3 lg:hidden">
          <span className="text-sm font-semibold">Navigation</span>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close navigation">
            <X />
          </Button>
        </div>
        <div className="flex-1 space-y-2 overflow-y-auto py-3">
          {NAV_SECTIONS.map((section) => (
            <SidebarSection key={section.label} section={section} pathname={pathname} onNavigate={onClose} isAdmin={isAdmin} />
          ))}
        </div>
        <div className="border-t border-border p-4 text-[11px] leading-5 text-muted-foreground">
          <div className="flex items-center gap-2 font-medium text-foreground">
            <ShieldCheck className="size-3.5 text-primary" /> Governed workspace
          </div>
          Metric definitions, scope and data vintage remain attached to every analytical view.
        </div>
      </aside>
    </>
  );
}

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <AppHeader onMenu={() => setMobileNavOpen(true)} />
      <div className="flex flex-1">
        <AppSidebar open={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
        <div className="min-w-0 flex-1">{children}</div>
      </div>
      <AppFooter />
    </div>
  );
}

/**
 * The closing band.
 *
 * A solid brand-coloured footer is the most recognisable structural element of
 * the reference design language: every page in it terminates in one. It also
 * does something useful here rather than only decorative — a dense analytical
 * page otherwise just stops, and the band gives the content a floor.
 *
 * `flex-col` + `flex-1` on the shell above is what keeps it at the bottom of a
 * short screen instead of floating halfway up an empty viewport.
 *
 * Colours come from --brand in styles.css, never from a literal here:
 * tests/web_checks.py asserts the palette lives in exactly one file.
 */
function AppFooter() {
  return (
    <footer className="no-print mt-auto bg-brand text-brand-foreground">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-3 px-6 py-6 text-xs sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <Activity className="size-4" aria-hidden="true" />
          <span className="font-medium">Transfer &amp; Conversion Intelligence Platform</span>
        </div>

        <nav className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <Link to="/catalogue" className="hover:underline">
            Metric catalogue
          </Link>
          <Link to="/access" className="hover:underline">
            Access &amp; entitlements
          </Link>
          <Link to="/reports" className="hover:underline">
            Reports
          </Link>
        </nav>

        {/* The disclaimer belongs somewhere permanent, not only in a dismissible
            banner. Synthetic data presented as real would be the one genuinely
            damaging thing this demonstration could do. */}
        <span className="text-brand-muted">
          Demonstration environment · synthetic data
        </span>
      </div>
    </footer>
  );
}

export function DemoDataBanner() {
  const { data } = useQuery(healthQuery());
  const { isAdmin } = useWhoami();
  const count = data?.projects;

  return (
    <div className="no-print border-b border-warn/30 bg-warn/10 px-6 py-2 text-xs">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-2 gap-y-1">
        <FlaskConical className="size-4 shrink-0 text-warn" aria-hidden="true" />
        <span className="font-medium">Demonstration dataset</span>
        <span className="text-muted-foreground">
          {count ? `${count} projects are` : "Projects are"} synthetic samples and must not be used as production records.
        </span>
        {isAdmin ? (
          <Link to="/ingestion" className="font-medium text-primary hover:underline">
            Import governed data
          </Link>
        ) : null}
      </div>
    </div>
  );
}
