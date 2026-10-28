'''Pure rate-rule helpers (Chapter 2A). No DB access.'''
from __future__ import annotations

from datetime import date
from typing import Iterable

from app.core.errors import AppError


class NoApplicableRateRule(AppError):
    def __init__(self, message: str) -> None:
        super().__init__('setup_error', message, 500)


def validate_tier_structure(rules: Iterable) -> None:
    sorted_rules = sorted(rules, key=lambda r: r.tier)
    if not sorted_rules:
        return
    expected = 1
    prev_up_to = 0
    last = len(sorted_rules) - 1
    for i, r in enumerate(sorted_rules):
        if r.tier != expected:
            raise AppError('invalid_tier_structure', f'tiers must be contiguous from 1; expected {expected}, got {r.tier}', 400)
        if r.tier_up_to_minutes is None:
            if i != last:
                raise AppError('invalid_tier_structure', 'only the highest tier may have tier_up_to_minutes=null', 400)
        else:
            if r.tier_up_to_minutes <= prev_up_to:
                raise AppError('invalid_tier_structure', f'tier_up_to_minutes must strictly increase; {r.tier_up_to_minutes} not greater than {prev_up_to}', 400)
            prev_up_to = r.tier_up_to_minutes
        expected += 1
    if sorted_rules[-1].tier_up_to_minutes is not None:
        raise AppError('invalid_tier_structure', 'the highest tier must have tier_up_to_minutes=null', 400)


def validate_period_non_overlap(proposed_from: date, proposed_to, existing_periods):
    for ex_from, ex_to in existing_periods:
        if (proposed_to is None or ex_from <= proposed_to) and (ex_to is None or proposed_from <= ex_to):
            raise AppError('overlapping_rate_rule', 'period overlaps with an existing rule', 409, {'existing_from': ex_from.isoformat(), 'existing_to': ex_to.isoformat() if ex_to else None})


def find_rule_for_minute(rules, minute_position: int):
    sorted_rules = sorted(rules, key=lambda r: r.tier)
    if not sorted_rules:
        raise NoApplicableRateRule('no rate rules exist for this key')
    for r in sorted_rules:
        if r.tier_up_to_minutes is None:
            return r
        if minute_position <= r.tier_up_to_minutes:
            return r
    raise NoApplicableRateRule(f'no rate rule covers minute position {minute_position}')

# END OF FILE
