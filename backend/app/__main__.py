"""Start the single-instance prototype using API_HOST/API_PORT from root .env."""

import os

import uvicorn

from app.core import config  # noqa: F401 -- load root .env before reading environment

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8000")),
        workers=1,
    )
