import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { AuthProvider, useAuth } from "./AuthContext";
import { ProtectedRoute } from "./ProtectedRoute";
import { setTenantSlug } from "../api/tenant";

function Probe() {
  const { status, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <button onClick={() => void login("user", "pass")}>do-login</button>
      <button onClick={() => void logout()}>do-logout</button>
    </div>
  );
}

function ProtectedChild() {
  return <div data-testid="protected-child">protected</div>;
}

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
    },
  });
}

function WithProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={makeClient()}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

function loginResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function meResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const ME_PAYLOAD = {
  id: "00000000-0000-0000-0000-000000000001",
  username: "user",
  role: "employee",
  employee_id: null,
  permissions: ["self_view", "self_submit", "attendance_view", "org_view"],
  must_change_password: false,
};

describe("AuthProvider", () => {
  beforeEach(() => {
    setTenantSlug("demo");
    localStorage.clear();
    sessionStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts unauthenticated", () => {
    render(
      <WithProviders>
        <Probe />
      </WithProviders>,
    );
    expect(screen.getByTestId("status").textContent).toBe("unauthenticated");
  });

  it("stores the token in memory only, never localStorage or sessionStorage", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/auth/login")) {
        return loginResponse({ access_token: "tok" });
      }
      if (url.endsWith("/auth/me")) {
        return meResponse(ME_PAYLOAD);
      }
      return new Response("{}", { status: 200 });
    }) as unknown as typeof fetch;

    render(
      <WithProviders>
        <Probe />
      </WithProviders>,
    );
    fireEvent.click(screen.getByText("do-login"));
    await waitFor(() =>
      expect(screen.getByTestId("status").textContent).toBe("authenticated"),
    );
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("surfaces login failure and stays unauthenticated", async () => {
    global.fetch = vi.fn(async () =>
      loginResponse(
        { error: { code: "invalid_credentials", message: "Bad credentials" } },
        401,
      ),
    ) as unknown as typeof fetch;

    render(
      <WithProviders>
        <Probe />
      </WithProviders>,
    );
    fireEvent.click(screen.getByText("do-login"));
    await waitFor(() =>
      expect(screen.getByTestId("status").textContent).toBe("unauthenticated"),
    );
  });

  it("clears the token on logout", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/auth/login")) {
        return loginResponse({ access_token: "tok" });
      }
      if (url.endsWith("/auth/me")) {
        return meResponse(ME_PAYLOAD);
      }
      return new Response("{}", { status: 200 });
    }) as unknown as typeof fetch;

    render(
      <WithProviders>
        <Probe />
      </WithProviders>,
    );
    fireEvent.click(screen.getByText("do-login"));
    await waitFor(() =>
      expect(screen.getByTestId("status").textContent).toBe("authenticated"),
    );
    fireEvent.click(screen.getByText("do-logout"));
    await waitFor(() =>
      expect(screen.getByTestId("status").textContent).toBe("unauthenticated"),
    );
  });
});

describe("ProtectedRoute", () => {
  it("redirects unauthenticated users to /login", () => {
    global.fetch = vi.fn(async () =>
      new Response("{}", { status: 200 }),
    ) as unknown as typeof fetch;

    render(
      <WithProviders>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route
              path="/login"
              element={<div data-testid="login-page">login</div>}
            />
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <ProtectedChild />
                </ProtectedRoute>
              }
            />
          </Routes>
        </MemoryRouter>
      </WithProviders>,
    );
    expect(screen.getByTestId("login-page")).toBeInTheDocument();
    expect(screen.queryByTestId("protected-child")).not.toBeInTheDocument();
  });
});
