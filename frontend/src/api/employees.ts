import { absoluteUrl, wrappedFetch } from "./client";

export type EmployeeRef = {
  id: string;
  employee_code: string;
  first_name: string;
  last_name: string;
};

const PAGE_LIMIT = 500;
const MAX_PAGES = 20;

export async function fetchEmployees(): Promise<EmployeeRef[]> {
  const all: EmployeeRef[] = [];
  let cursor: string | null = null;
  let pages = 0;
  for (;;) {
    if (pages >= MAX_PAGES) {
      console.warn(`fetchEmployees: stopped at MAX_PAGES=${MAX_PAGES}`);
      break;
    }
    const qs = new URLSearchParams();
    qs.set("limit", String(PAGE_LIMIT));
    if (cursor) qs.set("cursor", cursor);
    const res = await wrappedFetch(
      new Request(absoluteUrl(`/api/v1/employees?${qs.toString()}`), {
        credentials: "include",
      }),
    );
    if (!res.ok) {
      throw new Error(`http_${res.status}`);
    }
    const body = (await res.json().catch(() => ({}))) as {
      items?: unknown;
      next_cursor?: unknown;
    };
    if (Array.isArray(body.items)) all.push(...(body.items as EmployeeRef[]));
    cursor = typeof body.next_cursor === "string" ? body.next_cursor : null;
    pages += 1;
    if (!cursor) break;
  }
  return all;
}
