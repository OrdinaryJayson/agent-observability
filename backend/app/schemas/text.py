"""Validation shared by B's PostgreSQL text inputs."""

from typing import Annotated

from pydantic import AfterValidator


def database_text(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Text must not contain a zero byte")
    return value


DatabaseText = Annotated[str, AfterValidator(database_text)]
