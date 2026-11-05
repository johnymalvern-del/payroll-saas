import { describe, expect, it } from "vitest";
import { toCsv } from "./csv";

describe("toCsv", () => {
  it("empty rows yields empty string", () => {
    expect(toCsv([])).toBe("");
  });

  it("joins simple rows with CRLF", () => {
    expect(toCsv([["a", "b"], ["c", "d"]])).toBe("a,b\r\nc,d");
  });

  it("quotes cells containing commas", () => {
    expect(toCsv([["a,b", "c"]])).toBe('"a,b",c');
  });

  it("escapes quotes inside cells", () => {
    expect(toCsv([['he said "hi"', "x"]])).toBe('"he said ""hi""",x');
  });

  it("quotes cells containing newlines", () => {
    expect(toCsv([["line1\nline2"]])).toBe('"line1\nline2"');
  });

  it("nulls become empty", () => {
    expect(toCsv([[null as unknown as string, "b"]])).toBe(",b");
  });
});
