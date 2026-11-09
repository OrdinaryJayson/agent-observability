"""Run backend tests against a separate *_test database; never create/drop databases."""

import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import database_url  # noqa: E402


def main() -> int:
    development = make_url(database_url())
    test_url = make_url(
        os.getenv("TEST_DATABASE_URL")
        or development.set(database=f"{development.database}_test")
    )
    if test_url == development or not (test_url.database or "").endswith("_test"):
        raise RuntimeError("Tests must use a separate *_test database")
    env = os.environ.copy()
    env["TEST_DATABASE_URL"] = test_url.render_as_string(hide_password=False)
    return subprocess.call(
        [sys.executable, "-m", "pytest", "-q", *sys.argv[1:]],
        cwd=ROOT / "backend",
        env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
