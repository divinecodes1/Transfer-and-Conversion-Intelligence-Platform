/**
 * Transfer & Conversion Intelligence Platform :: access and entitlements.
 *
 * The screen makes one distinction visible, because it is the distinction the
 * whole access model rests on: an application **role** and a data
 * **entitlement** are different things. A fully trusted analyst may still have
 * no business seeing another division's transfers.
 *
 * It is read-only, and that is not an omission. Entitlements are enforced by a
 * row-level policy on `tr_core.dim_project` and provisioned from version control
 * or the identity provider; a console that could grant itself a portfolio would
 * be a second, weaker authority sitting beside the one that actually holds.
 */
import { useQuery } from "@tanstack/react-query";
import { KeyRound, ShieldCheck, UserCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader, Panel, QueryState } from "@/components/panels";
import { useWhoami } from "@/lib/app-state";
import { whoamiQuery } from "@/lib/marts";

export function AccessScreen() {
  const me = useWhoami();
  const query = useQuery(whoamiQuery());
  const identity = query.data;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Access"
        description="Who the platform thinks you are, what you may do, and what you may see — resolved by the API, enforced by the database."
      />

      <QueryState isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()}>
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <UserCheck className="size-4" />
                Identity
              </div>
              <div className="num mt-2 text-lg font-semibold">{identity?.username ?? "—"}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                Resolved via <span className="num">{identity?.source ?? "—"}</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <ShieldCheck className="size-4" />
                Application roles
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(identity?.roles ?? []).length === 0 ? (
                  <span className="text-sm text-muted-foreground">No roles</span>
                ) : (
                  identity!.roles.map((role) => (
                    <Badge key={role} variant="secondary" className="num">
                      {role}
                    </Badge>
                  ))
                )}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                What you may do in the application.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <KeyRound className="size-4" />
                Data entitlements
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(identity?.portfolios ?? []).map((portfolio) => (
                  <Badge key={portfolio} variant="outline" className="num">
                    {portfolio === "*" ? "all portfolios" : portfolio}
                  </Badge>
                ))}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                What you may see. Separate from your role, and enforced below the application.
              </p>
            </CardContent>
          </Card>
        </div>

        <Panel
          title="How enforcement works"
          description="Three things have to hold together; missing any one leaves the policy installed but inert."
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Requirement</TableHead>
                <TableHead>Why it matters</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell className="num text-xs">FORCE ROW LEVEL SECURITY</TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  Without it the table owner bypasses its own policy.
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="num text-xs">Non-superuser connection</TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  Superusers bypass row-level security unconditionally, so the API connects as a
                  least-privilege reader rather than the bootstrap account.
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="num text-xs">security_invoker on every view</TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  Otherwise a view owned by the schema owner evaluates the policy as its owner and
                  quietly returns everything.
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="num text-xs">Fail-closed default</TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  An unset scope selects zero rows, so a forgotten assignment produces an obviously
                  empty result rather than a silent full-portfolio disclosure.
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </Panel>

        <Card className="border-dashed">
          <CardContent className="p-3 text-xs text-muted-foreground">
            {me.isAdmin
              ? "You hold PLATFORM_ADMIN, so you see the whole portfolio and the administrative screens. Switch demo identity from the user menu to see what a scoped user sees — the numbers change, because the policy is doing the work, not the interface."
              : "Your view is scoped to your entitled portfolios. If a screen looks empty, that is the default-deny policy working as designed rather than missing data."}
          </CardContent>
        </Card>
      </QueryState>
    </div>
  );
}
