import { afterEach, describe, expect, it } from "vitest";
import { DEFAULT_SITE_TZ, getSiteTz, setSiteTz } from "../config";
import { applyMeSiteTz, type Me } from "../../auth/useMe";

const BASE_ME: Me = {
  id: "u1",
  username: "u",
  role: "employee",
  employee_id: null,
  permissions: [],
  must_change_password: false,
  default_timezone: "Europe/London",
};

afterEach(() => {
  setSiteTz(null);
});

describe("site timezone", () => {
  it("defaults to DEFAULT_SITE_TZ", () => {
    expect(getSiteTz()).toBe(DEFAULT_SITE_TZ);
  });

  it("setSiteTz sets a non-empty tz", () => {
    setSiteTz("Europe/London");
    expect(getSiteTz()).toBe("Europe/London");
  });

  it("setSiteTz(null) resets to default", () => {
    setSiteTz("Europe/London");
    setSiteTz(null);
    expect(getSiteTz()).toBe(DEFAULT_SITE_TZ);
  });

  it("applyMeSiteTz reads default_timezone", () => {
    applyMeSiteTz(BASE_ME);
    expect(getSiteTz()).toBe("Europe/London");
  });

  it("applyMeSiteTz(null) resets", () => {
    setSiteTz("Europe/London");
    applyMeSiteTz(null);
    expect(getSiteTz()).toBe(DEFAULT_SITE_TZ);
  });

  it("applyMeSiteTz with null default_timezone resets", () => {
    setSiteTz("Europe/London");
    applyMeSiteTz({ ...BASE_ME, default_timezone: null });
    expect(getSiteTz()).toBe(DEFAULT_SITE_TZ);
  });
});
