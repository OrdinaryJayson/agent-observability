"""Read root .env without overriding process environment (including test settings)."""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env", override=False)


def database_url() -> str | URL:
    if value := os.getenv("DATABASE_URL"):
        return value
    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("Set POSTGRES_PASSWORD or DATABASE_URL in root .env")
    return URL.create(
        "postgresql+psycopg",
        username=os.getenv("POSTGRES_USER", "agent_user"),
        password=password,
        host="localhost",
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "agent_observability"),
    )


def cors_origins() -> list[str]:
    return [
        s.strip()
        for s in os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if s.strip()
    ]
