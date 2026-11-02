import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import { getSiteTz } from "./config";
import { strings } from "./strings";

dayjs.extend(utc);
dayjs.extend(timezone);

export function suggestionSummary(
  sf: Record<string, unknown>,
): string | null {
  const outcome = typeof sf.outcome === "string" ? sf.outcome : null;
  if (!outcome) return null;
  const tin =
    typeof sf.time_in === "string"
      ? dayjs(sf.time_in).tz(getSiteTz()).format("HH:mm")
      : null;
  const tout =
    typeof sf.time_out === "string"
      ? dayjs(sf.time_out).tz(getSiteTz()).format("HH:mm")
      : null;
  if (outcome === "worked" && tin && tout) {
    return `${strings.exceptions.suggestWorked} ${tin}\u2013${tout}`;
  }
  return outcome.replace(/_/g, " ");
}
