import { describe, expect, it } from "vitest";
import { mapErrorCode } from "./errors";

describe("mapErrorCode", () => {
  it("maps known codes to human messages", () => {
    expect(mapErrorCode("record_changed")).toContain("Reload");
  });

  it("returns the generic fallback for unknown codes", () => {
    expect(mapErrorCode("unknown_thing")).toBe(
      "Something went wrong. Please try again.",
    );
  });

  it("uses the supplied fallback message when provided", () => {
    expect(mapErrorCode("unknown_thing", "Try again")).toBe("Try again");
  });

  it("handles undefined code", () => {
    expect(mapErrorCode(undefined)).toBe(
      "Something went wrong. Please try again.",
    );
  });

  it("maps holiday_calendar_missing to a specific message", () => {
    const out = mapErrorCode("holiday_calendar_missing", "fallback");
    expect(out).not.toBe("fallback");
    expect(out).toMatch(/holiday|calendar/i);
  });

  it("maps company_missing to a specific message", () => {
    const out = mapErrorCode("company_missing", "fallback");
    expect(out).not.toBe("fallback");
    expect(out).toMatch(/company/i);
  });

  it("maps bulk_validation_failed to a specific message", () => {
    const out = mapErrorCode("bulk_validation_failed", "fallback");
    expect(out).not.toBe("fallback");
    expect(out).toMatch(/validation|nothing was applied/i);
  });

  it("maps token_mismatch to a specific message", () => {
    const out = mapErrorCode("token_mismatch", "fallback");
    expect(out).not.toBe("fallback");
    expect(out).toMatch(/dry run|batch/i);
  });

  it("maps batch_failed to a specific message", () => {
    const out = mapErrorCode("batch_failed", "fallback");
    expect(out).not.toBe("fallback");
    expect(out).toMatch(/batch|nothing was applied/i);
  });
});