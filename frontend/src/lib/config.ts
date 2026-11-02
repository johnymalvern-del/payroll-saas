export const DEFAULT_SITE_TZ = "Africa/Johannesburg";

let currentSiteTz: string = DEFAULT_SITE_TZ;

export function getSiteTz(): string {
  return currentSiteTz;
}

export function setSiteTz(tz: string | null | undefined): void {
  const trimmed = (tz ?? "").trim();
  currentSiteTz = trimmed.length > 0 ? trimmed : DEFAULT_SITE_TZ;
}
