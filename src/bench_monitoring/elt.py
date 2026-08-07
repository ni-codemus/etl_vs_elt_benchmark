from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
import time

from .config import PROJECT_ROOT
from .database import DatabaseConnexion
from .logging_setup import setup_logging


TARGET_TABLES = ["bench_user.tmp_des", "bench_user.tmp_fix", "bench_user.tmp_var"]


@dataclass(frozen=True)
class ELTProfile:
    name: str
    work_mem_mb: int | None = None
    temp_buffers_mb: int | None = None
    maintenance_work_mem_mb: int | None = None
    synchronous_commit_off: bool = False
    analyze_after_copy: bool = False
    analyze_temp_tables: bool = False
    disable_constraints: bool = False
    copy_freeze: bool = False
    jit_off: bool = False


ELT_PROFILES: dict[str, ELTProfile] = {
    "baseline": ELTProfile(name="baseline"),
    "memory": ELTProfile(name="memory", work_mem_mb=64, temp_buffers_mb=64, maintenance_work_mem_mb=256),
    "analyze": ELTProfile(name="analyze", analyze_after_copy=True, analyze_temp_tables=True),
    "constraints": ELTProfile(name="constraints", disable_constraints=True),
    "max": ELTProfile(
        name="max",
        work_mem_mb=128,
        temp_buffers_mb=64,
        maintenance_work_mem_mb=512,
        synchronous_commit_off=True,
        analyze_after_copy=True,
        analyze_temp_tables=True,
        disable_constraints=True,
        copy_freeze=True,
        jit_off=True,
    ),
}


def log_phase_start(logger: logging.Logger, profile: ELTProfile, phase_name: str) -> None:
    logger.info("ELT phase start", extra={"profile": profile.name, "phase": phase_name})


def log_phase_end(logger: logging.Logger, profile: ELTProfile, phase_name: str, elapsed_sec: float) -> None:
    logger.info(
        "ELT phase end",
        extra={"profile": profile.name, "phase": phase_name, "elapsed_sec": round(elapsed_sec, 6)},
    )


def record_phase(phase_times: dict[str, float], logger: logging.Logger, profile: ELTProfile, phase_name: str, action):
    log_phase_start(logger, profile, phase_name)
    phase_start = time.perf_counter()
    result = action()
    elapsed_sec = time.perf_counter() - phase_start
    phase_times[phase_name] = round(elapsed_sec, 6)
    log_phase_end(logger, profile, phase_name, elapsed_sec)
    return result


def write_phase_summary(path: str | None, payload: dict[str, object]) -> None:
    if not path:
        return
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def session_prelude(profile: ELTProfile) -> list[str]:
    statements: list[str] = []
    if profile.work_mem_mb is not None:
        statements.append(f"SET LOCAL work_mem = '{profile.work_mem_mb}MB';")
    if profile.temp_buffers_mb is not None:
        statements.append(f"SET LOCAL temp_buffers = '{profile.temp_buffers_mb}MB';")
    if profile.maintenance_work_mem_mb is not None:
        statements.append(f"SET LOCAL maintenance_work_mem = '{profile.maintenance_work_mem_mb}MB';")
    if profile.synchronous_commit_off:
        statements.append("SET LOCAL synchronous_commit = off;")
    if profile.jit_off:
        statements.append("SET LOCAL jit = off;")
    return statements


def disable_target_constraints(cur) -> None:
    for table in TARGET_TABLES:
        cur.execute(f"ALTER TABLE {table} DISABLE TRIGGER ALL;")


def enable_target_constraints(cur) -> None:
    for table in TARGET_TABLES:
        cur.execute(f"ALTER TABLE {table} ENABLE TRIGGER ALL;")


def apply_session_prelude(cur, profile: ELTProfile) -> None:
    for statement in session_prelude(profile):
        cur.execute(statement)


def build_admin_db(host: str, port: str, dbname: str, app_name: str) -> DatabaseConnexion:
    super_user = os.getenv("PG_SUPER_USER")
    super_pass = os.getenv("PG_SUPER_PASS")
    if not super_user or not super_pass:
        raise RuntimeError("PG_SUPER_USER et PG_SUPER_PASS sont requis pour le profil ELT 'constraints' ou 'max'.")
    return DatabaseConnexion(host, port, dbname, super_user, super_pass, app_name=f"{app_name}-admin")


def _copy_into_staging(cur, source_file: Path, expected_pipes: int, copy_freeze_clause: str) -> None:
    with source_file.open("r", encoding="utf-8") as file:
        copy_query = (
            "COPY staging_raw (type, col1, col2, col3, col4, col5, col6, col7, col8, col9, col10, col11, col12, col13, col14, col15, colnull) "
            f"FROM STDIN WITH (FORMAT CSV, DELIMITER '|', NULL ''{copy_freeze_clause})"
        )
        with cur.copy(copy_query) as copy:
            for line in file:
                clean_line = line.rstrip("\n")
                current_pipes = clean_line.count("|")
                if current_pipes < expected_pipes:
                    clean_line += "|" * (expected_pipes - current_pipes)
                copy.write(clean_line + "\n")


def build_elti_sql(profile: ELTProfile) -> str:
    analyze_temp = "ANALYZE temp_hierarchie_complete;" if profile.analyze_temp_tables else ""
    analyze_des = "ANALYZE mapping_des;" if profile.analyze_temp_tables else ""
    analyze_fix = "ANALYZE mapping_fix;" if profile.analyze_temp_tables else ""

    return f"""
    CREATE TEMP TABLE temp_hierarchie_complete AS
    WITH donnees_utiles AS (
        SELECT * FROM staging_raw WHERE type IN ('DES', 'FIX', 'VAR')
    ),
    blocs_des AS (
        SELECT
            line_number, type, col1, col2, col3, col4, col5, col6, col7, col8, col9, col10, col11, col12, col13, col14, col15,
            SUM(CASE WHEN type = 'DES' THEN 1 ELSE 0 END) OVER (ORDER BY line_number) AS des_block
        FROM donnees_utiles
    )
    SELECT
        *,
        SUM(CASE WHEN type = 'FIX' THEN 1 ELSE 0 END) OVER (PARTITION BY des_block ORDER BY line_number) AS fix_block
    FROM blocs_des;

    CREATE INDEX idx_temp_type ON temp_hierarchie_complete(type);
    CREATE INDEX idx_temp_hier_des ON temp_hierarchie_complete(des_block);
    CREATE INDEX idx_temp_hier_fix ON temp_hierarchie_complete(des_block, fix_block);
    {analyze_temp}

    CREATE TEMP TABLE mapping_des AS
    SELECT
        des_block,
        (RIGHT(col3, 2)::integer * 10000000::bigint) + nextval('des_seq_' || RIGHT(col3, 2)) AS id_des_final,
        col2, col3, col4, col5, col6, col7, col8, col9, col10, col11, col12, col13, col14
    FROM temp_hierarchie_complete
    WHERE type = 'DES';

    CREATE INDEX idx_map_des_block ON mapping_des(des_block);
    {analyze_des}

    INSERT INTO tmp_des
    (
        des_id_num,
        des_pos_cod,
        des_num_id,
        des_npr_usg,
        des_dat_tar,
        des_civ_lib,
        des_nor_afn,
        des_lig_ad2,
        des_lig_ad3,
        des_lig_ad4,
        des_lig_ad5,
        des_lig_ad6,
        des_lig_ad7,
        des_cod_pay
    )
    SELECT
        id_des_final,
        col2:: NUMERIC(5),
        col3:: VARCHAR(15),
        col4:: VARCHAR(40),
        TO_DATE(col5, 'DDMMYYYY'),
        col6:: VARCHAR(4),
        col7:: VARCHAR(4),
        col8:: VARCHAR(38),
        col9:: VARCHAR(38),
        col10:: VARCHAR(38),
        col11:: VARCHAR(38),
        col12:: VARCHAR(38),
        col13:: VARCHAR(38),
        col14:: VARCHAR(4)
    FROM mapping_des;

    CREATE TEMP TABLE mapping_fix AS
    SELECT
        h.des_block, h.fix_block,
        d.id_des_final,
        nextval('fix_seq') AS id_fix_final,
        h.col2, h.col3, h.col4, h.col5,
        h.col6, h.col7, h.col8, h.col9,
        h.col10, h.col11, h.col12, h.col13,
        h.col14, h.col15
    FROM temp_hierarchie_complete h
    JOIN mapping_des d ON h.des_block = d.des_block
    WHERE h.type = 'FIX'
    ORDER BY h.line_number;

    CREATE INDEX idx_map_fix_blocks ON mapping_fix(des_block, fix_block);
    {analyze_fix}

    INSERT INTO tmp_fix
    (
        fix_des_id_num,
        fix_id_num,
        fix_mdt_dtj,
        fix_typ_num,
        fix_dat_tot,
        fix_dat_tar,
        fix_typ_rgp,
        fix_cpa_num,
        fix_uge_ser,
        fix_cpa_ord,
        fix_inf_drg,
        fix_inf_div,
        fix_montant,
        fix_dgr_typ,
        fix_nom_ptr
    )
    SELECT
        id_des_final,
        id_fix_final,
        TO_DATE(col3, 'DDMMYYYY'),
        col4:: NUMERIC(4),
        TO_DATE(col5, 'DDMMYYYY'),
        TO_DATE(col6, 'DDMMYYYY'),
        col7:: CHAR(1),
        col8:: NUMERIC(6),
        col9:: NUMERIC(4),
        col10::VARCHAR(2),
        col11::VARCHAR(100),
        col12::VARCHAR(250),
        col13::NUMERIC(13),
        col14::CHAR(1),
        col15::VARCHAR(30)
    FROM mapping_fix;

    INSERT INTO tmp_var
    (
        var_fix_des_id_num,
        var_fix_id_num,
        var_id_num,
        var_inf_det
    )
    SELECT
        f.id_des_final,
        f.id_fix_final,
        ROW_NUMBER() OVER (
            PARTITION BY h.des_block, h.fix_block
            ORDER BY h.line_number
        ) AS var_id_num,
        h.col4::VARCHAR(255)
    FROM temp_hierarchie_complete h
    JOIN mapping_fix f
      ON h.des_block = f.des_block AND h.fix_block = f.fix_block
    WHERE h.type = 'VAR';

    WITH source_data AS (
        SELECT DISTINCT
            col1 AS couloir,
            col4 AS date_mdt,
            col6 AS seuils
        FROM staging_raw
        WHERE type = '000'
        AND col2 = '0040'
        LIMIT 1
    ),
    split_data AS (
        SELECT
            gs AS pos,
            substr(sd.seuils, ((gs - 1) * 10) + 1, 10) AS bloc10
        FROM source_data sd
        CROSS JOIN generate_series(1, 13) AS gs
    ),
    extracted_data AS (
        SELECT
            pos,
            bloc10,
            substr(bloc10, 1, 3) AS cpa,
            substr(bloc10, 4, 7) AS montant
        FROM split_data
        WHERE length(bloc10) = 10
    )
    INSERT INTO tmp_seuil (seu_cti, seu_mdt, seu_cpa, seu_mnt)
    SELECT
        sd.couloir::NUMERIC(2) AS seu_cti,
        TO_DATE(sd.date_mdt, 'DDMMYYYY') AS seu_mdt,
        ed.cpa::NUMERIC(3) AS seu_cpa,
        ed.montant::NUMERIC(7) AS seu_mnt
    FROM extracted_data ed
    CROSS JOIN source_data sd
    WHERE ed.cpa ~ '^[0-9]{{3}}$'
      AND ed.montant ~ '^[0-9]{{7}}$'
      AND ed.bloc10 <> '0000000000'
      AND ed.montant <> '0000000';
    """


def main(argv: list[str] | None = None, *, default_profile: str = "baseline") -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Run an ELT benchmark profile")
    parser.add_argument("--profile", choices=sorted(ELT_PROFILES), default=default_profile, help="ELT profile to run")
    args = parser.parse_args(argv)

    profile = ELT_PROFILES[args.profile]
    source_file = Path(os.getenv("BENCH_DATA_FILE", PROJECT_ROOT / "data" / "flux_des_fix_var.dat"))
    if not source_file.exists():
        raise FileNotFoundError(f"Fichier introuvable: {source_file}")

    host = os.environ["PG_HOST"]
    port = os.environ["PG_PORT"]
    dbname = os.environ["PG_DBNAME"]
    user = os.environ["PG_USER"]
    password = os.environ["PG_PASSWORD"]
    app_name = os.getenv("PG_APP_ELT", "bench-elt")
    phase_summary_path = os.getenv("BENCH_PHASE_TIMES_PATH")

    db = DatabaseConnexion(host, port, dbname, user, password, app_name=app_name)
    admin_db = build_admin_db(host, port, dbname, app_name) if profile.disable_constraints else None
    sql_script = build_elti_sql(profile)
    phase_times: dict[str, float] = {}

    if admin_db is not None:
        with db as conn, admin_db as admin_conn:
            with conn.cursor() as cur, admin_conn.cursor() as admin_cur:
                record_phase(phase_times, logger, profile, "disable_constraints", lambda: disable_target_constraints(admin_cur))
                record_phase(phase_times, logger, profile, "truncate_target_tables", lambda: cur.execute("TRUNCATE TABLE tmp_des, tmp_fix, tmp_var, tmp_seuil"))  # type: ignore[arg-type]
                if profile.work_mem_mb is not None or profile.temp_buffers_mb is not None or profile.maintenance_work_mem_mb is not None or profile.synchronous_commit_off or profile.jit_off:
                    record_phase(phase_times, logger, profile, "session_prelude", lambda: apply_session_prelude(cur, profile))
                record_phase(
                    phase_times,
                    logger,
                    profile,
                    "create_staging_raw",
                    lambda: cur.execute(
                        "CREATE TEMP TABLE staging_raw("
                        "line_number BIGINT GENERATED ALWAYS AS IDENTITY,"
                        "type TEXT, col1 TEXT, col2 TEXT, col3 TEXT, col4 TEXT, col5 TEXT, col6 TEXT, col7 TEXT, col8 TEXT, col9 TEXT, col10 TEXT, col11 TEXT, col12 TEXT, col13 TEXT, col14 TEXT, col15 TEXT, colnull TEXT"
                        ") ON COMMIT DROP;"
                    ),
                )  # type: ignore[arg-type]

                expected_pipes = 16
                copy_freeze_clause = ", FREEZE" if profile.copy_freeze else ""
                record_phase(
                    phase_times,
                    logger,
                    profile,
                    "copy_into_staging_raw",
                    lambda: _copy_into_staging(cur, source_file, expected_pipes, copy_freeze_clause),
                )  # type: ignore[arg-type]

                if profile.analyze_after_copy:
                    record_phase(phase_times, logger, profile, "analyze_staging_raw", lambda: cur.execute("ANALYZE staging_raw"))  # type: ignore[arg-type]

                record_phase(phase_times, logger, profile, "transform_and_load", lambda: cur.execute(sql_script))  # type: ignore[arg-type]

                record_phase(phase_times, logger, profile, "enable_constraints", lambda: enable_target_constraints(admin_cur))
    else:
        with db as conn:
            with conn.cursor() as cur:
                record_phase(phase_times, logger, profile, "truncate_target_tables", lambda: cur.execute("TRUNCATE TABLE tmp_des, tmp_fix, tmp_var, tmp_seuil"))  # type: ignore[arg-type]
                if profile.work_mem_mb is not None or profile.temp_buffers_mb is not None or profile.maintenance_work_mem_mb is not None or profile.synchronous_commit_off or profile.jit_off:
                    record_phase(phase_times, logger, profile, "session_prelude", lambda: apply_session_prelude(cur, profile))
                record_phase(
                    phase_times,
                    logger,
                    profile,
                    "create_staging_raw",
                    lambda: cur.execute(
                        "CREATE TEMP TABLE staging_raw("
                        "line_number BIGINT GENERATED ALWAYS AS IDENTITY,"
                        "type TEXT, col1 TEXT, col2 TEXT, col3 TEXT, col4 TEXT, col5 TEXT, col6 TEXT, col7 TEXT, col8 TEXT, col9 TEXT, col10 TEXT, col11 TEXT, col12 TEXT, col13 TEXT, col14 TEXT, col15 TEXT, colnull TEXT"
                        ") ON COMMIT DROP;"
                    ),
                )  # type: ignore[arg-type]

                expected_pipes = 16
                copy_freeze_clause = ", FREEZE" if profile.copy_freeze else ""
                record_phase(
                    phase_times,
                    logger,
                    profile,
                    "copy_into_staging_raw",
                    lambda: _copy_into_staging(cur, source_file, expected_pipes, copy_freeze_clause),
                )  # type: ignore[arg-type]

                if profile.analyze_after_copy:
                    record_phase(phase_times, logger, profile, "analyze_staging_raw", lambda: cur.execute("ANALYZE staging_raw"))  # type: ignore[arg-type]

                record_phase(phase_times, logger, profile, "transform_and_load", lambda: cur.execute(sql_script))  # type: ignore[arg-type]

    write_phase_summary(
        phase_summary_path,
        {
            "kind": "elt",
            "profile": profile.name,
            "phase_times_sec": phase_times,
        },
    )
    logger.info("ELT profile completed", extra={"profile": profile.name, "phase_times_sec": phase_times})


def main_baseline() -> None:
    main(default_profile="baseline")


def main_memory() -> None:
    main(default_profile="memory")


def main_analyze() -> None:
    main(default_profile="analyze")


def main_constraints() -> None:
    main(default_profile="constraints")


def main_max() -> None:
    main(default_profile="max")


if __name__ == "__main__":
    main()
