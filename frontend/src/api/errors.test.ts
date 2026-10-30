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
});
