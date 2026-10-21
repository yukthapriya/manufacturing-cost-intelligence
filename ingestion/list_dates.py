"""Print every partition date present under a storage URI, one per line (for backfills/CI).

python -m ingestion.list_dates --src ./data/source_drop
"""

from __future__ import annotations

import argparse

from common.config import source_uri
from common.storage import open_storage
from ingestion.load import parse_key


def list_dates(uri: str, source: str | None = None) -> list[str]:
    return sorted(
        {p[1] for k in open_storage(uri).list() if (p := parse_key(k)) and (source is None or p[0] == source)}
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=None)
    ap.add_argument("--source", default=None, help="only partitions of this source, e.g. material_issues")
    args = ap.parse_args(argv)
    print("\n".join(list_dates(args.src or source_uri(), args.source)))


if __name__ == "__main__":
    main()
