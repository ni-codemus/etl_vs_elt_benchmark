import pytest

from bench_monitoring.elt import ELT_PROFILES
from bench_monitoring.etl import ETL_PROFILES
from bench_monitoring.series_runner import benchmark_command, parse_profile_values


def test_profile_catalogs_expose_expected_variants():
    assert set(ETL_PROFILES) == {"baseline", "copy", "batch"}
    assert set(ELT_PROFILES) == {"baseline", "memory", "analyze", "constraints", "max"}


def test_benchmark_command_builds_profile_specific_cli():
    assert benchmark_command("etl", "baseline") == "bench-monitor-etl --profile baseline"
    assert benchmark_command("etl", "batch") == "bench-monitor-etl --profile batch"
    assert benchmark_command("elt", "max") == "bench-monitor-elt --profile max"


def test_parse_profile_values_rejects_unknown_profile():
    with pytest.raises(ValueError):
        parse_profile_values(["baseline", "unknown"], ELT_PROFILES, "--elt-profiles")
