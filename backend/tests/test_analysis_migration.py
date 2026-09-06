import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_budget_migration_upgrade_and_downgrade():
    path = Path(__file__).parents[1] / "alembic/versions/20260906_0012_ai_analysis_budget.py"
    spec = importlib.util.spec_from_file_location("analysis_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert set(inspect(connection).get_table_names()) == {
                "ai_analysis_days",
                "ai_analysis_usage",
            }
            module.downgrade()
            assert inspect(connection).get_table_names() == []
    engine.dispose()
