"""Connection settings that protect query plans (found by the ARC-07 load test)."""
from sqlalchemy import text

from supplylens.db import app_engine


def test_connections_always_plan_for_the_actual_parameter_values():
    """With the default (auto), the 6th use of a prepared statement may switch to a generic plan in which the search text
    and the query vector are re-evaluated per scanned row: 0.75 s became 8 s per retrieval at 100,000 chunks."""
    with app_engine().connect() as c:
        assert c.execute(text("SHOW plan_cache_mode")).scalar() == "force_custom_plan"
        assert c.execute(text("SHOW timezone")).scalar() == "UTC"
