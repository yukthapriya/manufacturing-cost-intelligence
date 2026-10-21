"""Land one day's source extracts into the raw landing zone (S3/MinIO or a local folder).

In production the source systems drop files into SOURCE_URI themselves; this step
copies the partitions for one business date into RAW_URI, the immutable landing zone
the loader reads from. Copying is idempotent (same key, same bytes).

    python -m ingestion.land --date 2025-03-04
"""

from __future__ import annotations

import argparse
import sys

from common.config import raw_uri, source_uri
from common.logging_setup import get_logger
from common.storage import LocalStorage, open_storage
from ingestion.load import parse_key

log = get_logger("ingestion.land")


def land(date: str | None, src_uri: str | None = None, dst_uri: str | None = None) -> int:
    """Copy one date's partitions (or every partition when date is None, for backfills)."""
    src = open_storage(src_uri or source_uri())
    dst = open_storage(dst_uri or raw_uri())
    keys = [k for k in src.list() if (p := parse_key(k)) and (date is None or p[1] == date)]
    for k in keys:
        if isinstance(src, LocalStorage) and isinstance(dst, LocalStorage):
            dst.copy_from(src, k)
        else:
            dst.write_bytes(k, src.read_bytes(k))
    log.info("landed partitions", extra={"date": date, "files": len(keys), "dst": dst.uri})
    return len(keys)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--date")
    g.add_argument("--all", action="store_true", help="land every partition (backfill)")
    ap.add_argument("--src", default=None)
    ap.add_argument("--dst", default=None)
    args = ap.parse_args(argv)
    land(None if args.all else args.date, args.src, args.dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
