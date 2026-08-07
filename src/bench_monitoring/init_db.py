import os
from pathlib import Path

import psycopg
from psycopg import sql

import bench_monitoring.config  # noqa: F401 - loads configs/.env as a side effect
from bench_monitoring.database import DatabaseConnexion


db_name = os.environ["PG_DBNAME"]
super_user_name = os.environ["PG_SUPER_USER"]
super_user_pass = os.environ["PG_SUPER_PASS"]
port = os.environ["PG_PORT"]
host = os.environ["PG_HOST"]

db = DatabaseConnexion(
    host=host,
    port=port,
    dbname=db_name,
    user=super_user_name,
    password=super_user_pass,
)

root_conn = psycopg.connect(
    host=host,
    port=port,
    dbname="postgres",
    user=super_user_name,
    password=super_user_pass,
    sslmode="require",
    autocommit=True,
)

try:
    root_conn.execute(sql.SQL("CREATE DATABASE {}" ).format(sql.Identifier(db_name)))
except psycopg.errors.DuplicateDatabase:
    print(f"La base de données {db_name} existe déjà.")
finally:
    root_conn.close()

project_root_path = Path(os.environ["PROJECT_ROOT"])
sql_file_path = project_root_path / "sql" / "init_db.sql"

with db as conn:
    with conn.cursor() as cur:
        with sql_file_path.open("r", encoding="utf-8") as sql_file:
            sql_text = sql_file.read()

        try:
            cur.execute(sql_text)
        except psycopg.errors.DuplicateObject as exc:
            print(f"Initialisation déjà appliquée, continuation : {exc}")
        except psycopg.errors.DuplicateDatabase as exc:
            print(f"Base déjà présente, continuation : {exc}")
