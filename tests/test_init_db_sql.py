from pathlib import Path


def test_init_db_sql_avoids_role_owner_switching_for_rds():
    sql = Path("sql/init_db.sql").read_text(encoding="utf-8")

    assert "AUTHORIZATION bench_user" not in sql
    assert "GRANT ALL ON SCHEMA bench_user TO bench_user" in sql
    assert "GRANT ALL ON ALL TABLES IN SCHEMA bench_user TO bench_user" in sql
    assert "GRANT ALL ON ALL SEQUENCES IN SCHEMA bench_user TO bench_user" in sql
