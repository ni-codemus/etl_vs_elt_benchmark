from __future__ import annotations

import argparse
import time
import random
import os
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import List, Tuple

DEFAULT_SEED = 123

ALLOWED_TYP_NUM = [40]
ALLOWED_CPA_NUM = [751]


def dmy(dt: date) -> str:
    return dt.strftime("%d%m%Y")


def random_date(start: date, end: date) -> date:
    days = (end - start).days
    return start + timedelta(days=random.randint(0, max(days, 0)))


def only_digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def zfill_num(n: int, width: int) -> str:
    return str(n).zfill(width)


def trunc(s: str, max_len: int) -> str:
    s = "" if s is None else str(s)
    return s[:max_len]


def fmt_amount_13(n: Decimal) -> str:
    i = int(n.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return str(i)[:13]


def ts_prefix() -> str:
    return time.strftime("%H:%M:%S")


def log_line(message: str) -> None:
    print(f"[{ts_prefix()}] {message}")


@dataclass
class DES:
    des_id_num: int
    des_pos_cod: int
    des_num_id: str
    des_npr_usg: str
    des_dat_tar: date
    des_civ_lib: str
    des_nor_afn: str
    des_lig_ad2: str
    des_lig_ad3: str
    des_lig_ad4: str
    des_lig_ad5: str
    des_lig_ad6: str
    des_lig_ad7: str
    des_cod_pay: str


@dataclass
class FIX:
    fix_des_id_num: int
    fix_id_num: int
    fix_mdt_dtj: date
    fix_typ_num: int
    fix_dat_tot: date
    fix_dat_tar: date
    fix_typ_rgp: str
    fix_cpa_num: int
    fix_uge_ser: int
    fix_cpa_ord: str
    fix_inf_drg: str
    fix_inf_div: str
    fix_montant: Decimal
    fix_dgr_typ: str
    fix_nom_ptr: str


@dataclass
class VAR:
    var_fix_des_id_num: int
    var_fix_id_num: int
    var_id_num: int
    var_inf_det: str


def line_000(batch_date: date, seq: int, payload: str) -> str:
    return f"000|36|0040|P|{dmy(batch_date)}|{zfill_num(seq,3)}|{payload}"


def line_des(d: DES) -> str:
    fields = [
        zfill_num(d.des_id_num, 9),
        zfill_num(d.des_pos_cod, 5),
        trunc(only_digits(d.des_num_id), 15).ljust(15),
        trunc(d.des_npr_usg, 40).ljust(40),
        dmy(d.des_dat_tar),
        trunc(d.des_civ_lib, 4).ljust(4),
        trunc(d.des_nor_afn, 4).ljust(4),
        trunc(d.des_lig_ad2, 38).ljust(38),
        trunc(d.des_lig_ad3, 38).ljust(38),
        trunc(d.des_lig_ad4, 38).ljust(38),
        trunc(d.des_lig_ad5, 38).ljust(38),
        trunc(d.des_lig_ad6, 38).ljust(38),
        trunc(d.des_lig_ad7, 38).ljust(38),
        trunc(d.des_cod_pay, 4).ljust(4),
    ]
    return "DES|" + "|".join(fields) + "|"


def line_fix(f: FIX) -> str:
    fields = [
        zfill_num(f.fix_des_id_num, 9),
        zfill_num(f.fix_id_num, 9),
        dmy(f.fix_mdt_dtj),
        zfill_num(f.fix_typ_num, 4),
        dmy(f.fix_dat_tot),
        dmy(f.fix_dat_tar),
        trunc(f.fix_typ_rgp, 1),
        zfill_num(f.fix_cpa_num, 6),
        zfill_num(f.fix_uge_ser, 4),
        trunc(f.fix_cpa_ord, 2).ljust(2),
        trunc(f.fix_inf_drg, 100).ljust(100),
        trunc(f.fix_inf_div, 250).ljust(250),
        fmt_amount_13(f.fix_montant),
        trunc(f.fix_dgr_typ, 1),
        trunc(f.fix_nom_ptr, 30).ljust(30),
    ]
    return "FIX|" + "|".join(fields) + "|"


def line_var(v: VAR) -> str:
    fields = [
        zfill_num(v.var_fix_des_id_num, 9),
        zfill_num(v.var_fix_id_num, 9),
        zfill_num(v.var_id_num, 9),
        trunc(v.var_inf_det, 255).ljust(255),
    ]
    return "VAR|" + "|".join(fields) + "|"


def line_900(nb_fix: int, nb_des: int) -> str:
    return f"900|{str(nb_fix).zfill(10)}|{str(nb_des).zfill(3)}|"


NOMS = ["NOM PRENOM", "MARTIN ALICE", "DUPONT PAUL", "ELIANE LASSURE"]
CIVS = ["MME", "M.", "MLLE"]
VOIES = ["ALL", "RUE", "AV", "BD"]
VILLES = ["BOURG EN BRESSE", "LYON", "PARIS"]
PAYS = ["F", "FR"]


def generate_payload_000(length: int = 255) -> str:
    base = "751000015078100002007890000150921000020095100001500"
    if len(base) >= length:
        return base[:length]
    return base + ("0" * (length - len(base)))


def make_des(des_id: int) -> DES:
    dt_ref = date(2026, 6, 5)
    return DES(
        des_id_num=des_id,
        des_pos_cod=1000,
        des_num_id="".join(str(random.randint(0, 9)) for _ in range(15)),
        des_npr_usg=random.choice(NOMS),
        des_dat_tar=dt_ref,
        des_civ_lib=random.choice(CIVS),
        des_nor_afn=str(random.randint(1, 9999)).zfill(4),
        des_lig_ad2="",
        des_lig_ad3="ETG3",
        des_lig_ad4=random.choice(VOIES),
        des_lig_ad5="DU 1ER MAI",
        des_lig_ad6="",
        des_lig_ad7=random.choice(VILLES),
        des_cod_pay=random.choice(PAYS),
    )


def make_fix(des_id: int, fix_id: int) -> FIX:
    dt1 = date(2026, 3, 6)
    dt2 = date(2026, 6, 5)
    return FIX(
        fix_des_id_num=des_id,
        fix_id_num=fix_id,
        fix_mdt_dtj=dt1,
        fix_typ_num=random.choice(ALLOWED_TYP_NUM),
        fix_dat_tot=dt1,
        fix_dat_tar=dt2,
        fix_typ_rgp=random.choice(["X", "A", "B"]),
        fix_cpa_num=random.choice(ALLOWED_CPA_NUM),
        fix_uge_ser=random.randint(1, 9999),
        fix_cpa_ord=random.choice(["01", "02", "03"]),
        fix_inf_drg="INFO DRG TEST",
        fix_inf_div="INFO DIV DETAILLEE POUR TEST",
        fix_montant=Decimal(random.randint(100, 500000)),
        fix_dgr_typ=random.choice(["1", "2", "3"]),
        fix_nom_ptr="NOM_PRATICIEN_TEST",
    )


def make_var(des_id: int, fix_id: int, var_id: int, des: DES) -> VAR:
    txt = f"{str(des.des_pos_cod).zfill(5)}{des.des_npr_usg[:20]}{dmy(des.des_dat_tar)}{des.des_num_id}ASAVIS 1"
    return VAR(
        var_fix_des_id_num=des_id,
        var_fix_id_num=fix_id,
        var_id_num=var_id,
        var_inf_det=txt,
    )


def generate_dat_file(
    out_path: str,
    nb_des: int = 3,
    min_fix_per_des: int = 1,
    max_fix_per_des: int = 2,
    min_var_per_fix: int = 1,
    max_var_per_fix: int = 3,
    seed: int | None = DEFAULT_SEED,
):
    if not ALLOWED_TYP_NUM or not ALLOWED_CPA_NUM:
        raise ValueError("Remplis ALLOWED_TYP_NUM et ALLOWED_CPA_NUM.")

    if seed is not None:
        random.seed(seed)

    if nb_des < 0:
        raise ValueError("nb_des must be >= 0")
    if min_fix_per_des < 0 or max_fix_per_des < 0:
        raise ValueError("fix bounds must be >= 0")
    if min_var_per_fix < 0 or max_var_per_fix < 0:
        raise ValueError("var bounds must be >= 0")
    if min_fix_per_des > max_fix_per_des:
        raise ValueError("min_fix_per_des must be <= max_fix_per_des")
    if min_var_per_fix > max_var_per_fix:
        raise ValueError("min_var_per_fix must be <= max_var_per_fix")

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # target in-memory batch size before flushing to disk (default ~300 MiB)
    batch_bytes = 300 * 1024 * 1024
    batch_buf = bytearray()

    batch_date = date(2026, 3, 6)
    # write header (overwrite any existing file)
    with path.open("wb") as fh:
        header = (line_000(batch_date, seq=1, payload=generate_payload_000(260)) + "\n").encode("utf-8")
        fh.write(header)
        fh.flush()
        os.fsync(fh.fileno())

    des_id_start = 192984554
    fix_id_counter = 975547212
    total_fix = 0

    def flush_buf():
        nonlocal batch_buf
        if not batch_buf:
            return
        with path.open("ab") as fh:
            fh.write(batch_buf)
            fh.flush()
            os.fsync(fh.fileno())
        batch_buf = bytearray()

    for i in range(nb_des):
        des_id = des_id_start + i
        des = make_des(des_id)
        line = line_des(des) + "\n"
        batch_buf.extend(line.encode("utf-8"))

        nfix = random.randint(min_fix_per_des, max_fix_per_des)
        for _ in range(nfix):
            fix = make_fix(des_id=des_id, fix_id=fix_id_counter)
            batch_buf.extend((line_fix(fix) + "\n").encode("utf-8"))
            total_fix += 1

            nvar = random.randint(min_var_per_fix, max_var_per_fix)
            for j in range(1, nvar + 1):
                var = make_var(des_id=des_id, fix_id=fix_id_counter, var_id=j, des=des)
                batch_buf.extend((line_var(var) + "\n").encode("utf-8"))

            fix_id_counter += 1

        # flush if buffer exceeds threshold
        if len(batch_buf) >= batch_bytes:
            flush_buf()

    # write trailer and flush remaining buffer
    batch_buf.extend((line_900(nb_fix=total_fix, nb_des=nb_des) + "\n").encode("utf-8"))
    flush_buf()
    log_line(f"[OK] Fichier généré: {path}")
    log_line(f"[COUNT] DES={nb_des} FIX={total_fix}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a benchmark dataset file")
    parser.add_argument("--out", default="data/flux_des_fix_var.dat", help="Output dataset path")
    parser.add_argument("--nb-des", type=int, default=30, help="Number of DES records to generate")
    parser.add_argument("--min-fix-per-des", type=int, default=1, help="Minimum FIX records per DES")
    parser.add_argument("--max-fix-per-des", type=int, default=50, help="Maximum FIX records per DES")
    parser.add_argument("--min-var-per-fix", type=int, default=1, help="Minimum VAR records per FIX")
    parser.add_argument("--max-var-per-fix", type=int, default=20, help="Maximum VAR records per FIX")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Random seed for reproducible datasets")
    parser.add_argument("--no-validate", action="store_true", help="Skip post-generation validation")
    return parser


def validate_generated_file(path: str) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    p = Path(path)
    if not p.exists():
        return False, [f"File not found: {path}"]
    # Validate by streaming through the file to avoid loading everything into memory
    with p.open("r", encoding="utf-8") as fh:
        first = None
        last = None
        des_set = set()
        fix_set = set()
        for i, line in enumerate(fh, start=1):
            if i == 1:
                first = line
            last = line
            parts = line.rstrip("\n").split("|")
            if not parts:
                continue
            rec = parts[0]
            if rec == "DES":
                if len(parts) < 15:
                    errors.append(f"L{i} DES: not enough fields")
                    continue
                des_id = parts[1]
                des_set.add(des_id)
            elif rec == "FIX":
                if len(parts) < 16:
                    errors.append(f"L{i} FIX: not enough fields")
                    continue
                des_id = parts[1]
                fix_id = parts[2]
                if des_id not in des_set:
                    errors.append(f"L{i} FIX references unknown DES {des_id}")
                fix_set.add((des_id, fix_id))
            elif rec == "VAR":
                if len(parts) < 5:
                    errors.append(f"L{i} VAR: not enough fields")
                    continue
                des_id = parts[1]
                fix_id = parts[2]
                if des_id not in des_set:
                    errors.append(f"L{i} VAR references unknown DES {des_id}")
                if (des_id, fix_id) not in fix_set:
                    errors.append(f"L{i} VAR references unknown FIX ({des_id}, {fix_id})")

        if first is None:
            return False, ["Empty file"]
        if not first.startswith("000|"):
            errors.append("L1: first line must be 000")
        if last is None or not last.startswith("900|"):
            errors.append("Last line must be 900")

    return (len(errors) == 0), errors


def main() -> None:
    args = build_parser().parse_args()
    output_file = Path(args.out)

    generate_dat_file(
        out_path=str(output_file),
        nb_des=args.nb_des,
        min_fix_per_des=args.min_fix_per_des,
        max_fix_per_des=args.max_fix_per_des,
        min_var_per_fix=args.min_var_per_fix,
        max_var_per_fix=args.max_var_per_fix,
        seed=args.seed,
    )

    if not args.no_validate:
        ok, errs = validate_generated_file(str(output_file))
        if ok:
            log_line("[VALID] Structure et références OK")
        else:
            log_line("[INVALID]")
            for e in errs:
                log_line(f" - {e}")


if __name__ == "__main__":
    main()