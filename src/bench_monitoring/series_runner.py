from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


project_root = Path(__file__).resolve().parents[2]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(obj, file, ensure_ascii=False, indent=2)


def run_command(command: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> None:
    printable = " ".join(shlex.quote(part) for part in command)
    print(f"[RUN] {printable}")
    subprocess.run(command, check=True, env=env, cwd=str(cwd) if cwd is not None else None)


def parse_nb_des_values(raw_values: list[int]) -> list[int]:
    if not raw_values:
        raise ValueError("At least one --nb-des value is required")
    values = list(dict.fromkeys(raw_values))
    if any(value < 0 for value in values):
        raise ValueError("--nb-des values must be >= 0")
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run benchmark series for multiple dataset volumes")
    parser.add_argument("--nb-des", nargs="+", type=int, required=True, help="Dataset volumes to generate, e.g. --nb-des 30 50 100")
    parser.add_argument("--replications", type=int, default=1, help="Number of repetitions to run for each dataset volume")
    parser.add_argument("--seed", type=int, default=123, help="Random seed used for each generated dataset")
    parser.add_argument("--min-fix-per-des", type=int, default=1, help="Minimum FIX records per DES")
    parser.add_argument("--max-fix-per-des", type=int, default=50, help="Maximum FIX records per DES")
    parser.add_argument("--min-var-per-fix", type=int, default=1, help="Minimum VAR records per FIX")
    parser.add_argument("--max-var-per-fix", type=int, default=20, help="Maximum VAR records per FIX")
    parser.add_argument("--data-root", default="data/generated", help="Directory where generated datasets are written")
    parser.add_argument("--results-root", default="results/series", help="Directory where series results are written")
    parser.add_argument("--series-name", default="default", help="Name stored in the series manifest")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue with the next volume if one run fails")
    return parser


def dataset_metadata(path: Path) -> dict[str, Any]:
    size_bytes = path.stat().st_size if path.exists() else None
    line_count = None
    if path.exists():
        with path.open("r", encoding="utf-8") as file:
            line_count = sum(1 for _ in file)
    return {
        "path": str(path),
        "exists": path.exists(),
        "line_count": line_count,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / (1024 * 1024), 3) if size_bytes is not None else None,
    }


def generate_dataset(
    dataset_path: Path,
    nb_des: int,
    *,
    min_fix_per_des: int,
    max_fix_per_des: int,
    min_var_per_fix: int,
    max_var_per_fix: int,
    seed: int,
) -> None:
    command = [
        sys.executable,
        "-m",
        "bench_monitoring.generate_data_set",
        "--out",
        str(dataset_path),
        "--nb-des",
        str(nb_des),
        "--min-fix-per-des",
        str(min_fix_per_des),
        "--max-fix-per-des",
        str(max_fix_per_des),
        "--min-var-per-fix",
        str(min_var_per_fix),
        "--max-var-per-fix",
        str(max_var_per_fix),
        "--seed",
        str(seed),
    ]
    run_command(command, cwd=project_root)


def replication_seed(base_seed: int, replication_index: int) -> int:
    return base_seed + replication_index


def run_monitored_benchmark(command_name: str, app_name: str, out_dir: Path, dataset_path: Path) -> None:
    env = os.environ.copy()
    env["BENCH_DATA_FILE"] = str(dataset_path)
    command = [
        sys.executable,
        "-m",
        "bench_monitoring.monitor_runner",
        "--cmd",
        command_name,
        "--app",
        app_name,
        "--out",
        str(out_dir),
    ]
    run_command(command, env=env, cwd=project_root)


def main() -> None:
    args = build_parser().parse_args()
    nb_des_values = parse_nb_des_values(args.nb_des)
    if args.replications < 1:
        raise ValueError("--replications must be >= 1")

    data_root = (project_root / args.data_root).resolve()
    results_root = (project_root / args.results_root).resolve()
    ensure_dir(data_root)
    ensure_dir(results_root)

    series_manifest: dict[str, Any] = {
        "series_name": args.series_name,
        "seed": args.seed,
        "replications": args.replications,
        "volumes": [],
    }

    for nb_des in nb_des_values:
        volume_entry: dict[str, Any] = {"nb_des": nb_des, "runs": []}
        for replication_index in range(1, args.replications + 1):
            seed = replication_seed(args.seed, replication_index - 1)
            dataset_path = data_root / f"flux_des_fix_var_des{nb_des}_rep{replication_index}_seed{seed}.dat"
            volume_root = results_root / f"des_{nb_des}" / f"rep_{replication_index:02d}"
            etl_out = volume_root / "etl"
            elt_out = volume_root / "elt"
            ensure_dir(volume_root)

            print(f"[INFO] Preparing dataset for nb_des={nb_des}, replication={replication_index}")
            try:
                generate_dataset(
                    dataset_path,
                    nb_des,
                    min_fix_per_des=args.min_fix_per_des,
                    max_fix_per_des=args.max_fix_per_des,
                    min_var_per_fix=args.min_var_per_fix,
                    max_var_per_fix=args.max_var_per_fix,
                    seed=seed,
                )

                print(f"[INFO] Running ETL for nb_des={nb_des}, replication={replication_index}")
                run_monitored_benchmark("bench-monitor-etl", "bench-etl", etl_out, dataset_path)

                print(f"[INFO] Running ELT for nb_des={nb_des}, replication={replication_index}")
                run_monitored_benchmark("bench-monitor-elt", "bench-elt", elt_out, dataset_path)

                volume_entry["runs"].append(
                    {
                        "replication": replication_index,
                        "seed": seed,
                        "dataset": dataset_metadata(dataset_path),
                        "etl_out": str(etl_out),
                        "elt_out": str(elt_out),
                    }
                )
            except Exception as exc:
                print(f"[ERROR] Failed series run for nb_des={nb_des}, replication={replication_index}: {exc}")
                volume_entry["runs"].append(
                    {
                        "replication": replication_index,
                        "seed": seed,
                        "dataset": dataset_metadata(dataset_path),
                        "etl_out": str(etl_out),
                        "elt_out": str(elt_out),
                        "error": str(exc),
                    }
                )
                if not args.continue_on_error:
                    series_manifest["volumes"].append(volume_entry)
                    write_json(results_root / "series_manifest.json", series_manifest)
                    raise

        series_manifest["volumes"].append(volume_entry)

    write_json(results_root / "series_manifest.json", series_manifest)
    print(f"[OK] Series manifest written to {results_root / 'series_manifest.json'}")


if __name__ == "__main__":
    main()