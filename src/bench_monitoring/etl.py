from __future__ import annotations

import argparse
import csv
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import PROJECT_ROOT
from .database import DatabaseConnexion
from .logging_setup import setup_logging


@dataclass
class ETLCounts:
    des: int = 0
    fix: int = 0
    var: int = 0
    seuil: int = 0


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


def parse_source_file(source_file: Path, target_dir: Path) -> tuple[list[str], ETLCounts]:
    target_dir.mkdir(parents=True, exist_ok=True)
    des_path = target_dir / "des_file.csv"
    fix_path = target_dir / "fix_file.csv"
    var_path = target_dir / "var_file.csv"
    seuil_path = target_dir / "seuil_file.csv"

    sequences: dict[str, int] = {}
    current_ids = {"des": 0, "fix": 0}
    counts = ETLCounts()
    rows_des: list[list[str]] = []
    rows_fix: list[list[str]] = []
    rows_var: list[list[str]] = []
    rows_seuil: list[list[str]] = []

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
                        rows_seuil.append([seu_cti, seu_mdt, seu_cpa, seu_mnt])

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
                rows_des.append(
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
                rows_fix.append(
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
                    rows_var.append(
                        [
                            str(current_ids["des"]),
                            str(current_ids["fix"]),
                            elements[3],
                            elements[4],
                        ]
                    )

    for path, rows, header in [
        (des_path, rows_des, [
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
        ]),
        (fix_path, rows_fix, [
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
        ]),
        (var_path, rows_var, ["VAR_FIX_DES_ID_NUM", "VAR_FIX_ID_NUM", "VAR_ID_NUM", "VAR_INF_DET"]),
        (seuil_path, rows_seuil, ["SEU_CTI", "SEU_MDT", "SEU_CPA", "SEU_MNT"]),
    ]:
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, delimiter="|")
            writer.writerow(header)
            writer.writerows(rows)

    counts.des = len(rows_des)
    counts.fix = len(rows_fix)
    counts.var = len(rows_var)
    counts.seuil = len(rows_seuil)
    return [str(des_path), str(fix_path), str(var_path), str(seuil_path)], counts


def copy_csv_to_table(conn, table: str, csv_file: Path) -> int:
    with conn.cursor() as cur:
        with csv_file.open("r", encoding="utf-8") as file:
            columns = next(csv.reader(file, delimiter="|"))
            file.seek(0)
            cur.execute(f"SELECT COUNT(*) AS count FROM {table}")
            before_count = cur.fetchone()["count"]
            copy_sql = f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE, DELIMITER '|')"
            with cur.copy(copy_sql) as copy:
                copy.write(file.read())
            cur.execute(f"SELECT COUNT(*) AS count FROM {table}")
            after_count = cur.fetchone()["count"]
    return after_count - before_count


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    source_file = Path(os.getenv("BENCH_DATA_FILE", PROJECT_ROOT / "data" / "flux_des_fix_var.dat"))
    if not source_file.exists():
        raise FileNotFoundError(f"Fichier introuvable: {source_file}")

    host = os.environ["PG_HOST"]
    port = os.environ["PG_PORT"]
    dbname = os.environ["PG_DBNAME"]
    user = os.environ["PG_USER"]
    password = os.environ["PG_PASSWORD"]
    app_name = os.getenv("PG_APP_ETL", "bench-etl")

    db = DatabaseConnexion(host, port, dbname, user, password, app_name=app_name)

    with tempfile.TemporaryDirectory(prefix="bench_etl_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        csv_paths, counts = parse_source_file(source_file, tmp_path)
        logger.info("ETL preparation finished", extra={"counts": counts.__dict__})

        with db as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE tmp_des, tmp_fix, tmp_var, tmp_seuil")

            inserted_des = copy_csv_to_table(conn, "tmp_des", Path(csv_paths[0]))
            inserted_fix = copy_csv_to_table(conn, "tmp_fix", Path(csv_paths[1]))
            inserted_var = copy_csv_to_table(conn, "tmp_var", Path(csv_paths[2]))
            inserted_seuil = copy_csv_to_table(conn, "tmp_seuil", Path(csv_paths[3]))

        logger.info(
            "ETL insertion finished",
            extra={
                "inserted": {
                    "tmp_des": inserted_des,
                    "tmp_fix": inserted_fix,
                    "tmp_var": inserted_var,
                    "tmp_seuil": inserted_seuil,
                }
            },
        )


if __name__ == "__main__":
    main()