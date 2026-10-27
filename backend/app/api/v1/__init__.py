from fastapi import APIRouter

from app.api.v1.auth.router import router as auth_router
from app.api.v1.branches import router as branches_router
from app.api.v1.company.router import router as company_router
from app.api.v1.departments import router as departments_router
from app.api.v1.employees import router as employees_router
from app.api.v1.pay_history import router as pay_history_router
from app.api.v1.register import router as register_router
from app.api.v1.sites import router as sites_router
from app.api.v1.users import router as users_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(register_router)
api_router.include_router(auth_router)
api_router.include_router(company_router)
api_router.include_router(branches_router)
api_router.include_router(sites_router)
api_router.include_router(departments_router)
api_router.include_router(employees_router)
api_router.include_router(pay_history_router)
api_router.include_router(users_router)

# END OF FILE