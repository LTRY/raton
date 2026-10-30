"""Which DB a PR preview runs on, from the PR's Alembic revisions and the real DB's revision.

    python3 scripts/preview_db.py <alembic/versions of the PR> <revision of the real DB>
    python3 scripts/preview_db.py head <alembic/versions>

The first form prints `shared` when the PR's migration head is the revision the real DB is at (no migration
to run: the preview uses the real DB), `copy` when the real DB is at an older revision of the
PR's chain (the preview migrates a copy). Exits 1 with the French reason otherwise: the real
DB is ahead of the PR, which no copy can fix since the PR lacks the migrations to go back.
`head` prints the migration head: `preview.sh retire-stale` compares a preview's to main's.
Standard library only: it runs in the raton-ops container, without the app's virtualenv.
Spec: docs/spec/04-configuration-et-deploiement.md, section "Previews des PR".
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SHARED = "shared"
COPY = "copy"


class PreviewDbError(ValueError):
    pass


def read_revisions(versions_dir: Path) -> dict[str, str | None]:
    """revision -> down_revision of every migration file, read without importing it."""
    revisions: dict[str, str | None] = {}
    for path in sorted(versions_dir.glob("*.py")):
        values = {}
        for node in ast.parse(path.read_text()).body:
            target = node.target if isinstance(node, ast.AnnAssign) else None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in ("revision", "down_revision"):
                values[target.id] = ast.literal_eval(node.value)
        if "revision" in values:
            revisions[values["revision"]] = values.get("down_revision")
    return revisions


def migration_head(revisions: dict[str, str | None]) -> str:
    heads = set(revisions) - set(revisions.values())
    if len(heads) != 1:
        raise PreviewDbError(f"la PR a {len(heads)} têtes de migration au lieu d'une")
    (head,) = heads
    return head


def choose_db(revisions: dict[str, str | None], db_revision: str) -> str:
    head = migration_head(revisions)
    if db_revision == head:
        return SHARED
    revision: str | None = head
    while revision is not None:
        if revision == db_revision:
            return COPY
        revision = revisions.get(revision)
    raise PreviewDbError(
        f"la DB réelle est en {db_revision!r}, absente des migrations de la PR : "
        "mettez la PR à jour avec main"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: preview_db.py <alembic/versions> <révision de la DB> | head <alembic/versions>",
            file=sys.stderr,
        )
        return 2
    try:
        if argv[0] == "head":
            print(migration_head(read_revisions(Path(argv[1]))))
        else:
            print(choose_db(read_revisions(Path(argv[0])), argv[1].strip()))
    except PreviewDbError as error:
        print(f"preview_db.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
