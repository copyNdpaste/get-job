import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\nset -eu\n" + body)
    path.chmod(0o755)


def run_launcher(tmp_path, state, *args):
    shutil.copyfile(ROOT / "run.sh", tmp_path / "run.sh")
    (tmp_path / ".env").write_text("")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable(
        bin_dir / "docker",
        """
case "$1 $2" in
  "version --format")
    if [ "$ENGINE_STATE" = permission ]; then
      echo "permission denied while trying to connect to the docker API" >&2
      exit 1
    fi
    if [ "$ENGINE_STATE" = healthy ] || [ -f engine-ready ]; then
      echo "29.4.0"
      exit 0
    fi
    exit 1 ;;
  "context show") echo "${TEST_CONTEXT:-orbstack}" ;;
  "compose ps") echo "synthetic-container" ;;
  *) exit 99 ;;
esac
""",
    )
    executable(
        bin_dir / "orbctl",
        """
echo "$*" >> engine-actions
case "$1" in
  start) [ "$ENGINE_STATE" != stopped ] || touch engine-ready ;;
  restart) touch engine-ready ;;
  *) exit 99 ;;
esac
""",
    )
    executable(bin_dir / "timeout", 'shift 2\nexec "$@"\n')
    executable(bin_dir / "curl", "exit 0\n")
    executable(bin_dir / "sleep", "exit 0\n")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "ENGINE_STATE": state,
    }
    for name in ("DOCKER_HOST", "DOCKER_CONTEXT"):
        env.pop(name, None)
    return subprocess.run(
        ["/bin/sh", "run.sh", "--no-open", *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_healthy_engine_does_not_restart_other_containers(tmp_path):
    result = run_launcher(tmp_path, "healthy")
    assert result.returncode == 0, result.stderr
    assert "이미 정상 실행 중" in result.stdout
    assert not (tmp_path / "engine-actions").exists()


def test_stopped_orbstack_is_started_through_its_engine_cli(tmp_path):
    result = run_launcher(tmp_path, "stopped")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "engine-actions").read_text() == "start\n"


def test_wedged_engine_reports_explicit_recovery_without_automatic_restart(tmp_path):
    result = run_launcher(tmp_path, "wedged")
    assert result.returncode == 1
    assert "--repair-docker" in result.stderr
    assert (tmp_path / "engine-actions").read_text() == "start\n"


def test_explicit_repair_recovers_wedged_docker(tmp_path):
    result = run_launcher(tmp_path, "wedged", "--repair-docker")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "engine-actions").read_text() == "restart docker\n"


def test_permission_error_does_not_start_or_restart_engine(tmp_path):
    result = run_launcher(tmp_path, "permission")
    assert result.returncode == 1
    assert "접근 권한" in result.stderr
    assert not (tmp_path / "engine-actions").exists()


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("raise SystemExit(7)", 7),
        (
            "import signal,time; signal.signal(signal.SIGALRM, signal.SIG_IGN); "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(20)",
            124,
        ),
    ],
)
def test_perl_watchdog_preserves_exit_status_and_kills_unresponsive_command(
    tmp_path, command, expected
):
    perl = shutil.which("perl")
    if perl is None:
        pytest.skip("Perl fallback requires Perl")
    (tmp_path / "perl").symlink_to(perl)
    script = (ROOT / "run.sh").read_text()
    function = script[script.index("run_with_timeout() {") : script.index("\nmode=start")]
    result = subprocess.run(
        [
            "/bin/sh",
            "-c",
            function + '\nrun_with_timeout 1 "$@"',
            "watchdog-test",
            sys.executable,
            "-c",
            command,
        ],
        env={**os.environ, "PATH": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == expected, result.stderr
