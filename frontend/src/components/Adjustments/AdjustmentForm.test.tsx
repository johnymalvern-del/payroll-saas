import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import { AdjustmentForm, type AdjustmentFormValues } from "./AdjustmentForm";
import { DEFAULT_SITE_TZ } from "../../lib/config";

if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {};
}

dayjs.extend(utc);
dayjs.extend(timezone);

const CODES = [
  { code: "system_correction", label: "System correction", requires_note: false },
  { code: "forgot_clock", label: "Forgot clock", requires_note: false },
  { code: "other", label: "Other", requires_note: true },
];

function mockCodes() {
  global.fetch = vi.fn(async () =>
    new Response(JSON.stringify({ items: CODES }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  ) as unknown as typeof fetch;
}

function renderForm(onSubmit: (v: AdjustmentFormValues) => void) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <AdjustmentForm workDate="2026-10-15" onSubmit={onSubmit} />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

async function pickReason(label: string) {
  await waitFor(() => {
    const el = screen.getByTestId("adj-reason") as HTMLInputElement;
    expect(el.disabled).toBe(false);
  });
  fireEvent.click(screen.getByTestId("adj-reason"));
  const opt = await screen.findByText(label);
  fireEvent.click(opt);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
  mockCodes();
});

describe("AdjustmentForm", () => {
  it("night shift: time-out earlier than time-in means next calendar day", async () => {
    const onSubmit = vi.fn();
    renderForm(onSubmit);

    fireEvent.change(screen.getByTestId("adj-time-in"), {
      target: { value: "22:00" },
    });
    fireEvent.change(screen.getByTestId("adj-time-out"), {
      target: { value: "06:00" },
    });
    await pickReason("System correction");

    expect(screen.getByTestId("adj-next-day")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("adj-submit"));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const v = onSubmit.mock.calls[0][0] as AdjustmentFormValues;
    expect(v.time_in).not.toBeNull();
    expect(v.time_out).not.toBeNull();
    expect(dayjs(v.time_in).tz(DEFAULT_SITE_TZ).format("HH:mm")).toBe("22:00");
    expect(dayjs(v.time_out).tz(DEFAULT_SITE_TZ).format("HH:mm")).toBe("06:00");
    expect(dayjs(v.time_out).tz(DEFAULT_SITE_TZ).format("YYYY-MM-DD")).toBe(
      dayjs(v.time_in).tz(DEFAULT_SITE_TZ).add(1, "day").format("YYYY-MM-DD"),
    );
  });

  it("day shift: no +1 day indicator when time-out is after time-in", () => {
    renderForm(vi.fn());
    fireEvent.change(screen.getByTestId("adj-time-in"), {
      target: { value: "08:00" },
    });
    fireEvent.change(screen.getByTestId("adj-time-out"), {
      target: { value: "16:30" },
    });
    expect(screen.queryByTestId("adj-next-day")).not.toBeInTheDocument();
  });

  it("requires a reason code", async () => {
    const onSubmit = vi.fn();
    renderForm(onSubmit);
    fireEvent.change(screen.getByTestId("adj-time-in"), {
      target: { value: "08:00" },
    });
    fireEvent.change(screen.getByTestId("adj-time-out"), {
      target: { value: "16:30" },
    });
    fireEvent.click(screen.getByTestId("adj-submit"));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent ?? "").toMatch(/required/i);
  });

  it("reason 'other' requires a note of at least 10 characters", async () => {
    const onSubmit = vi.fn();
    renderForm(onSubmit);
    fireEvent.change(screen.getByTestId("adj-time-in"), {
      target: { value: "08:00" },
    });
    fireEvent.change(screen.getByTestId("adj-time-out"), {
      target: { value: "16:30" },
    });
    await pickReason("Other");
    fireEvent.change(screen.getByTestId("adj-note"), {
      target: { value: "short" },
    });
    fireEvent.click(screen.getByTestId("adj-submit"));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent ?? "").toMatch(
      /at least 10 characters/i,
    );
  });

  it("submits non-other reason without requiring a note", async () => {
    const onSubmit = vi.fn();
    renderForm(onSubmit);
    fireEvent.change(screen.getByTestId("adj-time-in"), {
      target: { value: "08:00" },
    });
    fireEvent.change(screen.getByTestId("adj-time-out"), {
      target: { value: "16:30" },
    });
    await pickReason("Forgot clock");
    fireEvent.click(screen.getByTestId("adj-submit"));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const v = onSubmit.mock.calls[0][0] as AdjustmentFormValues;
    expect(v.reason_code).toBe("forgot_clock");
  });
});
