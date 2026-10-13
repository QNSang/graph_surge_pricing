"""Import the active dataset (data/CURRENT.json) into Postgres and publish recommendation sets.

Usage:
    uv run python scripts/import_dataset.py --from-date 2026-01-01 --to-date 2026-01-02 --provider mock
    uv run python scripts/import_dataset.py --provider precomputed --source ../pipeline/outputs/proposals
Defaults: --from-date = first dataset day, --to-date = --from-date (one day). Re-running is a no-op.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_policy, get_settings  # noqa: E402
from app.db.models import Snapshot  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.ingestion.dataset_loader import last_date, load_active_dataset, load_hexes  # noqa: E402
from app.ingestion.recommendation_importer import (  # noqa: E402
    import_recommendations,
    register_policy,
    register_provider,
)
from app.ingestion.snapshot_builder import ensure_release_and_hexes, import_snapshots  # noqa: E402
from app.providers.precomputed_provider import PrecomputedProvider, PrecomputedProviderError  # noqa: E402
from app.providers.registry import build_provider  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-date", type=date.fromisoformat)
    parser.add_argument("--to-date", type=date.fromisoformat)
    parser.add_argument("--provider", choices=["mock", "precomputed", "none"], default="mock")
    parser.add_argument("--source", type=Path, help="directory with proposals_k*.json (precomputed provider)")
    parser.add_argument("--database-url", help="override DATABASE_URL")
    args = parser.parse_args(argv)

    settings = get_settings()
    policy = get_policy()
    ds = load_active_dataset(settings.repo_path)
    start = args.from_date or ds.start_date
    end = args.to_date or start
    if start < ds.start_date or end > last_date(ds) or end < start:
        parser.error(f"date range must be within [{ds.start_date}, {last_date(ds)}] and ordered")

    Session = get_sessionmaker(args.database_url)
    with Session() as session:
        hexes = load_hexes(ds)
        nm = ensure_release_and_hexes(session, ds, hexes, policy.region_id)
        register_policy(session, policy)
        session.commit()
        print(f"dataset {ds.dataset_id} ({ds.fingerprint[:12]}), {len(hexes)} hexes, node mapping {nm}")

        snapshot_ids = import_snapshots(
            session,
            ds,
            region_id=policy.region_id,
            nm_version=nm,
            from_date=start,
            to_date=end,
            precision=policy.limits.precision,
        )
        print(f"snapshots in range: {len(snapshot_ids)} ({start} .. {end})")
        if args.provider == "none":
            return 0

        provider = build_provider(args.provider, policy, args.source)
        register_provider(session, provider)
        session.commit()
        snapshots = session.scalars(
            select(Snapshot).where(Snapshot.snapshot_id.in_(snapshot_ids)).order_by(Snapshot.cutoff_ts)
        ).all()
        created = rejected = skipped = missing = 0
        for snap in snapshots:
            try:
                result = import_recommendations(session, snap, provider, policy)
            except PrecomputedProviderError:
                session.rollback()
                missing += 1
                continue
            if not result.created:
                skipped += 1
            elif result.status == "REJECTED":
                rejected += 1
                print(f"  REJECTED {snap.snapshot_id}: {result.summary['set_errors']}")
            else:
                created += 1
        if isinstance(provider, PrecomputedProvider) and missing:
            print(f"  {missing} snapshots had no precomputed file")
        print(f"recommendation sets: created={created} rejected={rejected} unchanged={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
