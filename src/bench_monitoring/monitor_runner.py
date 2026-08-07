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
from typing import Any, Dict, List, Optional, Tuple

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
        f"postgresql://{quote_plus(user)}:{quote_plus(password)}"
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
    target_vms_mb: float
    target_threads: int
    target_children_count: int
    target_cpu_percent_with_children: float
    target_rss_mb_with_children: float
    net_host_rx_Bps: Optional[float]
    net_host_tx_Bps: Optional[float]
    net_target_sock_inodes_count: Optional[int]
    net_target_tx_queue_bytes: Optional[int]
    net_target_rx_queue_bytes: Optional[int]
    net_target_est_tx_Bps: Optional[float]
    net_target_est_rx_Bps: Optional[float]
    db_enabled: bool
    db_state: Optional[str]
    db_wait_event_type: Optional[str]
    db_wait_event: Optional[str]
    db_query_age_sec: Optional[float]
    db_active_sessions_for_app: Optional[int]
    db_blks_read: Optional[int]
    db_blks_hit: Optional[int]
    db_tup_returned: Optional[int]
    db_tup_fetched: Optional[int]
    db_tup_inserted: Optional[int]
    db_tup_updated: Optional[int]
    db_tup_deleted: Optional[int]
    db_blk_read_time_ms: Optional[float]
    db_blk_write_time_ms: Optional[float]
    db_session_pids: Optional[str]
    db_session_commit_total: Optional[int]
    db_session_commit_rate_per_sec: Optional[float]
    db_session_commit_total_all_seen: Optional[int]


class PgMonitor:
    def __init__(self, dsn: Optional[str], app_name: Optional[str]):
        self.dsn = dsn
        self.app_name = app_name
        self.enabled = False
        self.conn = None
        self.last_xact_start_by_pid: Dict[int, Optional[datetime]] = {}
        self.last_state_by_pid: Dict[int, Optional[str]] = {}
        self.commit_count_by_pid: Dict[int, int] = {}
        self.seen_pids: set[int] = set()
        self._last_sample_ts: Optional[float] = None
        self._last_total_active_commits: Optional[int] = None

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
        # Snapshot the client backends created by the monitored application.
        # These rows drive the session state and wait-event fields in the CSV.
        q = """
        SELECT pid, state, xact_start, wait_event_type, wait_event,
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

    def _fetch_db_counters(self) -> Dict[str, Any]:
        # Database-wide counters since the last PostgreSQL reset.
        # They are cumulative, so they are useful to compare activity across a run,
        # but they are not per-query or per-process exact values.
        out = {
            "db_blks_read": None,
            "db_blks_hit": None,
            "db_tup_returned": None,
            "db_tup_fetched": None,
            "db_tup_inserted": None,
            "db_tup_updated": None,
            "db_tup_deleted": None,
            "db_blk_read_time_ms": None,
            "db_blk_write_time_ms": None,
        }
        q = """
        SELECT blks_read, blks_hit, tup_returned, tup_fetched, tup_inserted, tup_updated, tup_deleted, blk_read_time, blk_write_time
        FROM pg_stat_database
        WHERE datname = current_database()
        """
        with self.conn.cursor() as cur:
            cur.execute(q)
            row = cur.fetchone()
            if row:
                out["db_blks_read"] = row[0]
                out["db_blks_hit"] = row[1]
                out["db_tup_returned"] = row[2]
                out["db_tup_fetched"] = row[3]
                out["db_tup_inserted"] = row[4]
                out["db_tup_updated"] = row[5]
                out["db_tup_deleted"] = row[6]
                out["db_blk_read_time_ms"] = row[7]
                out["db_blk_write_time_ms"] = row[8]
        return out

    def _update_commit_estimation(self, rows: List[Tuple], now_ts: float) -> Dict[str, Any]:
        active_pids = set()
        representative = {
            "db_state": None,
            "db_wait_event_type": None,
            "db_wait_event": None,
            "db_query_age_sec": None,
        }
        best_age = -1.0
        for r in rows:
            pid, state, xact_start, wait_event_type, wait_event, query_age_sec = r
            active_pids.add(pid)
            self.seen_pids.add(pid)
            old_xact = self.last_xact_start_by_pid.get(pid)
            old_state = self.last_state_by_pid.get(pid)
            self.commit_count_by_pid.setdefault(pid, 0)
            if old_xact is not None and xact_start is not None and old_xact != xact_start:
                self.commit_count_by_pid[pid] += 1
            if old_state in ("active", "idle in transaction", "idle in transaction (aborted)") and state == "idle":
                if not (old_xact is not None and xact_start is not None and old_xact != xact_start):
                    if old_xact is not None:
                        self.commit_count_by_pid[pid] += 1
            self.last_xact_start_by_pid[pid] = xact_start
            self.last_state_by_pid[pid] = state
            if state == "active":
                # Keep the most recent active query as a representative sample.
                age = query_age_sec if query_age_sec is not None else -1.0
                if age > best_age:
                    best_age = age
                    representative["db_state"] = state
                    representative["db_wait_event_type"] = wait_event_type
                    representative["db_wait_event"] = wait_event
                    representative["db_query_age_sec"] = query_age_sec
        disappeared = set(self.last_state_by_pid.keys()) - active_pids
        for pid in disappeared:
            self.last_state_by_pid.pop(pid, None)
            self.last_xact_start_by_pid.pop(pid, None)
        total_active_commits = sum(self.commit_count_by_pid.get(pid, 0) for pid in active_pids)
        total_all_seen = sum(self.commit_count_by_pid.values())
        rate = None
        if self._last_sample_ts is not None and self._last_total_active_commits is not None:
            dt = now_ts - self._last_sample_ts
            if dt > 0:
                rate = (total_active_commits - self._last_total_active_commits) / dt
        self._last_sample_ts = now_ts
        self._last_total_active_commits = total_active_commits
        return {
            **representative,
            "db_active_sessions_for_app": len(active_pids),
            "db_session_pids": ",".join(str(p) for p in sorted(active_pids)) if active_pids else "",
            "db_session_commit_total": int(total_active_commits),
            "db_session_commit_rate_per_sec": rate,
            "db_session_commit_total_all_seen": int(total_all_seen),
        }

    def sample(self, now_ts: float) -> Dict[str, Any]:
        if not self.enabled:
            return {}
        out = {
            "db_state": None,
            "db_wait_event_type": None,
            "db_wait_event": None,
            "db_query_age_sec": None,
            "db_active_sessions_for_app": None,
            "db_session_pids": None,
            "db_session_commit_total": None,
            "db_session_commit_rate_per_sec": None,
            "db_session_commit_total_all_seen": None,
            "db_blks_read": None,
            "db_blks_hit": None,
            "db_tup_returned": None,
            "db_tup_fetched": None,
            "db_tup_inserted": None,
            "db_tup_updated": None,
            "db_tup_deleted": None,
            "db_blk_read_time_ms": None,
            "db_blk_write_time_ms": None,
        }
        try:
            rows = self._fetch_activity_rows()
            out.update(self._update_commit_estimation(rows, now_ts))
            out.update(self._fetch_db_counters())
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
            "target_vms_mb": 0.0,
            "target_threads": 0,
            "target_children_count": 0,
            "target_cpu_percent_with_children": 0.0,
            "target_rss_mb_with_children": 0.0,
        }
    try:
        mem = proc.memory_info()
        cpu = proc.cpu_percent(interval=None)
        threads = proc.num_threads()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {
            "target_alive": False,
            "target_cpu_percent": 0.0,
            "target_rss_mb": 0.0,
            "target_vms_mb": 0.0,
            "target_threads": 0,
            "target_children_count": 0,
            "target_cpu_percent_with_children": 0.0,
            "target_rss_mb_with_children": 0.0,
        }
    children = []
    try:
        children = proc.children(recursive=True)
    except Exception:
        children = []
    total_cpu = cpu
    total_rss = mem.rss
    for ch in children:
        try:
            total_cpu += ch.cpu_percent(interval=None)
            total_rss += ch.memory_info().rss
        except Exception:
            pass
    return {
        "target_alive": True,
        "target_cpu_percent": cpu,
        "target_rss_mb": mb(mem.rss),
        "target_vms_mb": mb(mem.vms),
        "target_threads": threads,
        "target_children_count": len(children),
        "target_cpu_percent_with_children": total_cpu,
        "target_rss_mb_with_children": mb(total_rss),
    }


def estimate_target_network_linux(pid: int, prev: Optional[Dict[str, Any]], now_ts: float) -> Dict[str, Any]:
    if os.name != "posix" or not os.path.exists("/proc"):
        return {
            "net_target_sock_inodes_count": None,
            "net_target_tx_queue_bytes": None,
            "net_target_rx_queue_bytes": None,
            "net_target_est_tx_Bps": None,
            "net_target_est_rx_Bps": None,
            "_state": prev,
        }
    inodes = _linux_proc_socket_inodes(pid)
    inode_set = set(inodes)
    table = _linux_read_proc_net_tcp()
    tx_q = 0
    rx_q = 0
    for inode in inode_set:
        if inode in table:
            tx, rx = table[inode]
            tx_q += tx
            rx_q += rx
    est_tx = None
    est_rx = None
    if prev and prev.get("ts") is not None:
        dt = now_ts - prev["ts"]
        if dt > 0:
            # This is only an estimate derived from socket queue deltas.
            # It is not an exact per-process bytes-sent/bytes-received counter.
            est_tx = (tx_q - prev.get("tx_q", tx_q)) / dt
            est_rx = (rx_q - prev.get("rx_q", rx_q)) / dt
    new_state = {"ts": now_ts, "tx_q": tx_q, "rx_q": rx_q}
    return {
        "net_target_sock_inodes_count": len(inode_set),
        "net_target_tx_queue_bytes": tx_q,
        "net_target_rx_queue_bytes": rx_q,
        "net_target_est_tx_Bps": est_tx,
        "net_target_est_rx_Bps": est_rx,
        "_state": new_state,
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


def summarize(samples: List[Sample], exit_code: int, cmd: str, app_name: str) -> Dict[str, Any]:
    def arr(field):
        return [getattr(s, field) for s in samples if getattr(s, field) is not None]

    def stats(vals):
        if not vals:
            return {}
        return {"min": min(vals), "max": max(vals), "avg": statistics.fmean(vals)}

    total_all_seen = 0
    for s in reversed(samples):
        if s.db_session_commit_total_all_seen is not None:
            total_all_seen = s.db_session_commit_total_all_seen
            break
    wait_events_seen = sorted({(s.db_wait_event_type, s.db_wait_event) for s in samples if s.db_wait_event_type is not None or s.db_wait_event is not None})
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
            "net_rx_Bps": stats(arr("net_host_rx_Bps")),
            "net_tx_Bps": stats(arr("net_host_tx_Bps")),
        },
        "target_process": {
            "cpu_percent": stats(arr("target_cpu_percent")),
            "rss_mb": stats(arr("target_rss_mb")),
            "cpu_percent_with_children": stats(arr("target_cpu_percent_with_children")),
            "rss_mb_with_children": stats(arr("target_rss_mb_with_children")),
            "net_est_tx_Bps": stats(arr("net_target_est_tx_Bps")),
            "net_est_rx_Bps": stats(arr("net_target_est_rx_Bps")),
        },
        "postgres": {
            "enabled": any(s.db_enabled for s in samples),
            "wait_events_seen": wait_events_seen,
            "session_commit_estimation": {
                "total_commits_estimated_all_seen_pids": total_all_seen,
                "commit_rate_per_sec": stats(arr("db_session_commit_rate_per_sec")),
                "method": "xact_start/state transitions from pg_stat_activity per PID (best effort)",
            },
            "note": "wait_event = attente logique PostgreSQL (pas iowait OS serveur).",
        },
        "network_note": [
            "net_host_* = débit réel machine (compteurs cumulés OS).",
            "net_target_est_* = estimation Linux basée sur variation des tx/rx socket queues, pas un compteur exact bytes sent/recv par process.",
        ],
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
    last_net_ts = time.time()
    last_bytes_recv = net0.bytes_recv
    last_bytes_sent = net0.bytes_sent
    last_target_net_state = None

    pgm = PgMonitor(effective_dsn, app_name)
    pgm.start()

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
        nic = psutil.net_io_counters()
        dt_net = ts - last_net_ts
        host_rx_Bps = None
        host_tx_Bps = None
        if dt_net > 0:
            host_rx_Bps = (nic.bytes_recv - last_bytes_recv) / dt_net
            host_tx_Bps = (nic.bytes_sent - last_bytes_sent) / dt_net
        last_bytes_recv = nic.bytes_recv
        last_bytes_sent = nic.bytes_sent
        last_net_ts = ts

        pm = collect_proc_tree_metrics(target_proc)
        tnet = estimate_target_network_linux(proc_sub.pid, last_target_net_state, ts)
        last_target_net_state = tnet.get("_state")
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
            target_vms_mb=pm["target_vms_mb"],
            target_threads=pm["target_threads"],
            target_children_count=pm["target_children_count"],
            target_cpu_percent_with_children=pm["target_cpu_percent_with_children"],
            target_rss_mb_with_children=pm["target_rss_mb_with_children"],
            net_host_rx_Bps=host_rx_Bps,
            net_host_tx_Bps=host_tx_Bps,
            net_target_sock_inodes_count=tnet.get("net_target_sock_inodes_count"),
            net_target_tx_queue_bytes=tnet.get("net_target_tx_queue_bytes"),
            net_target_rx_queue_bytes=tnet.get("net_target_rx_queue_bytes"),
            net_target_est_tx_Bps=tnet.get("net_target_est_tx_Bps"),
            net_target_est_rx_Bps=tnet.get("net_target_est_rx_Bps"),
            db_enabled=pgm.enabled,
            db_state=dbm.get("db_state"),
            db_wait_event_type=dbm.get("db_wait_event_type"),
            db_wait_event=dbm.get("db_wait_event"),
            db_query_age_sec=dbm.get("db_query_age_sec"),
            db_active_sessions_for_app=dbm.get("db_active_sessions_for_app"),
            db_blks_read=dbm.get("db_blks_read"),
            db_blks_hit=dbm.get("db_blks_hit"),
            db_tup_returned=dbm.get("db_tup_returned"),
            db_tup_fetched=dbm.get("db_tup_fetched"),
            db_tup_inserted=dbm.get("db_tup_inserted"),
            db_tup_updated=dbm.get("db_tup_updated"),
            db_tup_deleted=dbm.get("db_tup_deleted"),
            db_blk_read_time_ms=dbm.get("db_blk_read_time_ms"),
            db_blk_write_time_ms=dbm.get("db_blk_write_time_ms"),
            db_session_pids=dbm.get("db_session_pids"),
            db_session_commit_total=dbm.get("db_session_commit_total"),
            db_session_commit_rate_per_sec=dbm.get("db_session_commit_rate_per_sec"),
            db_session_commit_total_all_seen=dbm.get("db_session_commit_total_all_seen"),
        ))

        if not alive:
            break
        time.sleep(sample_interval)

    t_out.join(timeout=3)
    t_err.join(timeout=3)
    pgm.stop()

    exit_code = proc_sub.returncode
    write_csv(os.path.join(run_dir, "timeseries.csv"), samples)
    write_json(os.path.join(run_dir, "summary.json"), summarize(samples, exit_code, cmd, app_name))
    with open(os.path.join(run_dir, "stdout.log"), "w", encoding="utf-8") as f:
        f.writelines(stdout_lines)
    with open(os.path.join(run_dir, "stderr.log"), "w", encoding="utf-8") as f:
        f.writelines(stderr_lines)

    print(f"[OK] exit_code={exit_code}")
    print(f"[OK] {os.path.join(run_dir, 'timeseries.csv')}")
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