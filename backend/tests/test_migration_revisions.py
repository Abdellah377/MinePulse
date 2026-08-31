"""Migration IDs must fit the existing Alembic version table."""

from pathlib import Path

import pytest
from alembic.script import ScriptDirectory


MIGRATIONS = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))


@pytest.mark.parametrize(
    "revision", list(MIGRATIONS.walk_revisions()), ids=lambda item: item.revision,
)
def test_revision_fits_alembic_version_column(revision):
    # The deployed version table uses Alembic's default VARCHAR(32).
    assert len(revision.revision) <= 32, (
        f"Revision {revision.revision!r} has {len(revision.revision)} characters; "
        "alembic_version.version_num allows at most 32."
    )


def test_migrations_have_one_resolvable_head():
    assert MIGRATIONS.get_current_head() is not None
