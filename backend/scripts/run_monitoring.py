"""Run or inspect one deterministic monitoring cycle without starting FastAPI."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.config import get_settings
from app.db.database import SessionLocal
from app.db.models import Site
from app.monitoring.detectors import DEFAULT_DETECTORS
from app.monitoring.predictive import attach_failure_risk_predictions
from app.monitoring.service import MonitoringService, build_monitoring_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--detect-only", action="store_true",
        help="Print candidates from operational services without creating alerts or calling an LLM.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    with SessionLocal() as session:
        if args.detect_only:
            findings = []
            sites = session.scalars(select(Site).where(Site.active.is_(True)).order_by(Site.site_id)).all()
            for site in sites:
                snapshot = attach_failure_risk_predictions(
                    session, build_monitoring_snapshot(session, site)
                )
                for detector in DEFAULT_DETECTORS:
                    findings.extend(detector(snapshot, settings))
            print(json.dumps([item.model_dump(mode="json") for item in findings], indent=2, ensure_ascii=False))
            return 0
        if not settings.monitoring_enabled:
            parser.error("MONITORING_ENABLED must be true to create alerts/investigations")
        print(json.dumps(MonitoringService(settings=settings).run_cycle(session), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
