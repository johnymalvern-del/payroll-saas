from fastapi import APIRouter

from app.api.v1.register import router as register_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(register_router)