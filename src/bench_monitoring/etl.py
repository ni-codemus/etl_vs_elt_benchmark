from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from .config import PROJECT_ROOT
from .database import DatabaseConnexion
from .logging_setup import setup_logging


@dataclass
class ETLCounts:
    des: int = 0
    fix: int = 0
    var: int = 0
    seuil: int = 0


@dataclass(frozen=True)
class ETLProfile:
    name: str
    mode: str
    batch_size: int = 1000


ETL_PROFILES: dict[str, ETLProfile] = {
    "copy": ETLProfile(name="copy", mode="copy"),
    "batch": ETLProfile(name="batch", mode="batch", batch_size=2000),
}

TABLE_SPECS: list[tuple[str, str, list[str]]] = [
    (
        "tmp_des",
        "des_file.csv",
        [
            "DES_ID_NUM",
            "DES_POS_COD",
            "DES_NUM_ID",
            "DES_NPR_USG",
            "DES_DAT_TAR",
            "DES_CIV_LIB",
            "DES_NOR_AFN",
            "DES_LIG_AD2",
            "DES_LIG_AD3",
            "DES_LIG_AD4",
            "DES_LIG_AD5",
            "DES_LIG_AD6",
            "DES_LIG_AD7",
            "DES_COD_PAY",
        ],
    ),
    (
        "tmp_fix",
        "fix_file.csv",
        [
            "FIX_DES_ID_NUM",
            "FIX_ID_NUM",
            "FIX_MDT_DTJ",
            "FIX_TYP_NUM",
            "FIX_DAT_TOT",
            "FIX_DAT_TAR",
            "FIX_TYP_RGP",
            "FIX_CPA_NUM",
            "FIX_UGE_SER",
            "FIX_CPA_ORD",
            "FIX_INF_DRG",
            "FIX_INF_DIV",
            "FIX_MONTANT",
            "FIX_DGR_TYP",
            "FIX_NOM_PTR",
        ],
    ),
    ("tmp_var", "var_file.csv", ["VAR_FIX_DES_ID_NUM", "VAR_FIX_ID_NUM", "VAR_ID_NUM", "VAR_INF_DET"]),
    ("tmp_seuil", "seuil_file.csv", ["SEU_CTI", "SEU_MDT", "SEU_CPA", "SEU_MNT"]),
]

TABLE_COLUMNS = {table: columns for table, _, columns in TABLE_SPECS}


def log_phase_start(logger: logging.Logger, profile: ETLProfile, phase_name: str) -> None:
    logger.info("ETL phase start", extra={"profile": profile.name, "phase": phase_name})


def log_phase_end(logger: logging.Logger, profile: ETLProfile, phase_name: str, elapsed_sec: float) -> None:
    logger.info(
        "ETL phase end",
        extra={"profile": profile.name, "phase": phase_name, "elapsed_sec": round(elapsed_sec, 6)},
    )


def record_phase(phase_times: dict[str, float], logger: logging.Logger, profile: ETLProfile, phase_name: str, action):
    log_phase_start(logger, profile, phase_name)
    phase_start = time.perf_counter()
    result = action()
    elapsed_sec = time.perf_counter() - phase_start
    phase_times[phase_name] = round(elapsed_sec, 6)
    log_phase_end(logger, profile, phase_name, elapsed_sec)
    return result


def write_phase_summary(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def dmy_to_iso(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%d%m%Y").strftime("%Y-%m-%d")
    except ValueError:
        return value
    

def ins_id_from_matricule(champ: str) -> str:
    if not champ or not champ[-1].isdigit():
        return "00"
    if len(champ) > 1 and champ[-2].isdigit():
        return champ[-2:]
    return champ[-1]


def parse_source_file(source_file: Path, tmp_dir: Path) -> tuple[dict[str, Path], ETLCounts]:
    """
    Parse the source dataset and write CSVs directly into tmp_dir to avoid
    keeping all rows in memory. Returns a mapping table->csv_path and counts.
    """
    tmp_dir.mkdir(parents=True, exist_ok=True)

    writers: dict[str, tuple[Path, object]] = {}
    for table, filename, header in TABLE_SPECS:
        path = tmp_dir / filename
        f = path.open("w", newline="", encoding="utf-8")
        writer = csv.writer(f, delimiter="|")
        writer.writerow(header)
        writers[table] = (path, (f, writer))

    sequences: dict[str, int] = {}
    current_ids = {"des": 0, "fix": 0}
    counts = ETLCounts()

    with source_file.open("r", encoding="utf-8") as file:
        already = True
        for line in file:
            elements = line.rstrip("\n").split("|")
            record_type = elements[0]

            if record_type == "000":
                if elements[2] == "0040" and already:
                    already = False
                    for index in range(13):
                        seu_cti = elements[1]
                        seu_mdt = dmy_to_iso(elements[4])
                        seu_cpa = elements[6][index * 10 : index * 10 + 3]
                        seu_mnt = elements[6][index * 10 + 3 : index * 10 + 10]
                        if not int(seu_cpa) and not int(seu_mnt):
                            continue
                        f, writer = writers["tmp_seuil"]
                        writer.writerow([seu_cti, seu_mdt, seu_cpa, seu_mnt])

            elif record_type == "DES":
                matricule = elements[3]
                ins_id = ins_id_from_matricule(matricule)
                if ins_id not in sequences:
                    sequences[ins_id] = 1

                new_id_des = int(ins_id) * 10000000 + sequences[ins_id]
                sequences[ins_id] += 1
                if sequences[ins_id] > 9999999:
                    sequences[ins_id] = 1

                des_num_id = elements[3]
                des_npr_usg = elements[4]
                f, writer = writers["tmp_des"]
                writer.writerow(
                    [
                        str(new_id_des),
                        elements[2],
                        des_num_id,
                        des_npr_usg,
                        dmy_to_iso(elements[5]),
                        elements[6],
                        elements[7],
                        elements[8],
                        elements[9],
                        elements[10],
                        elements[11],
                        elements[12],
                        elements[13],
                        elements[14],
                    ]
                )
                current_ids["des"] = new_id_des

            elif record_type == "FIX":
                if "F" not in sequences:
                    sequences["F"] = 1
                new_id_fix = sequences["F"]
                sequences["F"] += 1
                if sequences["F"] > 999999999:
                    sequences["F"] = 1

                fix_cpa_num = elements[8]
                f, writer = writers["tmp_fix"]
                writer.writerow(
                    [
                        str(current_ids["des"]),
                        str(new_id_fix),
                        dmy_to_iso(elements[3]),
                        elements[4],
                        dmy_to_iso(elements[5]),
                        dmy_to_iso(elements[6]),
                        elements[7],
                        fix_cpa_num,
                        elements[9],
                        "10",
                        elements[11],
                        elements[12],
                        elements[13],
                        elements[14],
                        elements[15],
                    ]
                )
                current_ids["fix"] = new_id_fix

            elif record_type == "VAR":
                if current_ids["fix"]:
                    f, writer = writers["tmp_var"]
                    writer.writerow(
                        [
                            str(current_ids["des"]),
                            str(current_ids["fix"]),
                            elements[3],
                            elements[4],
                        ]
                    )

    # close writer files
    csv_paths: dict[str, Path] = {}
    for table, (path, (f, writer)) in writers.items():
        f.close()
        csv_paths[table] = path

    counts.des = sum(1 for _ in csv_paths["tmp_des"].open("r", encoding="utf-8") ) - 1
    counts.fix = sum(1 for _ in csv_paths["tmp_fix"].open("r", encoding="utf-8") ) - 1
    counts.var = sum(1 for _ in csv_paths["tmp_var"].open("r", encoding="utf-8") ) - 1
    counts.seuil = sum(1 for _ in csv_paths["tmp_seuil"].open("r", encoding="utf-8") ) - 1
    return csv_paths, counts


def write_csv_bundle(target_dir: Path, rows_by_table: dict[str, list[list[str]]]) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for table, filename, header in TABLE_SPECS:
        path = target_dir / filename
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, delimiter="|")
            writer.writerow(header)
            writer.writerows(rows_by_table[table])
        paths.append(path)
    return paths


def copy_csv_to_table(conn, table: str, csv_file: Path) -> int:
    with conn.cursor() as cur:
        with csv_file.open("r", encoding="utf-8") as file:
            columns = next(csv.reader(file, delimiter="|"))
            file.seek(0)
            cur.execute(f"SELECT COUNT(*) AS count FROM {table}")
            before_count = cur.fetchone()["count"]
            copy_sql = f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE, DELIMITER '|')"
            with cur.copy(copy_sql) as copy:
                # stream file into the COPY in chunks to avoid loading entire file into memory
                file.seek(0)
                while True:
                    chunk = file.read(64 * 1024)
                    if not chunk:
                        break
                    copy.write(chunk)
            cur.execute(f"SELECT COUNT(*) AS count FROM {table}")
            after_count = cur.fetchone()["count"]
    return after_count - before_count


def insert_rows_in_batches(conn, table: str, rows: list[list[str]], columns: list[str], batch_size: int) -> int:
    if not rows:
        return 0

    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    inserted = 0
    with conn.cursor() as cur:
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            cur.executemany(insert_sql, batch)
            inserted += len(batch)
    return inserted


def execute_sql(conn: Any, statement: str) -> None:
    with conn.cursor() as cur:
        cur.execute(statement)


def run_profile(profile: ETLProfile, source_file: Path, db: DatabaseConnexion, tmp_dir: Path, logger: logging.Logger) -> dict[str, Any]:
    phase_times: dict[str, float] = {}

    csv_paths, counts = record_phase(
        phase_times,
        logger,
        profile,
        "parse_source_file",
        lambda: parse_source_file(source_file, tmp_path),
    )
    # If batch profile requested, load CSVs into memory for batched inserts
    rows_by_table: dict[str, list[list[str]]] = {table: [] for table, _, _ in TABLE_SPECS}
    if profile.mode == "batch":
        for table, filename, _ in TABLE_SPECS:
            path = csv_paths[table]
            with path.open("r", encoding="utf-8") as fh:
                reader = csv.reader(fh, delimiter="|")
                header = next(reader, None)
                rows_by_table[table] = [row for row in reader]
    logger.info("ETL preparation finished", extra={"profile": profile.name, "counts": counts.__dict__})

    with db as conn:
        pg_conn = cast(Any, conn)

        record_phase(
            phase_times,
            logger,
            profile,
            "truncate_target_tables",
            lambda: execute_sql(pg_conn, "TRUNCATE TABLE tmp_des, tmp_fix, tmp_var, tmp_seuil"),
        )

        inserted: dict[str, int] = {}
        if profile.mode == "copy":
            # csv_paths is a mapping table->path produced by parse_source_file
            for table, _, _ in TABLE_SPECS:
                csv_path = csv_paths[table]
                inserted[table] = record_phase(
                    phase_times,
                    logger,
                    profile,
                    f"copy_{table}",
                    lambda table=table, csv_path=csv_path: copy_csv_to_table(pg_conn, table, csv_path),
                )
        elif profile.mode == "batch":
            for table, _, _ in TABLE_SPECS:
                inserted[table] = record_phase(
                    phase_times,
                    logger,
                    profile,
                    f"batch_insert_{table}",
                    lambda table=table: insert_rows_in_batches(pg_conn, table, rows_by_table[table], TABLE_COLUMNS[table], profile.batch_size),
                )
        else:
            raise ValueError(f"Unsupported ETL profile: {profile.name}")

    logger.info("ETL insertion finished", extra={"profile": profile.name, "inserted": inserted, "phase_times_sec": phase_times})
    return {"inserted": inserted, "phase_times_sec": phase_times, "counts": counts.__dict__}


def main(argv: list[str] | None = None, *, default_profile: str = "copy") -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Run an ETL benchmark profile")
    parser.add_argument("--profile", choices=sorted(ETL_PROFILES), default=default_profile, help="ETL profile to run")
    args = parser.parse_args(argv)

    profile = ETL_PROFILES[args.profile]

    source_file = Path(os.getenv("BENCH_DATA_FILE", PROJECT_ROOT / "data" / "flux_des_fix_var.dat"))
    if not source_file.exists():
        raise FileNotFoundError(f"Fichier introuvable: {source_file}")

    host = os.environ["PG_HOST"]
    port = os.environ["PG_PORT"]
    dbname = os.environ["PG_DBNAME"]
    user = os.environ["PG_USER"]
    password = os.environ["PG_PASSWORD"]
    app_name = os.getenv("PG_APP_ETL", "bench-etl")
    phase_summary_path = os.getenv("BENCH_PHASE_TIMES_PATH")

    db = DatabaseConnexion(host, port, dbname, user, password, app_name=app_name)

    with tempfile.TemporaryDirectory(prefix="bench_etl_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        run_summary = run_profile(profile, source_file, db, tmp_path, logger)
        write_phase_summary(
            phase_summary_path,
            {
                "kind": "etl",
                "profile": profile.name,
                **run_summary,
            },
        )
        logger.info("ETL profile completed", extra={"profile": profile.name, **run_summary})


def main_copy() -> None:
    main(default_profile="copy")


def main_batch() -> None:
    main(default_profile="batch")


if __name__ == "__main__":
    main()