from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from alembic import command
from app.core.config import get_settings
from app.models import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_migrations_match_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "migrate.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file.as_posix()}")
    monkeypatch.chdir(BACKEND_DIR)
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
    finally:
        get_settings.cache_clear()

    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        perm_count = conn.execute(text("SELECT count(*) FROM permissions")).scalar_one()
    engine.dispose()
    assert diff == []
    assert perm_count > 0
