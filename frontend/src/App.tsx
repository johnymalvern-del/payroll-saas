import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { AppShell } from "./shell/AppShell";
import { AdjustmentsPage } from "./pages/AdjustmentsPage";
import { AttendanceSheetPage } from "./pages/AttendanceSheetPage";
import { ExceptionsPage } from "./pages/ExceptionsPage";
import { ForcePasswordChangePage } from "./pages/ForcePasswordChangePage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/change-password"
          element={
            <ProtectedRoute>
              <ForcePasswordChangePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <AppShell />
            </ProtectedRoute>
          }
        >
          <Route index element={<HomePage />} />
          <Route path="attendance" element={<AttendanceSheetPage />} />
          <Route path="attendance/exceptions" element={<ExceptionsPage />} />
          <Route path="attendance/adjustments" element={<AdjustmentsPage />} />
          <Route
            path="employees"
            element={<PlaceholderPage title="Employees" phase="F-4" />}
          />
          <Route
            path="payroll/pay-periods"
            element={<PlaceholderPage title="Pay periods" phase="F-7" />}
          />
          <Route
            path="payroll/change-requests"
            element={<PlaceholderPage title="Change requests" phase="F-6" />}
          />
          <Route
            path="audit-log"
            element={<PlaceholderPage title="Audit log" phase="F-8" />}
          />
          <Route
            path="setup"
            element={<PlaceholderPage title="Setup" phase="F-5" />}
          />
          <Route
            path="payslips"
            element={<PlaceholderPage title="My payslips" phase="F-7" />}
          />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}