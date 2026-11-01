let tenantSlug: string | null = null;

const fromEnv = import.meta.env.VITE_TENANT_SLUG;
if (typeof fromEnv === "string" && fromEnv.length > 0) {
  tenantSlug = fromEnv;
}

export function getTenantSlug(): string | null {
  return tenantSlug;
}

export function setTenantSlug(slug: string | null): void {
  tenantSlug = slug && slug.length > 0 ? slug : null;
}
