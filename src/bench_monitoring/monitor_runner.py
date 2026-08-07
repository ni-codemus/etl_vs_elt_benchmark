from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import statistics
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus
from typing import Any, Dict, List, Optional, Tuple, cast

import psutil
from dotenv import load_dotenv

try:
    import psycopg

    HAS_PSYCOPG = True
except Exception:
    HAS_PSYCOPG = False


def mb(x: int) -> float:
    return x / (1024 * 1024)


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


project_root = Path(__file__).resolve().parents[2]
env_file = project_root / "configs" / ".env"
if env_file.exists():
    load_dotenv(env_file)


def build_dsn_from_pg_env() -> Optional[str]:
    host = os.getenv("PG_HOST")
    port = os.getenv("PG_PORT")
    dbname = os.getenv("PG_DBNAME")
    user = os.getenv("PG_SUPER_USER")
    password = os.getenv("PG_SUPER_PASS")
    if not all([host, port, dbname, user, password]):
        return None
    return (
        f"postgresql://{quote_plus(cast(str, user))}:{quote_plus(cast(str, password))}"
        f"@{host}:{port}/{dbname}"
    )


def resolve_input_dataset_file() -> Path:
    return Path(os.getenv("BENCH_DATA_FILE", project_root / "data" / "flux_des_fix_var.dat"))


def get_input_dataset_metadata() -> Dict[str, Any]:
    dataset_file = resolve_input_dataset_file()
    metadata: Dict[str, Any] = {
        "path": str(dataset_file),
        "exists": dataset_file.exists(),
        "line_count": None,
        "size_bytes": None,
        "size_mb": None,
    }
    if not dataset_file.exists():
        return metadata

    metadata["size_bytes"] = dataset_file.stat().st_size
    metadata["size_mb"] = round(metadata["size_bytes"] / (1024 * 1024), 3)
    with dataset_file.open("r", encoding="utf-8") as file:
        metadata["line_count"] = sum(1 for _ in file)
    return metadata


def _linux_read_proc_net_tcp() -> Dict[str, Tuple[int, int]]:
    out: Dict[str, Tuple[int, int]] = {}
    for p in ["/proc/net/tcp", "/proc/net/tcp6"]:
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines[1:]:
                cols = line.strip().split()
                if len(cols) < 10:
                    continue
                txrx = cols[4]
                inode = cols[9]
                if ":" not in txrx:
                    continue
                tx_hex, rx_hex = txrx.split(":")
                out[inode] = (int(tx_hex, 16), int(rx_hex, 16))
        except Exception:
            pass
    return out


def _linux_proc_socket_inodes(pid: int) -> List[str]:
    inodes = []
    fd_dir = f"/proc/{pid}/fd"
    if not os.path.isdir(fd_dir):
        return inodes
    try:
        for fd in os.listdir(fd_dir):
            try:
                target = os.readlink(os.path.join(fd_dir, fd))
                if target.startswith("socket:[") and target.endswith("]"):
                    inodes.append(target[len("socket:[") : -1])
            except Exception:
                continue
    except Exception:
        return inodes
    return inodes


@dataclass
class Sample:
    ts_epoch: float
    t_rel_sec: float
    sys_cpu_percent: float
    sys_ram_used_mb: float
    sys_ram_percent: float
    target_pid: int
    target_alive: bool
    target_cpu_percent: float
    target_rss_mb: float
    db_enabled: bool
    db_state: Optional[str]
    db_wait_event_type: Optional[str]
    db_wait_event: Optional[str]
    db_query_age_sec: Optional[float]


class PgMonitor:
    def __init__(self, dsn: Optional[str], app_name: Optional[str]):
        self.dsn = dsn
        self.app_name = app_name
        self.enabled = False
        self.conn = None

    def start(self):
        if not self.dsn or not HAS_PSYCOPG:
            self.enabled = False
            return
        try:
            self.conn = psycopg.connect(self.dsn)
            self.conn.autocommit = True
            self.enabled = True
        except Exception as e:
            print(f"[WARN] PG monitor disabled: {e}")
            self.enabled = False

    def stop(self):
        if self.conn:
            self.conn.close()

    def _fetch_activity_rows(self) -> List[Tuple]:
        if not self.app_name:
            return []
        assert self.conn is not None
        # Snapshot the client backends created by the monitored application.
        # These rows drive the session state and wait-event fields in the CSV.
        q = """
        SELECT pid, state, wait_event_type, wait_event,
               CASE WHEN query_start IS NULL THEN NULL
                    ELSE EXTRACT(EPOCH FROM (clock_timestamp() - query_start))::double precision
               END AS query_age_sec
        FROM pg_stat_activity
        WHERE application_name = %s
          AND backend_type = 'client backend'
        """
        with self.conn.cursor() as cur:
            cur.execute(q, (self.app_name,))
            return cur.fetchall()

    def _fetch_wal_counters(self) -> Dict[str, Any]:
        assert self.conn is not None
        q = """
        SELECT wal_records, wal_fpi, wal_bytes, wal_buffers_full, wal_write, wal_sync, wal_write_time, wal_sync_time
        FROM pg_stat_wal
        """
        with self.conn.cursor() as cur:
            cur.execute(q)
            row = cur.fetchone()
            if not row:
                return {}
        return {
            "wal_records": row[0],
            "wal_fpi": row[1],
            "wal_bytes": row[2],
            "wal_buffers_full": row[3],
            "wal_write": row[4],
            "wal_sync": row[5],
            "wal_write_time_ms": row[6],
            "wal_sync_time_ms": row[7],
        }

    def _fetch_io_counters(self) -> Dict[str, Any]:
        assert self.conn is not None
        q = """
        SELECT object, context,
               SUM(reads) AS reads,
               SUM(read_time) AS read_time_ms,
               SUM(writes) AS writes,
               SUM(write_time) AS write_time_ms,
               SUM(writebacks) AS writebacks,
               SUM(writeback_time) AS writeback_time_ms,
               SUM(extends) AS extends,
               SUM(extend_time) AS extend_time_ms,
               SUM(hits) AS hits,
               SUM(evictions) AS evictions,
               SUM(reuses) AS reuses,
               SUM(fsyncs) AS fsyncs,
               SUM(fsync_time) AS fsync_time_ms
        FROM pg_stat_io
        GROUP BY object, context
        """
        result: Dict[str, Any] = {"relation": {}, "temp relation": {}}
        with self.conn.cursor() as cur:
            cur.execute(q)
            for row in cur.fetchall():
                object_name, context = row[0], row[1]
                if object_name not in result:
                    continue
                result[object_name][context] = {
                    "reads": row[2],
                    "read_time_ms": row[3],
                    "writes": row[4],
                    "write_time_ms": row[5],
                    "writebacks": row[6],
                    "writeback_time_ms": row[7],
                    "extends": row[8],
                    "extend_time_ms": row[9],
                    "hits": row[10],
                    "evictions": row[11],
                    "reuses": row[12],
                    "fsyncs": row[13],
                    "fsync_time_ms": row[14],
                }
        return result

    def _fetch_bgwriter_counters(self) -> Dict[str, Any]:
        assert self.conn is not None
        q = """
        SELECT checkpoint_write_time, checkpoint_sync_time, buffers_checkpoint, buffers_backend
        FROM pg_stat_bgwriter
        """
        with self.conn.cursor() as cur:
            cur.execute(q)
            row = cur.fetchone()
            if not row:
                return {}
        return {
            "checkpoint_write_time_ms": row[0],
            "checkpoint_sync_time_ms": row[1],
            "buffers_checkpoint": row[2],
            "buffers_backend": row[3],
        }

    def _fetch_database_io_counters(self) -> Dict[str, Any]:
        assert self.conn is not None
        q = """
        SELECT temp_files, temp_bytes
        FROM pg_stat_database
        WHERE datname = current_database()
        """
        with self.conn.cursor() as cur:
            cur.execute(q)
            row = cur.fetchone()
            if not row:
                return {}
        return {
            "temp_files": row[0],
            "temp_bytes": row[1],
        }

    def snapshot(self) -> Dict[str, Any]:
        if not self.enabled:
            return {}
        try:
            return {
                "wal": self._fetch_wal_counters(),
                "io": self._fetch_io_counters(),
                "bgwriter": self._fetch_bgwriter_counters(),
                "database": self._fetch_database_io_counters(),
            }
        except Exception as e:
            print(f"[WARN] PG snapshot error: {e}")
            return {}

    def sample(self, now_ts: float) -> Dict[str, Any]:
        if not self.enabled:
            return {}
        out = {
            "db_state": None,
            "db_wait_event_type": None,
            "db_wait_event": None,
            "db_query_age_sec": None,
        }
        try:
            rows = self._fetch_activity_rows()
            if rows:
                pid, state, wait_event_type, wait_event, query_age_sec = rows[0]
                out["db_state"] = state
                out["db_wait_event_type"] = wait_event_type
                out["db_wait_event"] = wait_event
                out["db_query_age_sec"] = query_age_sec
        except Exception as e:
            print(f"[WARN] PG sample error: {e}")
        return out


def collect_proc_tree_metrics(proc: psutil.Process) -> Dict[str, Any]:
    alive = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    if not alive:
        return {
            "target_alive": False,
            "target_cpu_percent": 0.0,
            "target_rss_mb": 0.0,
        }
    try:
        mem = proc.memory_info()
        cpu = proc.cpu_percent(interval=None)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {
            "target_alive": False,
            "target_cpu_percent": 0.0,
            "target_rss_mb": 0.0,
        }
    return {
        "target_alive": True,
        "target_cpu_percent": cpu,
        "target_rss_mb": mb(mem.rss),
    }


def write_csv(path: str, rows: List[Sample]):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for r in rows:
            writer.writerow(asdict(r))


def write_json(path: str, obj: Dict[str, Any]):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def read_json_if_exists(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def delta_value(start: Any, end: Any) -> Any:
    if isinstance(start, (int, float)) and isinstance(end, (int, float)):
        return end - start
    return None


def delta_snapshot(start: Any, end: Any) -> Any:
    if isinstance(start, dict) and isinstance(end, dict):
        keys = set(start) | set(end)
        out: Dict[str, Any] = {}
        for key in keys:
            out[key] = delta_snapshot(start.get(key), end.get(key))
        return out
    return {
        "start": start,
        "end": end,
        "delta": delta_value(start, end),
    }


def summarize(samples: List[Sample], exit_code: int, cmd: str, app_name: str, pg_start: Dict[str, Any], pg_end: Dict[str, Any]) -> Dict[str, Any]:
    def arr(field):
        return [getattr(s, field) for s in samples if getattr(s, field) is not None]

    def stats(vals):
        if not vals:
            return {}
        return {"min": min(vals), "max": max(vals), "avg": statistics.fmean(vals)}

    wait_events_seen = sorted({(s.db_wait_event_type, s.db_wait_event) for s in samples if s.db_wait_event_type is not None or s.db_wait_event is not None})
    wal_bytes = arr("db_wal_bytes")
    wal_records = arr("db_wal_records")
    wal_write_time = arr("db_wal_write_time_ms")
    wal_sync_time = arr("db_wal_sync_time_ms")
    return {
        "command": cmd,
        "application_name": app_name,
        "exit_code": exit_code,
        "input_dataset": get_input_dataset_metadata(),
        "n_samples": len(samples),
        "duration_sec": (samples[-1].t_rel_sec - samples[0].t_rel_sec) if len(samples) > 1 else 0.0,
        "host": {
            "cpu_percent": stats(arr("sys_cpu_percent")),
            "ram_percent": stats(arr("sys_ram_percent")),
            "ram_used_mb": stats(arr("sys_ram_used_mb")),
        },
        "target_process": {
            "cpu_percent": stats(arr("target_cpu_percent")),
            "rss_mb": stats(arr("target_rss_mb")),
        },
        "postgres": {
            "enabled": any(s.db_enabled for s in samples),
            "wait_events_seen": wait_events_seen,
            "run_counters": delta_snapshot(pg_start, pg_end),
            "note": "wait_event = attente logique PostgreSQL (pas iowait OS serveur).",
        },
    }


def monitor_command(cmd: str, out_dir: str, sample_interval: float = 0.2, db_dsn: Optional[str] = None, app_name: str = "py-monitored-app"):
    ensure_dir(out_dir)
    run_id = f"run_{int(time.time())}"
    run_dir = os.path.join(out_dir, run_id)
    ensure_dir(run_dir)

    effective_dsn = db_dsn or build_dsn_from_pg_env()

    env = os.environ.copy()
    env["PGAPPNAME"] = app_name
    env["APP_NAME"] = app_name
    phase_summary_path = os.path.join(run_dir, "phase_times.json")
    env["BENCH_PHASE_TIMES_PATH"] = phase_summary_path

    print(f"[INFO] Launch: {cmd}")
    print(f"[INFO] Run dir: {run_dir}")
    print(f"[INFO] PG application_name tag expected: {app_name}")
    if effective_dsn:
        print("[INFO] PostgreSQL monitoring connection: enabled")
    else:
        print("[WARN] PostgreSQL monitoring connection: disabled (missing --dsn/DB_DSN and PG_* env vars)")

    proc_sub = subprocess.Popen(shlex.split(cmd), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    target_proc = psutil.Process(proc_sub.pid)

    psutil.cpu_percent(interval=None)
    target_proc.cpu_percent(interval=None)
    for ch in target_proc.children(recursive=True):
        try:
            ch.cpu_percent(interval=None)
        except Exception:
            pass

    net0 = psutil.net_io_counters()

    pgm = PgMonitor(effective_dsn, app_name)
    pgm.start()
    pg_start = pgm.snapshot()

    stdout_lines: List[str] = []
    stderr_lines: List[str] = []

    def drain(stream, sink):
        for line in stream:
            sink.append(line)

    t_out = threading.Thread(target=drain, args=(proc_sub.stdout, stdout_lines), daemon=True)
    t_err = threading.Thread(target=drain, args=(proc_sub.stderr, stderr_lines), daemon=True)
    t_out.start(); t_err.start()

    t0 = time.perf_counter()
    samples: List[Sample] = []
    while True:
        alive = proc_sub.poll() is None
        ts = time.time()
        t_rel = time.perf_counter() - t0
        vm = psutil.virtual_memory()
        sys_cpu = psutil.cpu_percent(interval=None)

        pm = collect_proc_tree_metrics(target_proc)
        dbm = pgm.sample(ts)

        # Sample layout:
        # - system metrics: host load and memory from psutil
        # - target process metrics: cpu/memory/thread counts for the benchmark command
        # - target network metrics: Linux-only socket queue estimates
        # - PostgreSQL metrics: db counters plus session/wait snapshots for the app_name
        samples.append(Sample(
            ts_epoch=ts,
            t_rel_sec=t_rel,
            sys_cpu_percent=sys_cpu,
            sys_ram_used_mb=mb(vm.used),
            sys_ram_percent=vm.percent,
            target_pid=proc_sub.pid,
            target_alive=pm["target_alive"],
            target_cpu_percent=pm["target_cpu_percent"],
            target_rss_mb=pm["target_rss_mb"],
            db_enabled=pgm.enabled,
            db_state=dbm.get("db_state"),
            db_wait_event_type=dbm.get("db_wait_event_type"),
            db_wait_event=dbm.get("db_wait_event"),
            db_query_age_sec=dbm.get("db_query_age_sec"),
        ))

        if not alive:
            break
        time.sleep(sample_interval)

    t_out.join(timeout=3)
    t_err.join(timeout=3)
    pg_end = pgm.snapshot()
    pgm.stop()

    exit_code = proc_sub.returncode
    write_csv(os.path.join(run_dir, "timeseries.csv"), samples)
    summary = summarize(samples, exit_code, cmd, app_name, pg_start, pg_end)
    phase_summary = read_json_if_exists(phase_summary_path)
    if phase_summary:
        summary["phase_summary"] = phase_summary
    write_json(os.path.join(run_dir, "summary.json"), summary)
    with open(os.path.join(run_dir, "stdout.log"), "w", encoding="utf-8") as f:
        f.writelines(stdout_lines)
    with open(os.path.join(run_dir, "stderr.log"), "w", encoding="utf-8") as f:
        f.writelines(stderr_lines)

    print(f"[OK] exit_code={exit_code}")
    print(f"[OK] {os.path.join(run_dir, 'timeseries.csv')}")
    if phase_summary:
        print(f"[OK] {phase_summary_path}")
    print(f"[OK] {os.path.join(run_dir, 'summary.json')}")
    print(f"[OK] {os.path.join(run_dir, 'stdout.log')}")
    print(f"[OK] {os.path.join(run_dir, 'stderr.log')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch and monitor a benchmark command")
    parser.add_argument("--cmd", required=True, help='Commande à lancer, ex: "bench-monitor-etl"')
    parser.add_argument("--dsn", default=os.getenv("DB_DSN"), help="DSN PostgreSQL monitoring (optionnel)")
    parser.add_argument("--app", default="bench-monitor", help="application_name PostgreSQL attendu")
    parser.add_argument("--out", default="./monitor_output", help="Dossier de sortie")
    parser.add_argument("--interval", type=float, default=0.2, help="Intervalle de sampling en secondes")
    args = parser.parse_args()

    monitor_command(cmd=args.cmd, out_dir=args.out, sample_interval=args.interval, db_dsn=args.dsn, app_name=args.app)


if __name__ == "__main__":
    main()