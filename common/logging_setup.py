"""Structured (JSON-lines) logging so pipeline logs are queryable in any log stack."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Anything passed via logger.info("...", extra={...}) becomes a top-level field.
        payload.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    root = logging.getLogger()
    if not getattr(root, "_mci_configured", False):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.handlers[:] = [handler]
        root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
        root._mci_configured = True  # type: ignore[attr-defined]
    return logging.getLogger(name)
