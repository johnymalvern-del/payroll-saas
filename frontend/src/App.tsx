import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { AppShell } from "./shell/AppShell";
import { AdjustmentsPage } from "./pages/AdjustmentsPage";
import { AttendanceSheetPage } from "./pages/AttendanceSheetPage";
import { ClockInPage } from "./pages/ClockInPage";
import { DevicesPage } from "./pages/setup/DevicesPage";
import { PublicHolidaysPage } from "./pages/setup/PublicHolidaysPage";
import { WorkPatternsPage } from "./pages/setup/WorkPatternsPage";
import { ShiftsPage } from "./pages/setup/ShiftsPage";
import { DepartmentsPage } from "./pages/setup/DepartmentsPage";
import { BranchesPage } from "./pages/setup/BranchesPage";
import { SitesPage } from "./pages/setup/SitesPage";
import { SetupLayout } from "./pages/setup/SetupLayout";
import { AuditLogPage } from "./pages/AuditLogPage";
import { ChangeRequestsPage } from "./pages/ChangeRequestsPage";
import { EmployeesPage } from "./pages/EmployeesPage";
import { ExceptionsPage } from "./pages/ExceptionsPage";
import { ForcePasswordChangePage } from "./pages/ForcePasswordChangePage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { PayPeriodsPage } from "./pages/PayPeriodsPage";
import { OwnPayslipsPage } from "./pages/OwnPayslipsPage";
import { PayPeriodDetailPage } from "./pages/PayPeriodDetailPage";

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
          <Route path="employees" element={<EmployeesPage />} />
          <Route path="clock-in" element={<ClockInPage />} />
          <Route path="setup/devices" element={<DevicesPage />} />
          <Route path="payroll/pay-periods" element={<PayPeriodsPage />} />
          <Route path="payroll/pay-periods/:id" element={<PayPeriodDetailPage />} />
          <Route path="payroll/change-requests" element={<ChangeRequestsPage />} />
          <Route path="audit-log" element={<AuditLogPage />} />
          <Route path="setup" element={<SetupLayout />}>
            <Route index element={<SitesPage />} />
            <Route path="sites" element={<SitesPage />} />
            <Route path="branches" element={<BranchesPage />} />
            <Route path="departments" element={<DepartmentsPage />} />
            <Route path="shifts" element={<ShiftsPage />} />
            <Route path="work-patterns" element={<WorkPatternsPage />} />
            <Route path="public-holidays" element={<PublicHolidaysPage />} />
            <Route path="devices" element={<DevicesPage />} />
          </Route>
          <Route path="payslips" element={<OwnPayslipsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
