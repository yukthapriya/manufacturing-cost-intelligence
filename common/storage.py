"""Storage abstraction over a local folder or an S3 bucket (AWS or MinIO).

URIs look like ``./data/raw`` or ``s3://bucket/optional/prefix``. Keys are always
forward-slash relative paths such as ``material_issues/2025-03-04/material_issues.csv``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    uri: str

    def list(self, prefix: str = "") -> list[str]: ...
    def read_bytes(self, key: str) -> bytes: ...
    def write_bytes(self, key: str, data: bytes) -> None: ...
    def local_path(self, key: str) -> Path | None: ...


class LocalStorage:
    def __init__(self, uri: str) -> None:
        self.uri = uri
        self.root = Path(uri).expanduser().resolve()

    def list(self, prefix: str = "") -> list[str]:
        base = self.root / prefix if prefix else self.root
        if not base.exists():
            return []
        return sorted(p.relative_to(self.root).as_posix() for p in base.rglob("*") if p.is_file())

    def read_bytes(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def write_bytes(self, key: str, data: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)  # atomic within a filesystem

    def copy_from(self, other: LocalStorage, key: str) -> None:
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(other.root / key, dest)

    def local_path(self, key: str) -> Path | None:
        return self.root / key


class S3Storage:
    def __init__(self, uri: str) -> None:
        import boto3  # imported lazily so local runs don't need boto3

        self.uri = uri
        rest = uri.removeprefix("s3://")
        self.bucket, _, self.prefix = rest.partition("/")
        self.prefix = self.prefix.strip("/")
        self.client = boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None)

    def _full(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def list(self, prefix: str = "") -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self._full(prefix)):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                keys.append(key[len(self.prefix) + 1 :] if self.prefix else key)
        return sorted(keys)

    def read_bytes(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=self._full(key))["Body"].read()

    def write_bytes(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=self._full(key), Body=data)

    def local_path(self, key: str) -> Path | None:
        return None


def open_storage(uri: str) -> LocalStorage | S3Storage:
    return S3Storage(uri) if uri.startswith("s3://") else LocalStorage(uri)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
