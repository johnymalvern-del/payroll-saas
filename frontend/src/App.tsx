import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { AppShell } from "./shell/AppShell";
import { AdjustmentsPage } from "./pages/AdjustmentsPage";
import { AttendanceSheetPage } from "./pages/AttendanceSheetPage";
import { ClockInPage } from "./pages/ClockInPage";
import { DevicesPage } from "./pages/setup/DevicesPage";
import { IntelligenceSettingsPage } from "./pages/setup/IntelligenceSettingsPage";
import { IntelligenceDecisionsPage } from "./pages/IntelligenceDecisionsPage";
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
import { PayslipSoFarPage } from "./pages/PayslipSoFarPage";
import { SalaryStructuresPage } from "./pages/SalaryStructuresPage";
import { SalaryStructureDetailPage } from "./pages/SalaryStructureDetailPage";
import { SalarySheetPage } from "./pages/SalarySheetPage";
import { EmployeePayrollPage } from "./pages/EmployeePayrollPage";
import { MyLeavePage } from "./pages/MyLeavePage";
import { MyLeaveHistoryPage } from "./pages/MyLeaveHistoryPage";
import { LeaveRequestDetailPage } from "./pages/LeaveRequestDetailPage";
import { LeaveAdminPage } from "./pages/LeaveAdminPage";
import { MyApprovalsPage } from "./pages/MyApprovalsPage";
import { LeaveBalancesAdminPage } from "./pages/LeaveBalancesAdminPage";
import { LeaveTypesAdminPage } from "./pages/LeaveTypesAdminPage";
import { LeaveCalendarPage } from "./pages/LeaveCalendarPage";

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
          <Route path="leave" element={<MyLeavePage />} />
          <Route path="leave/history" element={<MyLeaveHistoryPage />} />
          <Route path="leave/requests/:id" element={<LeaveRequestDetailPage />} />
          <Route path="leave/admin" element={<LeaveAdminPage />} />
          <Route path="leave/approvals" element={<MyApprovalsPage />} />
          <Route path="leave/balances-admin" element={<LeaveBalancesAdminPage />} />
          <Route path="leave/types-admin" element={<LeaveTypesAdminPage />} />
          <Route path="leave/calendar" element={<LeaveCalendarPage />} />
          <Route path="setup/devices" element={<DevicesPage />} />
          <Route path="payroll/pay-periods" element={<PayPeriodsPage />} />
          <Route path="payroll/pay-periods/:id" element={<PayPeriodDetailPage />} />
          <Route path="payroll/pay-periods/:id/salary-sheet" element={<SalarySheetPage />} />
          <Route path="payroll/pay-periods/:id/payslip-so-far/:employeeId" element={<PayslipSoFarPage />} />
          <Route path="payroll/change-requests" element={<ChangeRequestsPage />} />
          <Route path="payroll/salary-structures" element={<SalaryStructuresPage />} />
          <Route path="payroll/salary-structures/:groupId" element={<SalaryStructureDetailPage />} />
          <Route path="payroll/employee-payroll" element={<EmployeePayrollPage />} />
          <Route path="payroll/employee-payroll/:employeeId" element={<EmployeePayrollPage />} />
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
            <Route path="intelligence" element={<IntelligenceSettingsPage />} />
            <Route path="intelligence/decisions" element={<IntelligenceDecisionsPage />} />
          </Route>
          <Route path="payslips" element={<OwnPayslipsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}