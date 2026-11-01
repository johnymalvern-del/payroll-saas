import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import { AdjustmentForm, type AdjustmentFormValues } from "./AdjustmentForm";
import { DEFAULT_SITE_TZ } from "../../lib/config";

dayjs.extend(utc);
dayjs.extend(timezone);

afterEach(() => cleanup());

function renderForm(onSubmit: (v: AdjustmentFormValues) => void) {
  return render(
    <MantineProvider>
      <AdjustmentForm workDate="2026-10-15" onSubmit={onSubmit} />
    </MantineProvider>,
  );
}

describe("AdjustmentForm", () => {
  it("night shift: time-out earlier than time-in means next calendar day", () => {
    const onSubmit = vi.fn();
    renderForm(onSubmit);

    fireEvent.change(screen.getByTestId("adj-time-in"), {
      target: { value: "22:00" },
    });
    fireEvent.change(screen.getByTestId("adj-time-out"), {
      target: { value: "06:00" },
    });
    fireEvent.change(screen.getByTestId("adj-reason"), {
      target: { value: "night_shift" },
    });

    expect(screen.getByTestId("adj-next-day")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("adj-submit"));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const v = onSubmit.mock.calls[0][0] as AdjustmentFormValues;
    expect(v.time_in).not.toBeNull();
    expect(v.time_out).not.toBeNull();
    // Both formatted in site timezone (independent of machine tz).
    expect(dayjs(v.time_in).tz(DEFAULT_SITE_TZ).format("HH:mm")).toBe("22:00");
    expect(dayjs(v.time_out).tz(DEFAULT_SITE_TZ).format("HH:mm")).toBe("06:00");
    // The time-out must land on the NEXT calendar day in site tz.
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

  it("rejects reason_code longer than 40 chars", () => {
    const onSubmit = vi.fn();
    renderForm(onSubmit);

    fireEvent.change(screen.getByTestId("adj-time-in"), {
      target: { value: "08:00" },
    });
    fireEvent.change(screen.getByTestId("adj-time-out"), {
      target: { value: "16:30" },
    });
    fireEvent.change(screen.getByTestId("adj-reason"), {
      target: { value: "x".repeat(41) },
    });
    fireEvent.click(screen.getByTestId("adj-submit"));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent ?? "").toMatch(
      /40 characters/i,
    );
  });
});