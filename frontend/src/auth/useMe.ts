import { useQuery } from "@tanstack/react-query";
import { absoluteUrl, wrappedFetch } from "../api/client";
import { useAuth } from "./AuthContext";

export type Me = {
  id: string;
  username: string;
  role: string;
  employee_id: string | null;
  permissions: string[];
  must_change_password: boolean;
};

export const meQueryKey = ["me"] as const;

export async function fetchMe(): Promise<Me> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/auth/me"), { credentials: "include" }),
  );
  if (!res.ok) {
    throw new Error(`/auth/me failed: ${res.status}`);
  }
  return (await res.json()) as Me;
}

export function useMe() {
  const { status } = useAuth();
  return useQuery<Me, Error>({
    queryKey: meQueryKey,
    queryFn: fetchMe,
    enabled: status === "authenticated",
    staleTime: Infinity,
    retry: 1,
  });
}
