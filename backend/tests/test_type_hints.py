
"""Every type used in a FastAPI dependency signature must resolve at runtime.

Because all modules use `from __future__ import annotations`, every annotation
is a string until `typing.get_type_hints` (or a pydantic schema builder)
resolves it against the module's globals. If a module uses a name in an
annotation but does not import that name at runtime, the class loads fine but
any consumer that introspects the annotation (FastAPI, pydantic) crashes with
a NameError at request time - or, worse, at route-registration time, which is
what produced the tenant-context / uuid failure in 1C.2.

This test calls get_type_hints on every dataclass and pydantic BaseModel in
`app` and every ORM class in the tenant and control model packages. The first
failure names the class and the missing symbol.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import typing

import pytest
from pydantic import BaseModel

import app


def _iter_app_modules():
    for modinfo in pkgutil.walk_packages(app.__path__, prefix="app."):
        try:
            yield importlib.import_module(modinfo.name)
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"Failed to import {modinfo.name}: {exc}") from exc


def _candidate_classes():
    seen = set()
    for mod in _iter_app_modules():
        for _name, obj in inspect.getmembers(mod, inspect.isclass):
            if obj in seen:
                continue
            seen.add(obj)
            if obj.__module__ != mod.__name__:
                continue
            if inspect.isabstract(obj):
                continue
            # Only classes whose annotations matter for FastAPI/pydantic
            if issubclass(obj, BaseModel) or hasattr(obj, "__dataclass_fields__"):
                yield mod.__name__, obj
            # ORM models: subclasses of DeclarativeBase
            from app.db.base import Base
            if issubclass(obj, Base):
                yield mod.__name__, obj


def test_all_type_hints_resolve() -> None:
    failures: list[str] = []
    for mod_name, cls in _candidate_classes():
        try:
            typing.get_type_hints(cls)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{mod_name}.{cls.__name__}: {type(exc).__name__}: {exc}")
    assert not failures, (
        "These classes have annotation names that do not resolve at runtime. "
        "Add the missing import to the module that defines the class.\n\n"
        + "\n".join(failures)
    )