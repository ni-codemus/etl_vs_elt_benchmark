from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any


project_root = Path(__file__).resolve().parents[2]


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def collect_infra_metadata() -> dict[str, Any]:
    app_root = Path(os.getenv("BENCH_APP_ROOT", "/opt/bench_monitoring"))
    metadata_path = Path(os.getenv("BENCH_INFRA_METADATA", str(app_root / "configs" / "infrastructure.json")))
    file_metadata = read_json_if_exists(metadata_path)

    env_metadata = {
        "project_name": os.getenv("BENCH_PROJECT_NAME"),
        "environment": os.getenv("BENCH_ENVIRONMENT"),
        "ec2_instance_type": os.getenv("BENCH_EC2_INSTANCE_TYPE"),
        "db_instance_class": os.getenv("BENCH_DB_INSTANCE_CLASS"),
        "s3_results_bucket": os.getenv("BENCH_RESULTS_BUCKET"),
        "s3_results_key_prefix": os.getenv("BENCH_RESULTS_KEY_PREFIX"),
        "app_root": os.getenv("BENCH_APP_ROOT"),
        "metadata_path": str(metadata_path),
    }

    infra: dict[str, Any] = {k: v for k, v in file_metadata.items() if v is not None}
    for key, value in env_metadata.items():
        if value is not None:
            infra[key] = value
    return infra


def ts_prefix() -> str:
    return time.strftime("%H:%M:%S")


def log_line(message: str) -> None:
    print(f"[{ts_prefix()}] {message}")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(obj, file, ensure_ascii=False, indent=2)


def run_command(command: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> None:
    printable = " ".join(shlex.quote(part) for part in command)
    log_line(f"[RUN] {printable}")
    subprocess.run(command, check=True, env=env, cwd=str(cwd) if cwd is not None else None)


def parse_nb_des_values(raw_values: list[int]) -> list[int]:
    if not raw_values:
        raise ValueError("At least one --nb-des value is required")
    values = list(dict.fromkeys(raw_values))
    if any(value < 0 for value in values):
        raise ValueError("--nb-des values must be >= 0")
    return values


def parse_profile_values(raw_values: list[str], available: dict[str, Any], option_name: str) -> list[str]:
    if not raw_values:
        raise ValueError(f"At least one {option_name} value is required")
    values = list(dict.fromkeys(raw_values))
    unknown = [value for value in values if value not in available]
    if unknown:
        raise ValueError(f"Unknown {option_name} values: {', '.join(sorted(unknown))}")
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run benchmark series for multiple dataset volumes")
    parser.add_argument("--nb-des", nargs="+", type=int, required=True, help="Dataset volumes to generate, e.g. --nb-des 30 50 100")
    parser.add_argument("--replications", type=int, default=1, help="Number of repetitions to run for each dataset volume")
    parser.add_argument("--etl-profiles", nargs="+", default=["copy"], help="ETL profiles to replay, e.g. copy batch")
    parser.add_argument("--elt-profiles", nargs="+", default=["baseline"], help="ELT profiles to replay, e.g. baseline memory analyze constraints max")
    parser.add_argument("--seed", type=int, default=123, help="Random seed used for each generated dataset")
    parser.add_argument("--min-fix-per-des", type=int, default=1, help="Minimum FIX records per DES")
    parser.add_argument("--max-fix-per-des", type=int, default=50, help="Maximum FIX records per DES")
    parser.add_argument("--min-var-per-fix", type=int, default=1, help="Minimum VAR records per FIX")
    parser.add_argument("--max-var-per-fix", type=int, default=20, help="Maximum VAR records per FIX")
    parser.add_argument("--data-root", default="data/generated", help="Directory where generated datasets are written")
    parser.add_argument("--results-root", default="results/series", help="Directory where series results are written")
    parser.add_argument("--series-name", default="default", help="Name stored in the series manifest")
    parser.add_argument("--s3-bucket", default=os.getenv("BENCH_RESULTS_S3_BUCKET", "my-tfstate-project1-nicode-202506"), help="S3 bucket used to store the results archive")
    parser.add_argument("--s3-key-prefix", default=os.getenv("BENCH_RESULTS_S3_KEY_PREFIX", "bench-monitor-series"), help="S3 key prefix for the uploaded archive")
    parser.add_argument("--skip-s3-upload", action="store_true", help="Skip the final S3 archive upload")
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


def delete_dataset(dataset_path: Path) -> None:
    if not dataset_path.exists():
        return
    dataset_path.unlink()
    log_line(f"[INFO] Deleted dataset {dataset_path}")


def replication_seed(base_seed: int, replication_index: int) -> int:
    return base_seed + replication_index


def benchmark_command(family: str, profile: str) -> str:
    if family == "etl":
        return f"bench-monitor-etl --profile {shlex.quote(profile)}"
    if family == "elt":
        return f"bench-monitor-elt --profile {shlex.quote(profile)}"
    raise ValueError(f"Unknown family: {family}")


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


def create_results_archive(results_root: Path, archive_path: Path) -> None:
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(results_root, arcname=results_root.name)


def upload_archive_to_s3(archive_path: Path, bucket: str, key: str) -> None:
    object_uri = f"s3://{bucket}/{key}"
    subprocess.run(["aws", "s3", "rm", object_uri], cwd=str(project_root), check=False)
    run_command(["aws", "s3", "cp", str(archive_path), object_uri], cwd=project_root)


def main() -> None:
    args = build_parser().parse_args()
    nb_des_values = parse_nb_des_values(args.nb_des)
    if args.replications < 1:
        raise ValueError("--replications must be >= 1")

    from .elt import ELT_PROFILES
    from .etl import ETL_PROFILES

    etl_profiles = parse_profile_values(args.etl_profiles, ETL_PROFILES, "--etl-profiles")
    elt_profiles = parse_profile_values(args.elt_profiles, ELT_PROFILES, "--elt-profiles")

    data_root = (project_root / args.data_root).resolve()
    results_root = (project_root / args.results_root).resolve()
    ensure_dir(data_root)
    ensure_dir(results_root)

    series_manifest: dict[str, Any] = {
        "series_name": args.series_name,
        "seed": args.seed,
        "replications": args.replications,
        "etl_profiles": etl_profiles,
        "elt_profiles": elt_profiles,
        "infra": collect_infra_metadata(),
        "volumes": [],
    }

    for nb_des in nb_des_values:
        volume_entry: dict[str, Any] = {"nb_des": nb_des, "runs": []}
        for replication_index in range(1, args.replications + 1):
            seed = replication_seed(args.seed, replication_index - 1)
            dataset_path = data_root / f"flux_des_fix_var_des{nb_des}_rep{replication_index}_seed{seed}.dat"
            volume_root = results_root / f"des_{nb_des}" / f"rep_{replication_index:02d}"
            ensure_dir(volume_root)

            log_line(f"[INFO] Preparing dataset for nb_des={nb_des}, replication={replication_index}")
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

                run_outputs: list[dict[str, Any]] = []
                for profile in etl_profiles:
                    out_dir = volume_root / f"etl_{profile}"
                    log_line(f"[INFO] Running ETL profile={profile} for nb_des={nb_des}, replication={replication_index}")
                    run_monitored_benchmark(benchmark_command("etl", profile), "bench-etl", out_dir, dataset_path)
                    run_outputs.append({"family": "etl", "profile": profile, "out": str(out_dir)})

                for profile in elt_profiles:
                    out_dir = volume_root / f"elt_{profile}"
                    log_line(f"[INFO] Running ELT profile={profile} for nb_des={nb_des}, replication={replication_index}")
                    run_monitored_benchmark(benchmark_command("elt", profile), "bench-elt", out_dir, dataset_path)
                    run_outputs.append({"family": "elt", "profile": profile, "out": str(out_dir)})

                volume_entry["runs"].append(
                    {
                        "replication": replication_index,
                        "seed": seed,
                        "dataset": dataset_metadata(dataset_path),
                        "benchmarks": run_outputs,
                    }
                )
            except Exception as exc:
                log_line(f"[ERROR] Failed series run for nb_des={nb_des}, replication={replication_index}: {exc}")
                volume_entry["runs"].append(
                    {
                        "replication": replication_index,
                        "seed": seed,
                        "dataset": dataset_metadata(dataset_path),
                        "benchmarks": [],
                        "error": str(exc),
                    }
                )
                if not args.continue_on_error:
                    series_manifest["volumes"].append(volume_entry)
                    write_json(results_root / "series_manifest.json", series_manifest)
                    raise
            finally:
                delete_dataset(dataset_path)

        series_manifest["volumes"].append(volume_entry)

    write_json(results_root / "series_manifest.json", series_manifest)

    if not args.skip_s3_upload:
        archive_name = f"{args.series_name}.tar.gz"
        s3_key_prefix = args.s3_key_prefix.strip("/")
        s3_key = f"{s3_key_prefix}/{archive_name}" if s3_key_prefix else archive_name
        with tempfile.TemporaryDirectory(prefix="bench_series_archive_") as tmp_dir:
            archive_path = Path(tmp_dir) / archive_name
            log_line(f"[INFO] Creating results archive from {results_root}")
            create_results_archive(results_root, archive_path)
            log_line(f"[INFO] Uploading archive to s3://{args.s3_bucket}/{s3_key}")
            upload_archive_to_s3(archive_path, args.s3_bucket, s3_key)
        series_manifest["s3_archive"] = {
            "bucket": args.s3_bucket,
            "key": s3_key,
            "source": str(results_root),
        }
        write_json(results_root / "series_manifest.json", series_manifest)

    log_line(f"[OK] Series manifest written to {results_root / 'series_manifest.json'}")


if __name__ == "__main__":
    main()