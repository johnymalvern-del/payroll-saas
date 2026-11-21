/**
 * DayHistory.test.tsx — focused tests for the correction history section.
 *
 * Stage B Batch B. Covers:
 *   1. Renders summary rows when data resolves.
 *   2. Clicking a row's Details toggle expands and shows the JSON snapshots.
 *   3. Empty response shows the empty message; error response shows the
 *      error alert.
 *
 * fetchAdjustmentHistory is mocked at the client boundary. The component
 * is mounted inside QueryClientProvider + MantineProvider as in the other
 * AttendanceSheet tests.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { DayHistory } from "./DayHistory";
import type { AdjustmentHistoryRow } from "../../api/adjustments";

if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {};
}

const fetchHistoryMock = vi.fn();

vi.mock("../../api/adjustments", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/adjustments")>(
      "../../api/adjustments",
    );
  return {
    ...actual,
    fetchAdjustmentHistory: (...args: unknown[]) => fetchHistoryMock(...args),
  };
});

const ROW: AdjustmentHistoryRow = {
  id: "adj-1",
  employee_id: "emp-1",
  work_date: "2024-05-15",
  outcome: "worked",
  time_in: "2024-05-15T08:00:00.000Z",
  time_out: "2024-05-15T16:30:00.000Z",
  minutes: 510,
  reason_code: "forgot_clock",
  note: "HR correction after employee forgot to clock out",
  batch_id: null,
  created_by: "user-1",
  created_by_name: "Jane Manager",
  created_at: "2024-05-15T12:00:00.000Z",
  old_value: { id: "d1", status: "absent", worked_minutes: 0 },
  new_value: { day: { id: "d1", status: "worked", worked_minutes: 510 } },
};

function wrap(children: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>{children}</MantineProvider>
    </QueryClientProvider>
  );
}

function renderComponent() {
  return render(
    wrap(<DayHistory employeeId="emp-1" workDate="2024-05-15" />),
  );
}

beforeEach(() => {
  fetchHistoryMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DayHistory", () => {
  it("renders summary rows when data resolves", async () => {
    fetchHistoryMock.mockResolvedValueOnce({ items: [ROW] });
    renderComponent();

    // Expand the accordion.
    fireEvent.click(screen.getByTestId("day-history-toggle"));

    await waitFor(() => {
      expect(screen.getByTestId("day-history-list")).toBeInTheDocument();
    });
    const row = screen.getByTestId("day-history-row-adj-1");
    expect(row).toBeInTheDocument();
    expect(row.textContent).toMatch(/worked/);
    expect(row.textContent).toMatch(/forgot_clock/);
    expect(row.textContent).toMatch(/Jane Manager/);
    expect(row.textContent).toMatch(/absent/);
  });

  it("expands snapshot details on toggle click", async () => {
    fetchHistoryMock.mockResolvedValueOnce({ items: [ROW] });
    renderComponent();

    fireEvent.click(screen.getByTestId("day-history-toggle"));
    await waitFor(() => {
      expect(screen.getByTestId("day-history-list")).toBeInTheDocument();
    });

    // Details should not yet be visible.
    expect(
      screen.queryByTestId("day-history-details-adj-1"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("day-history-toggle-adj-1"));

    await waitFor(() => {
      expect(screen.getByTestId("day-history-details-adj-1")).toBeInTheDocument();
    });
    const oldBlock = screen.getByTestId("day-history-old-adj-1");
    const newBlock = screen.getByTestId("day-history-new-adj-1");
    expect(oldBlock.textContent).toMatch(/"status": "absent"/);
    expect(newBlock.textContent).toMatch(/"status": "worked"/);
    expect(newBlock.textContent).toMatch(/"worked_minutes": 510/);
  });

  it("renders empty state when there are no rows", async () => {
    fetchHistoryMock.mockResolvedValueOnce({ items: [] });
    renderComponent();

    fireEvent.click(screen.getByTestId("day-history-toggle"));
    await waitFor(() => {
      expect(screen.getByTestId("day-history-empty")).toBeInTheDocument();
    });
  });

  it("renders error state when the fetch fails", async () => {
    fetchHistoryMock.mockRejectedValueOnce(new Error("boom"));
    renderComponent();

    fireEvent.click(screen.getByTestId("day-history-toggle"));
    await waitFor(() => {
      expect(screen.getByTestId("day-history-error")).toBeInTheDocument();
    });
  });
});