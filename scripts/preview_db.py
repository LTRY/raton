"""Which DB a PR preview runs on, from the PR's Alembic revisions and the real DB's revision.

    python3 scripts/preview_db.py <alembic/versions of the PR> <revision of the real DB>

prints `shared` when the PR's migration head is the revision the real DB is at (no migration
to run: the preview uses the real DB), `copy` when the real DB is at an older revision of the
PR's chain (the preview migrates a copy). Exits 1 with the French reason otherwise: the real
DB is ahead of the PR, which no copy can fix since the PR lacks the migrations to go back.
Standard library only: it runs in the raton-ops container, without the app's virtualenv.
Spec: docs/spec/04-configuration-et-deploiement.md, section "Previews des PR".
"""

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


def choose_db(revisions: dict[str, str | None], db_revision: str) -> str:
    heads = set(revisions) - set(revisions.values())
    if len(heads) != 1:
        raise PreviewDbError(f"la PR a {len(heads)} têtes de migration au lieu d'une")
    (head,) = heads
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
        print("usage: preview_db.py <alembic/versions> <révision de la DB>", file=sys.stderr)
        return 2
    try:
        print(choose_db(read_revisions(Path(argv[0])), argv[1].strip()))
    except PreviewDbError as error:
        print(f"preview_db.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
