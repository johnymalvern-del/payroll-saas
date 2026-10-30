import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { AttendanceSheetPage } from "./AttendanceSheetPage";

function jr(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function setupMock(sheetItems: unknown[]): void {
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/v1/attendance/sheet")) {
      return jr({ items: sheetItems, next_cursor: null });
    }
    if (
      url.includes("/api/v1/branches") ||
      url.includes("/api/v1/sites") ||
      url.includes("/api/v1/departments")
    ) {
      return jr({ items: [], next_cursor: null });
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <AttendanceSheetPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

const SAMPLE_CELL = {
  work_date: "2025-06-01",
  status: "worked",
  worked_minutes: 480,
  normal_minutes: 480,
  overtime_minutes: 0,
  flags: [],
  open_exception_count: 0,
  locked: false,
  reviewed: false,
};

const SAMPLE_EMPLOYEE = {
  employee_id: "e1",
  employee_code: "EMP001",
  employee_name: "Ada Lovelace",
  site_id: null,
  department_id: null,
  days: [SAMPLE_CELL],
};

describe("AttendanceSheetPage", () => {
  beforeEach(() => {
    setupMock([SAMPLE_EMPLOYEE]);
  });

  it("renders the title and employee row from the sheet", async () => {
    renderPage();
    expect(screen.getByText("Attendance")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
      expect(screen.getByText("EMP001")).toBeInTheDocument();
    });
  });

  it("shows empty text when sheet returns no employees", async () => {
    setupMock([]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByText(/no employees match these filters/i),
      ).toBeInTheDocument();
    });
  });

  it("renders a status badge for a worked cell", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("worked")).toBeInTheDocument();
    });
  });

  it("shows an error message when sheet fetch fails", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/v1/attendance/sheet")) {
        return jr({ error: { code: "boom" } }, 500);
      }
      return jr({ items: [], next_cursor: null });
    }) as unknown as typeof fetch;
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByText(/could not load the attendance sheet/i),
      ).toBeInTheDocument();
    });
  });
});
