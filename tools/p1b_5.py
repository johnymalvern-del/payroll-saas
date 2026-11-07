"""Phase 1B frontend: api additions + page + test + nav + strings + App.tsx."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "frontend" / "src"

# 1. api/intelligence.ts — append decisions client
pp = FE / "api" / "intelligence.ts"
s = pp.read_text(encoding="utf-8")
if "listDecisions" in s:
    print("api: already has listDecisions")
else:
    addition = '''

// ---- Phase 1B — decision records (read-only) ----

export type DecisionSummary = {
  id: string;
  employee_id: string;
  workflow: string;
  source_type: string;
  source_id: string | null;
  decision_type: string;
  initiator_type: string;
  initiator_user_id: string | null;
  company_default_mode: string | null;
  effective_workflow_mode: string | null;
  workflow_override_mode: string | null;
  execution_status: string;
  created_at: string;
};

export type DecisionSnapshot = {
  id: string;
  decision_id: string;
  created_at: string;
  schema_version: number;
  payload: Record<string, unknown>;
  sha256_hex: string;
};

export type DecisionDetail = DecisionSummary & {
  policy_version: string | null;
  statutory_version: string | null;
  recommendation: Record<string, unknown> | null;
  explanation: string | null;
  audit_id: string | null;
  evidence_snapshot_id: string | null;
  snapshot: DecisionSnapshot | null;
};

export type DecisionListOut = {
  items: DecisionSummary[];
  next_cursor: string | null;
  total: number | null;
};

'''
    s = s.rstrip() + addition
    # extend the intelligenceApi object
    s = s.replace(
        "  getChangeLog: () =>\n    req<{ items: ModeChangeLog[] }>(\"GET\", \"/settings/change-log?limit=50\"),\n};",
        '''  getChangeLog: () =>
    req<{ items: ModeChangeLog[] }>("GET", "/settings/change-log?limit=50"),
  listDecisions: (params?: {
    workflow?: string;
    employee_id?: string;
    status?: string;
    limit?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.workflow) qs.set("workflow", params.workflow);
    if (params?.employee_id) qs.set("employee_id", params.employee_id);
    if (params?.status) qs.set("status", params.status);
    if (params?.limit) qs.set("limit", String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return req<DecisionListOut>("GET", `/decisions${suffix}`);
  },
  getDecision: (id: string) =>
    req<DecisionDetail>("GET", `/decisions/${id}`),
  verifyDecisionSnapshot: (id: string) =>
    req<{ valid: boolean; decision_id: string }>(
      "GET",
      `/decisions/${id}/verify`,
    ),
};''',
        1,
    )
    pp.write_text(s, encoding="utf-8")
    print("api: appended decisions client")

# 2. Page
(FE / "pages" / "IntelligenceDecisionsPage.tsx").write_text('''import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Drawer,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import dayjs from "dayjs";
import {
  intelligenceApi,
  type DecisionDetail,
  type DecisionSummary,
} from "../api/intelligence";
import { PageHeader } from "../components/layout/PageHeader";
import { EmptyState } from "../components/layout/EmptyState";
import { TableSkeleton } from "../components/layout/TableSkeleton";
import { colors } from "../theme/colors";

export function IntelligenceDecisionsPage() {
  const [workflow, setWorkflow] = useState("");
  const [status, setStatus] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["intelligence", "decisions", workflow, status],
    queryFn: () =>
      intelligenceApi.listDecisions({
        workflow: workflow || undefined,
        status: status || undefined,
        limit: 100,
      }),
    staleTime: 30_000,
  });

  const detail = useQuery({
    queryKey: ["intelligence", "decision", selectedId],
    queryFn: () => intelligenceApi.getDecision(selectedId!),
    enabled: !!selectedId,
    staleTime: 30_000,
  });

  const verify = useQuery({
    queryKey: ["intelligence", "decision", selectedId, "verify"],
    queryFn: () => intelligenceApi.verifyDecisionSnapshot(selectedId!),
    enabled: !!selectedId,
    staleTime: Infinity,
  });

  return (
    <Stack>
      <PageHeader
        title="Decision records"
        subtitle="Read-only inspection of every intelligence decision record and its immutable evidence snapshot."
      />

      <Card>
        <Group gap="sm" wrap="wrap">
          <TextInput
            label="Workflow"
            placeholder="e.g. leave_decision"
            value={workflow}
            onChange={(e) => setWorkflow(e.currentTarget.value)}
            data-testid="decisions-filter-workflow"
            w={220}
          />
          <TextInput
            label="Status"
            placeholder="e.g. pending"
            value={status}
            onChange={(e) => setStatus(e.currentTarget.value)}
            data-testid="decisions-filter-status"
            w={180}
          />
        </Group>
      </Card>

      {list.isLoading ? (
        <TableSkeleton rows={6} cols={6} />
      ) : list.isError ? (
        <Alert color={colors.problem}>
          Could not load decision records.{" "}
          {(list.error as Error | undefined)?.message?.includes("403")
            ? "You do not have permission."
            : ""}
        </Alert>
      ) : !list.data || list.data.items.length === 0 ? (
        <EmptyState message="No decision records yet." />
      ) : (
        <Table data-testid="decisions-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>When</Table.Th>
              <Table.Th>Workflow</Table.Th>
              <Table.Th>Type</Table.Th>
              <Table.Th>Initiator</Table.Th>
              <Table.Th>Mode</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {list.data.items.map((d: DecisionSummary) => (
              <Table.Tr key={d.id}>
                <Table.Td>{dayjs(d.created_at).format("YYYY-MM-DD HH:mm")}</Table.Td>
                <Table.Td>{d.workflow}</Table.Td>
                <Table.Td>
                  <Badge variant="light" color={colors.info}>
                    {d.decision_type}
                  </Badge>
                </Table.Td>
                <Table.Td>{d.initiator_type}</Table.Td>
                <Table.Td>{d.effective_workflow_mode ?? "—"}</Table.Td>
                <Table.Td>
                  <Badge variant="light" color={colors.pending}>
                    {d.execution_status}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Button
                    size="xs"
                    variant="light"
                    onClick={() => setSelectedId(d.id)}
                  >
                    View
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Drawer
        opened={!!selectedId}
        onClose={() => setSelectedId(null)}
        position="right"
        size="lg"
        title="Decision record"
      >
        {detail.isLoading ? (
          <Loader />
        ) : detail.isError || !detail.data ? (
          <Alert color={colors.problem}>Could not load decision.</Alert>
        ) : (
          <Stack gap="md">
            <Stack gap={2}>
              <Text fw={600}>{detail.data.workflow}</Text>
              <Text size="sm" c="dimmed">
                {detail.data.id}
              </Text>
            </Stack>

            <Group gap="xs">
              <Badge variant="light">{detail.data.decision_type}</Badge>
              <Badge variant="light">{detail.data.initiator_type}</Badge>
              <Badge variant="light">{detail.data.execution_status}</Badge>
            </Group>

            <Group gap="lg">
              <Stack gap={0}>
                <Text size="xs" c="dimmed">Company mode</Text>
                <Text>{detail.data.company_default_mode ?? "—"}</Text>
              </Stack>
              <Stack gap={0}>
                <Text size="xs" c="dimmed">Effective mode</Text>
                <Text>{detail.data.effective_workflow_mode ?? "—"}</Text>
              </Stack>
              <Stack gap={0}>
                <Text size="xs" c="dimmed">Override</Text>
                <Text>{detail.data.workflow_override_mode ?? "—"}</Text>
              </Stack>
            </Group>

            {detail.data.explanation ? (
              <Stack gap={2}>
                <Text size="sm" fw={500}>Explanation</Text>
                <Text size="sm">{detail.data.explanation}</Text>
              </Stack>
            ) : null}

            {detail.data.recommendation ? (
              <Stack gap={2}>
                <Text size="sm" fw={500}>Recommendation</Text>
                <Code block>{JSON.stringify(detail.data.recommendation, null, 2)}</Code>
              </Stack>
            ) : null}

            {detail.data.snapshot ? (
              <Stack gap={2}>
                <Text size="sm" fw={500}>Evidence snapshot</Text>
                <Text size="xs" c="dimmed">
                  SHA-256: {detail.data.snapshot.sha256_hex}
                </Text>
                <Code block>{JSON.stringify(detail.data.snapshot.payload, null, 2)}</Code>
                {verify.data ? (
                  <Alert
                    color={verify.data.valid ? colors.approved : colors.problem}
                    data-testid="decisions-verify-result"
                  >
                    {verify.data.valid
                      ? "Snapshot integrity verified."
                      : "Snapshot integrity FAILED."}
                  </Alert>
                ) : null}
              </Stack>
            ) : (
              <Alert color={colors.inactive}>No snapshot attached.</Alert>
            )}
          </Stack>
        )}
      </Drawer>
    </Stack>
  );
}
''', encoding="utf-8")
print("wrote IntelligenceDecisionsPage.tsx")

# 3. Nav — add decisions item under Audit group
nav = FE / "shell" / "nav.ts"
s = nav.read_text(encoding="utf-8")
if "/intelligence/decisions" in s:
    print("nav: already has decisions item")
else:
    s = s.replace(
        '''  { permission: "audit_view", group: "Audit",
    item: { label: "Audit log", to: "/audit-log", icon: "audit" } },''',
        '''  { permission: "intelligence_view", group: "Audit",
    item: { label: "Decision records", to: "/intelligence/decisions", icon: "audit" } },
  { permission: "audit_view", group: "Audit",
    item: { label: "Audit log", to: "/audit-log", icon: "audit" } },''',
        1,
    )
    nav.write_text(s, encoding="utf-8")
    print("nav: added Decision records item")

# 4. App.tsx route
app = FE / "App.tsx"
s = app.read_text(encoding="utf-8")
if "IntelligenceDecisionsPage" in s:
    print("App.tsx: already has IntelligenceDecisionsPage")
else:
    anchor = 'import { IntelligenceSettingsPage } from "./pages/setup/IntelligenceSettingsPage";'
    if anchor in s:
        s = s.replace(
            anchor,
            anchor + '\nimport { IntelligenceDecisionsPage } from "./pages/IntelligenceDecisionsPage";',
            1,
        )
    m = s.find('<Route path="intelligence" element={<IntelligenceSettingsPage />} />')
    if m > 0:
        s = s[:m] + (
            '<Route path="intelligence" element={<IntelligenceSettingsPage />} />\n'
            '            <Route path="intelligence/decisions" element={<IntelligenceDecisionsPage />} />\n'
        ) + s[m + len('<Route path="intelligence" element={<IntelligenceSettingsPage />} />'):]
    app.write_text(s, encoding="utf-8")
    print("App.tsx: added /intelligence/decisions route")

# 5. Test
(FE / "pages" / "IntelligenceDecisionsPage.test.tsx").write_text('''import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter } from "react-router-dom";
import { IntelligenceDecisionsPage } from "./IntelligenceDecisionsPage";

vi.mock("../auth/useMe", () => ({
  useMe: () => ({
    data: {
      id: "u1", username: "admin", role: "payroll_admin",
      employee_id: null,
      permissions: ["intelligence_view", "intelligence_manage"],
      must_change_password: false, default_timezone: null,
    },
    isLoading: false, isError: false,
  }),
}));

function jr(body: unknown, s = 200): Response {
  return new Response(JSON.stringify(body), {
    status: s, headers: { "Content-Type": "application/json" },
  });
}
function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  if (input instanceof Request) return input.url;
  return String(input);
}
function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <MemoryRouter initialEntries={["/intelligence/decisions"]}>
          <IntelligenceDecisionsPage />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const DECISION = {
  id: "d1", employee_id: "e1", workflow: "leave_decision",
  source_type: "leave_request", source_id: "s1",
  decision_type: "recommendation", initiator_type: "human",
  initiator_user_id: "u1",
  company_default_mode: "traditional", effective_workflow_mode: "traditional",
  workflow_override_mode: null, execution_status: "pending",
  created_at: "2026-11-07T09:00:00Z",
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("IntelligenceDecisionsPage", () => {
  it("renders empty state when no records", async () => {
    global.fetch = vi.fn(async () => jr({ items: [], next_cursor: null, total: null }));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/No decision records yet/i)).toBeInTheDocument(),
    );
  });

  it("renders a row for each decision", async () => {
    global.fetch = vi.fn(async () => jr({ items: [DECISION], next_cursor: null }));
    renderPage();
    await waitFor(() => expect(screen.getByTestId("decisions-table")).toBeInTheDocument());
    expect(screen.getByText("leave_decision")).toBeInTheDocument();
  });

  it("filters trigger refetch with workflow param", async () => {
    const calls: string[] = [];
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const u = urlOf(input);
      calls.push(u);
      return jr({ items: [DECISION], next_cursor: null });
    });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("decisions-filter-workflow")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("decisions-filter-workflow"), {
      target: { value: "leave_decision" },
    });
    await waitFor(() => {
      expect(calls.some((u) => u.includes("workflow=leave_decision"))).toBe(true);
    }, { timeout: 1500 });
  });

  it("opens drawer and shows snapshot on View", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const u = urlOf(input);
      if (u.includes("/decisions/d1/verify")) return jr({ valid: true, decision_id: "d1" });
      if (u.includes("/decisions/d1")) {
        return jr({
          ...DECISION,
          policy_version: null, statutory_version: null,
          recommendation: { action: "approve" },
          explanation: "Sufficient balance",
          audit_id: "a1",
          evidence_snapshot_id: "snap1",
          snapshot: {
            id: "snap1", decision_id: "d1",
            created_at: "2026-11-07T09:00:00Z",
            schema_version: 1,
            payload: { days: 2 },
            sha256_hex: "abc123",
          },
        });
      }
      return jr({ items: [DECISION], next_cursor: null });
    });
    renderPage();
    await waitFor(() => expect(screen.getByText("leave_decision")).toBeInTheDocument());
    fireEvent.click(screen.getByText("View"));
    await waitFor(() => {
      expect(screen.getByText(/Snapshot integrity verified/i)).toBeInTheDocument();
    }, { timeout: 1500 });
  });
});
''', encoding="utf-8")
print("wrote IntelligenceDecisionsPage.test.tsx")