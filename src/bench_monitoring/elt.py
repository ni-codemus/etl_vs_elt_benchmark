from __future__ import annotations

import os
from pathlib import Path

from .config import PROJECT_ROOT
from .database import DatabaseConnexion
from .logging_setup import setup_logging


def main() -> None:
    setup_logging()

    source_file = Path(os.getenv("BENCH_DATA_FILE", PROJECT_ROOT / "data" / "flux_des_fix_var.dat"))
    if not source_file.exists():
        raise FileNotFoundError(f"Fichier introuvable: {source_file}")

    host = os.environ["PG_HOST"]
    port = os.environ["PG_PORT"]
    dbname = os.environ["PG_DBNAME"]
    user = os.environ["PG_USER"]
    password = os.environ["PG_PASSWORD"]
    app_name = os.getenv("PG_APP_ELT", "bench-elt")

    db = DatabaseConnexion(host, port, dbname, user, password, app_name=app_name)

    sql_script = """
    --CREATE TEMP TABLE staging_raw(
    --    line_number BIGINT GENERATED ALWAYS AS IDENTITY,
    --    type TEXT,
    --    col1 TEXT,
    --    col2 TEXT,
    --    col3 TEXT,
    --    col4 TEXT,
    --    col5 TEXT,
    --    col6 TEXT,
    --    col7 TEXT,
    --    col8 TEXT,
    --    col9 TEXT,
    --    col10 TEXT,
    --    col11 TEXT,
    --    col12 TEXT,
    --    col13 TEXT,
    --    col14 TEXT,
    --    col15 TEXT,
    --    colnull TEXT
    --) ON COMMIT DROP;
    
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

    ANALYZE temp_hierarchie_complete;

    CREATE TEMP TABLE mapping_des AS
    SELECT
        des_block,
        (RIGHT(col3, 2)::integer * 10000000::bigint) + nextval('des_seq_' || RIGHT(col3, 2)) AS id_des_final,
        col2, col3, col4, col5, col6, col7, col8, col9, col10, col11, col12, col13, col14
    FROM temp_hierarchie_complete
    WHERE type = 'DES';

    CREATE INDEX idx_map_des_block ON mapping_des(des_block);
    ANALYZE mapping_des;

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
    ANALYZE mapping_fix;

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
    WHERE ed.cpa ~ '^[0-9]{3}$'
      AND ed.montant ~ '^[0-9]{7}$'
      AND ed.bloc10 <> '0000000000'
      AND ed.montant <> '0000000';
    """

    with db as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE tmp_des, tmp_fix, tmp_var, tmp_seuil")
            cur.execute(
                "CREATE TEMP TABLE staging_raw("
                "line_number BIGINT GENERATED ALWAYS AS IDENTITY,"
                "type TEXT, col1 TEXT, col2 TEXT, col3 TEXT, col4 TEXT, col5 TEXT, col6 TEXT, col7 TEXT, col8 TEXT, col9 TEXT, col10 TEXT, col11 TEXT, col12 TEXT, col13 TEXT, col14 TEXT, col15 TEXT, colnull TEXT"
                ") ON COMMIT DROP;"
            )

            expected_pipes = 16
            with source_file.open("r", encoding="utf-8") as file:
                copy_query = (
                    "COPY staging_raw (type, col1, col2, col3, col4, col5, col6, col7, col8, col9, col10, col11, col12, col13, col14, col15, colnull) "
                    "FROM STDIN WITH (FORMAT CSV, DELIMITER '|', NULL '')"
                )
                with cur.copy(copy_query) as copy:
                    for line in file:
                        clean_line = line.rstrip("\n")
                        current_pipes = clean_line.count("|")
                        if current_pipes < expected_pipes:
                            clean_line += "|" * (expected_pipes - current_pipes)
                        copy.write(clean_line + "\n")

            cur.execute(sql_script)


if __name__ == "__main__":
    main()