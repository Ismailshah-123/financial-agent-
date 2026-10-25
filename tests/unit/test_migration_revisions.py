"""Static checks on the Alembic revision files.

Defect: revision `0012_audit_and_approval_execution` is 33 characters, but Alembic creates
`alembic_version.version_num` as VARCHAR(32). On PostgreSQL the upgrade failed at that step with
"value too long for type character varying(32)", so a clean database could never reach head. It was
never noticed because no one had run the migrations on a real PostgreSQL before.

These tests read the files as text, so they need neither a database nor Alembic.
"""

from __future__ import annotations

import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
MAX_REVISION_LENGTH = 32  # alembic_version.version_num is VARCHAR(32)


def _revisions() -> dict[str, tuple[str, str | None]]:
    """revision id -> (file name, down_revision)."""
    found: dict[str, tuple[str, str | None]] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        revision = re.search(r'^revision(?:\s*:\s*str)?\s*=\s*"([^"]+)"', text, re.M)
        down = re.search(r'^down_revision[^=]*=\s*(None|"([^"]+)")', text, re.M)
        assert revision and down, f"{path.name} does not declare revision and down_revision"
        found[revision.group(1)] = (path.name, down.group(2))
    return found


def test_every_revision_id_fits_the_alembic_version_column() -> None:
    too_long = {rev: len(rev) for rev in _revisions() if len(rev) > MAX_REVISION_LENGTH}
    assert not too_long, f"revision ids longer than {MAX_REVISION_LENGTH} characters: {too_long}"


def test_file_names_match_revision_ids() -> None:
    for revision, (file_name, _) in _revisions().items():
        assert file_name == f"{revision}.py", (revision, file_name)


def test_history_is_one_linear_chain_with_a_single_head() -> None:
    revisions = _revisions()
    roots = [rev for rev, (_, down) in revisions.items() if down is None]
    assert len(roots) == 1, roots
    children: dict[str | None, list[str]] = {}
    for rev, (_, down) in revisions.items():
        assert down is None or down in revisions, f"{rev} points at missing parent {down}"
        children.setdefault(down, []).append(rev)
    assert all(len(kids) == 1 for kids in children.values()), children
    walked, current = [], roots[0]
    while current:
        walked.append(current)
        current = children.get(current, [None])[0]
    assert len(walked) == len(revisions)
