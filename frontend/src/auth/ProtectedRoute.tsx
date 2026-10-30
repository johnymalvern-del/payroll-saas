import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Center, Loader } from "@mantine/core";
import { useAuth } from "./AuthContext";
import { useMe } from "./useMe";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const me = useMe();
  const location = useLocation();

  if (status === "unauthenticated") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (me.isLoading) {
    return (
      <Center h="50vh">
        <Loader />
      </Center>
    );
  }
  if (me.isError || !me.data) {
    return <Navigate to="/login" replace />;
  }
  if (
    me.data.must_change_password &&
    location.pathname !== "/change-password"
  ) {
    return <Navigate to="/change-password" replace />;
  }
  return <>{children}</>;
}
