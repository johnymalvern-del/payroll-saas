from fastapi import APIRouter

from app.api.v1.audit_log import router as audit_log_router
from app.api.v1.auth.router import router as auth_router
from app.api.v1.branches import router as branches_router
from app.api.v1.company.router import router as company_router
from app.api.v1.departments import router as departments_router
from app.api.v1.devices import router as devices_router
from app.api.v1.employee_work_patterns import router as employee_work_patterns_router
from app.api.v1.employees import router as employees_router
from app.api.v1.import_employees import router as import_employees_router
from app.api.v1.pay_history import router as pay_history_router
from app.api.v1.public_holidays import router as public_holidays_router
from app.api.v1.punches import router as punches_router
from app.api.v1.register import router as register_router
from app.api.v1.shift_rate_rules import router as shift_rate_rules_router
from app.api.v1.shifts import router as shifts_router
from app.api.v1.sites import router as sites_router
from app.api.v1.users import router as users_router
from app.api.v1.work_patterns import router as work_patterns_router

from app.api.v1.attendance import router as attendance_router
from app.api.v1.exceptions import router as exceptions_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(register_router)
api_router.include_router(auth_router)
api_router.include_router(company_router)
api_router.include_router(branches_router)
api_router.include_router(sites_router)
api_router.include_router(departments_router)
api_router.include_router(import_employees_router)
api_router.include_router(employees_router)
api_router.include_router(pay_history_router)
api_router.include_router(users_router)
api_router.include_router(audit_log_router)
api_router.include_router(shifts_router)
api_router.include_router(shift_rate_rules_router)
api_router.include_router(work_patterns_router)
api_router.include_router(employee_work_patterns_router)
api_router.include_router(public_holidays_router)
api_router.include_router(devices_router)
api_router.include_router(punches_router)

# END OF FILE
api_router.include_router(attendance_router)
api_router.include_router(exceptions_router)
