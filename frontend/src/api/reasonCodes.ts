import { absoluteUrl, wrappedFetch } from "./client";

export type ReasonCode = {
  code: string;
  label: string;
  requires_note: boolean;
};

type ReasonCodeListOut = {
  items: ReasonCode[];
};

export async function fetchReasonCodes(): Promise<ReasonCode[]> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/attendance/reason-codes"), {
      credentials: "include",
    }),
  );
  if (!res.ok) throw new Error(`http_${res.status}`);
  const body = (await res.json()) as ReasonCodeListOut;
  return body.items ?? [];
}
