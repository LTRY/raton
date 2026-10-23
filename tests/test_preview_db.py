from pathlib import Path

import pytest

from scripts.preview_db import COPY, SHARED, PreviewDbError, choose_db, read_revisions

CHAIN = {
    "0001_initial": None,
    "0002_drop_ai_analysis": "0001_initial",
    "0003_new": "0002_drop_ai_analysis",
}


def test_a_pr_without_migration_to_run_shares_the_real_db():
    assert choose_db(CHAIN, "0003_new") == SHARED


def test_a_pr_with_a_migration_to_run_gets_a_copy():
    assert choose_db(CHAIN, "0002_drop_ai_analysis") == COPY


def test_a_real_db_ahead_of_the_pr_is_refused():
    with pytest.raises(PreviewDbError, match="mettez la PR à jour avec main"):
        choose_db(CHAIN, "0004_from_main")


def test_two_migration_heads_are_refused():
    with pytest.raises(PreviewDbError, match="2 têtes"):
        choose_db({**CHAIN, "0003_other": "0002_drop_ai_analysis"}, "0003_new")


def test_read_revisions_reads_the_repo_migrations():
    revisions = read_revisions(Path(__file__).resolve().parents[1] / "alembic" / "versions")

    assert revisions["0001_initial"] is None
    assert revisions["0002_drop_ai_analysis"] == "0001_initial"
