"""Enforce public query names, including endpoints that accept no filters."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel


def validate_query_names(request: Request):
    allowed = set()
    for field in request.scope["route"].dependant.query_params:
        model = field.type_
        if isinstance(model, type) and issubclass(model, BaseModel):
            allowed.update(f.alias or name for name, f in model.model_fields.items())
        else:
            allowed.add(field.alias)
    unknown = set(request.query_params) - allowed
    if unknown:
        raise RequestValidationError(
            [
                {"type": "extra_forbidden", "loc": ("query", key)}
                for key in sorted(unknown)
            ]
        )
