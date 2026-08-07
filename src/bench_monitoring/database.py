from __future__ import annotations

import psycopg
from psycopg.rows import dict_row


class DatabaseConnexion:
    def __init__(
        self,
        host: str,
        port: str | int,
        dbname: str,
        user: str,
        password: str,
        app_name: str | None = None,
    ) -> None:
        self.params: dict[str, object] = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password,
        }
        if app_name:
            self.params["application_name"] = app_name
        self.conn: psycopg.Connection | None = None

    def __enter__(self) -> psycopg.Connection:
        self.conn = psycopg.connect(**self.params, row_factory=dict_row)
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn is None:
            return
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()


DatabaseConnection = DatabaseConnexion