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


# Canonical codes (subset; more land in 004a-iii for UIF/SDL/pipeline)
STATUTORY_TABLE_MISSING = "statutory_table_missing"
STATUTORY_TABLE_EXPIRED = "statutory_table_expired"
STATUTORY_TABLE_INVALID = "statutory_table_invalid"
AGE_REFERENCE_DATE_UNSET = "age_reference_date_unset"
MISSING_DATE_OF_BIRTH = "missing_date_of_birth"
TAX_METHOD_UNSUPPORTED = "tax_method_unsupported"

# END OF FILE
