const STORAGE_KEY = "payroll.device_key";

export function getDeviceKey(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setDeviceKey(key: string): boolean {
  try {
    localStorage.setItem(STORAGE_KEY, key);
    return true;
  } catch {
    return false;
  }
}

export function clearDeviceKey(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignored — screen must still work without storage
  }
}
