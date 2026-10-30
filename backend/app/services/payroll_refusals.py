"""Payroll refusals (Chapter 4).

Raised by services when a computation cannot proceed because a statutory
table, a tenant setting, or a required employee field is missing. Endpoints
translate these into HTTP responses with the code and status supplied here.
"""
from __future__ import annotations


class PayrollRefusal(Exception):
    def __init__(self, code: str, message: str, http_status: int = 409) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


# Statutory data
STATUTORY_TABLE_MISSING = "statutory_table_missing"
STATUTORY_TABLE_EXPIRED = "statutory_table_expired"
STATUTORY_TABLE_INVALID = "statutory_table_invalid"

# Employee field / setting
AGE_REFERENCE_DATE_UNSET = "age_reference_date_unset"
MISSING_DATE_OF_BIRTH = "missing_date_of_birth"
MISSING_CONTRACTED_HOURS = "missing_contracted_hours"

# Tenant settings
SDL_APPLIES_UNSET = "sdl_applies_unset"

# Specific statutory tables
UIF_CEILING_MISSING = "uif_ceiling_missing"
RETIREMENT_LIMIT_MISSING = "retirement_limit_missing"

# Method gate
TAX_METHOD_UNSUPPORTED = "tax_method_unsupported"

# F7: legal-order deductions never deferred
DEDUCTION_EXCEEDS_FLOOR_LEGAL_ORDER = "deduction_exceeds_floor_legal_order"

# END OF FILE
