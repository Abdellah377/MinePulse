"""Resolve the single site used by prototype ML loaders and training.

ML snapshots must not mix simulation-site rows with any other site that happens
to exist in the same PostgreSQL database. This helper does not import the
simulator package.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Site

SIMULATION_SITE_CODE = "MP-SIM-01"


def resolve_ml_site_id(session: Session, site_id: int | None = None) -> int:
    """Return an explicit site id, or the canonical simulation-site id."""
    if site_id is not None:
        return int(site_id)
    site = session.scalar(select(Site).where(Site.code == SIMULATION_SITE_CODE))
    if site is None:
        raise ValueError(f"No site-scoped ML snapshot: site {SIMULATION_SITE_CODE} was not found.")
    return int(site.site_id)
