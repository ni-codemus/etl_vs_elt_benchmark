CREATE ROLE bench_user WITH LOGIN PASSWORD 'bench_pass';

CREATE SCHEMA IF NOT EXISTS bench_user;
ALTER SCHEMA bench_user OWNER TO bench_user;
ALTER ROLE bench_user SET search_path TO bench_user;
GRANT ALL ON SCHEMA bench_user TO bench_user;
GRANT ALL ON ALL TABLES IN SCHEMA bench_user TO bench_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA bench_user TO bench_user;

CREATE TABLE IF NOT EXISTS bench_user.tmp_seuil(
    seu_cpa NUMERIC(3),
    seu_cti NUMERIC(2),
    seu_mnt NUMERIC(7),
    seu_mdt DATE
    -- PRIMARY KEY(seu_cpa, seu_cti, seu_mnt, seu_mdt)
);
ALTER TABLE bench_user.tmp_seuil OWNER TO bench_user;


CREATE TABLE IF NOT EXISTS bench_user.tmp_des(
    des_id_num NUMERIC(9),
    des_pos_cod NUMERIC(5),
    des_num_id VARCHAR(15) NOT NULL,
    des_npr_usg VARCHAR(40),
    des_dat_tar DATE,
    des_civ_lib VARCHAR(4),
    des_nor_afn VARCHAR(4),
    des_lig_ad2 VARCHAR(38),
    des_lig_ad3 VARCHAR(38),
    des_lig_ad4 VARCHAR(38),
    des_lig_ad5 VARCHAR(38),
    des_lig_ad6 VARCHAR(38),
    des_lig_ad7 VARCHAR(38),
    des_cod_pay VARCHAR(4),
    PRIMARY KEY(des_id_num),
    UNIQUE(des_id_num, des_num_id, des_npr_usg)
) PARTITION BY RANGE(des_id_num);

ALTER TABLE bench_user.tmp_des OWNER TO bench_user;

CREATE TABLE IF NOT EXISTS bench_user.tmp_fix(
    fix_des_id_num NUMERIC(9),
    fix_id_num NUMERIC(9),
    fix_mdt_dtj DATE,
    fix_typ_num NUMERIC(4),
    fix_dat_tot DATE,
    fix_dat_tar DATE,
    fix_typ_rgp CHAR(1),
    fix_cpa_num NUMERIC(6),
    fix_uge_ser NUMERIC(4),
    fix_cpa_ord VARCHAR(2),
    fix_inf_drg VARCHAR(100),
    fix_inf_div VARCHAR(250),
    fix_montant NUMERIC(13),
    fix_dgr_typ CHAR(1),
    fix_nom_ptr VARCHAR(30),
    PRIMARY KEY(fix_des_id_num, fix_id_num),
    FOREIGN KEY(fix_des_id_num) REFERENCES bench_user.tmp_des(des_id_num)
) PARTITION BY RANGE(fix_des_id_num);

ALTER TABLE bench_user.tmp_fix OWNER TO bench_user;

CREATE TABLE IF NOT EXISTS bench_user.tmp_var(
    var_fix_des_id_num NUMERIC(9),
    var_fix_id_num NUMERIC(9),
    var_id_num NUMERIC(9),
    var_inf_det VARCHAR(255),
    PRIMARY KEY(var_fix_des_id_num, var_fix_id_num, var_id_num),
    FOREIGN KEY(var_fix_des_id_num, var_fix_id_num) REFERENCES bench_user.tmp_fix(fix_des_id_num, fix_id_num)
) PARTITION BY RANGE(var_fix_des_id_num);

ALTER TABLE bench_user.tmp_var OWNER TO bench_user;

DO $$
DECLARE
    i int;
    start_id bigint;
    end_id bigint;
    p_name text;
BEGIN
    FOR i IN 0..99 LOOP
        start_id := i * 10000000;
        end_id := (i + 1) * 10000000 - 1;
        p_name := lpad(i::text, 2, '0');
        
        EXECUTE format('CREATE TABLE IF NOT EXISTS bench_user.tmp_des_p%s PARTITION OF bench_user.tmp_des FOR VALUES FROM (%s) TO (%s);', p_name, start_id, end_id);
        EXECUTE format('ALTER TABLE bench_user.tmp_des_p%s OWNER TO bench_user;', p_name);
        
        EXECUTE format('CREATE TABLE IF NOT EXISTS bench_user.tmp_fix_p%s PARTITION OF bench_user.tmp_fix FOR VALUES FROM (%s) TO (%s);', p_name, start_id, end_id);
        EXECUTE format('ALTER TABLE bench_user.tmp_fix_p%s OWNER TO bench_user;', p_name);
        
        EXECUTE format('CREATE TABLE IF NOT EXISTS bench_user.tmp_var_p%s PARTITION OF bench_user.tmp_var FOR VALUES FROM (%s) TO (%s);', p_name, start_id, end_id);
        EXECUTE format('ALTER TABLE bench_user.tmp_var_p%s OWNER TO bench_user;', p_name);
    END LOOP;
END $$;

DO $$
DECLARE
    i int;
    seq_name text;
BEGIN
    FOR i IN 0..99 LOOP
        seq_name := format('des_seq_%s', lpad(i::text, 2, '0'));
        EXECUTE format('CREATE SEQUENCE IF NOT EXISTS bench_user.%I MINVALUE 1 MAXVALUE 999999999 CYCLE CACHE 5000;', seq_name);
        EXECUTE format('ALTER SEQUENCE bench_user.%I OWNER TO bench_user;', seq_name);
    END LOOP;
END $$;

CREATE SEQUENCE IF NOT EXISTS bench_user.fix_seq MINVALUE 1 MAXVALUE 999999999 CYCLE CACHE 5000;
ALTER SEQUENCE bench_user.fix_seq OWNER TO bench_user;