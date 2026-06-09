from __future__ import annotations

import logging

import uvicorn

from .app import create_app
from .config import Settings
from .logging_config import configure_logging


def main() -> None:
    settings = Settings.from_env()
    settings.validate()
    configure_logging(settings.log_level)
    app = create_app(settings)
    if settings.http_host in ("0.0.0.0", "::"):
        if not settings.miner_api_key:
            logging.warning(
                "SECURITY WARNING: binding to %s without MINER_API_KEY exposes "
                "all miner endpoints to the network. Set MINER_API_KEY to require "
                "authentication.",
                settings.http_host,
            )
        else:
            logging.warning(
                "binding to %s — ensure firewall rules restrict access. "
                "API key authentication is enabled.",
                settings.http_host,
            )
    logging.info("server starting: host=%s port=%s", settings.http_host, settings.http_port)
    uvicorn.run(
        app,
        host=settings.http_host,
        port=settings.http_port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
