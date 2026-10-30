import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { setAccessToken, setOnUnauthorized } from "../api/client";
import { queryClient } from "../lib/queryClient";
import { meQueryKey } from "./useMe";
import {
  AuthRequestError,
  changePasswordRequest,
  loginRequest,
  logoutRequest,
} from "./api";

export type AuthState = {
  status: "authenticated" | "unauthenticated";
  loginError: string | null;
  busy: boolean;
};

export type AuthContextValue = AuthState & {
  login: (identifier: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
  changePassword: (current: string, next: string) => Promise<boolean>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    status: "unauthenticated",
    loginError: null,
    busy: false,
  });

  useEffect(() => {
    setOnUnauthorized(() => {
      setAccessToken(null);
      queryClient.clear();
      setState({
        status: "unauthenticated",
        loginError: "Session expired. Please sign in again.",
        busy: false,
      });
    });
    return () => setOnUnauthorized(null);
  }, []);

  const login = useCallback(
    async (identifier: string, password: string): Promise<boolean> => {
      setState((s) => ({ ...s, busy: true, loginError: null }));
      try {
        const result = await loginRequest(identifier, password);
        setAccessToken(result.accessToken);
        queryClient.removeQueries({ queryKey: meQueryKey });
        setState({
          status: "authenticated",
          loginError: null,
          busy: false,
        });
        return true;
      } catch (err) {
        const message =
          err instanceof AuthRequestError
            ? err.apiError.message
            : "Sign-in failed";
        setState({
          status: "unauthenticated",
          loginError: message,
          busy: false,
        });
        return false;
      }
    },
    [],
  );

  const logout = useCallback(async (): Promise<void> => {
    await logoutRequest();
    setAccessToken(null);
    queryClient.clear();
    setState({
      status: "unauthenticated",
      loginError: null,
      busy: false,
    });
  }, []);

  const changePassword = useCallback(
    async (current: string, next: string): Promise<boolean> => {
      setState((s) => ({ ...s, busy: true, loginError: null }));
      try {
        await changePasswordRequest({
          currentPassword: current,
          newPassword: next,
        });
        await queryClient.invalidateQueries({ queryKey: meQueryKey });
        setState((s) => ({ ...s, busy: false }));
        return true;
      } catch (err) {
        const message =
          err instanceof AuthRequestError
            ? err.apiError.message
            : "Change password failed";
        setState((s) => ({ ...s, busy: false, loginError: message }));
        return false;
      }
    },
    [],
  );

  return (
    <AuthContext.Provider value={{ ...state, login, logout, changePassword }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
