"""Entry point: ``tool-service`` (uvicorn). Configuration comes from the environment (see ``settings``)."""

from __future__ import annotations

import logging
import os

import uvicorn

from tool_service.app import create_app
from tool_service.settings import ConfigError, Settings


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        raise SystemExit(f"configuración inválida: {exc}") from None
    uvicorn.run(create_app(settings), host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    run()
