from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FormulaInfo(BaseModel):
    code: str
    description: str
    verified: bool
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None


class ReadinessOut(BaseModel):
    items: list[FormulaInfo]
    all_acknowledged: bool


class AcknowledgeOut(BaseModel):
    code: str
    acknowledged: bool
    acknowledged_at: datetime

# END OF FILE
