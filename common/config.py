"""Environment-driven configuration. No secrets are hardcoded; see .env.example."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class WarehouseConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str | None

    @property
    def dsn(self) -> str:
        parts = [f"host={self.host}", f"port={self.port}", f"dbname={self.dbname}", f"user={self.user}"]
        if self.password:
            parts.append(f"password={self.password}")
        return " ".join(parts)


def warehouse() -> WarehouseConfig:
    return WarehouseConfig(
        host=_env("WAREHOUSE_HOST", "localhost"),
        port=int(_env("WAREHOUSE_PORT", "5432")),
        dbname=_env("WAREHOUSE_DB", "mfg_cost"),
        user=_env("WAREHOUSE_USER", "postgres"),
        password=_env("WAREHOUSE_PASSWORD"),
    )


def source_uri() -> str:
    return _env("SOURCE_URI", "./data/source_drop")


def raw_uri() -> str:
    return _env("RAW_URI", "./data/raw")


def materiality_usd() -> float:
    """Absolute reconciliation difference above which a break blocks close sign-off."""
    return float(_env("MATERIALITY_USD", "1000"))


def slack_webhook() -> str | None:
    return _env("SLACK_WEBHOOK_URL")
