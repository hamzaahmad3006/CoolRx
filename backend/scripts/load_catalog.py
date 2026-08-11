"""Load the intervention catalog from CSV into the database.

    python -m scripts.load_catalog                    # validate and load
    python -m scripts.load_catalog --dry-run          # validate only
    python -m scripts.load_catalog --path other.csv

Exits non-zero on any validation failure, so it can gate a deploy.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.config import get_settings
from repositories.base import session_scope
from repositories.catalog import (
    CatalogError,
    assert_catalog_ready,
    load_catalog,
    read_catalog_csv,
)


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        default=settings.catalog_csv_path,
        help=f"CSV to load (default: {settings.catalog_csv_path})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the CSV without writing to the database",
    )
    parser.add_argument(
        "--allow-invalid",
        action="store_true",
        help="Load valid rows and skip invalid ones instead of aborting",
    )
    args = parser.parse_args(argv)

    path = Path(args.path)

    try:
        rows, violations = read_catalog_csv(path)
    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"{path}: {len(rows)} valid row(s), {len(violations)} violation(s)")
    for violation in violations:
        print(f"  - {violation}", file=sys.stderr)

    if not rows:
        print(
            "\nNo valid rows. The catalog must be populated from published cost "
            "and effect-size sources before the optimizer can run; see the header "
            f"comment in {path}.",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        print("dry run — nothing written")
        return 1 if violations else 0

    try:
        with session_scope() as session:
            loaded = load_catalog(session, path, strict=not args.allow_invalid)
            total = assert_catalog_ready(session)
    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"loaded {loaded} row(s); catalog now holds {total} cited entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
