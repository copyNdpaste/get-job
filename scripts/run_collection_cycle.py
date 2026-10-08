"""Run one scheduled collection with an OS lock and save public timing statistics."""

import fcntl
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    runtime = root / "data" / "runtime.local"
    output = root / "data" / "collection-timing.local"
    output.mkdir(parents=True, exist_ok=True)
    docker = shutil.which("docker") or str(Path.home() / ".orbstack/bin/docker")
    with (output / "cycle.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Collection already running; this slot was skipped.", flush=True)
            return 0
        started = datetime.now(ZoneInfo("Asia/Seoul"))
        print(f"Collection requested at {started.isoformat()}", flush=True)
        environment = {**os.environ, "PATH": (
            f"{Path.home()}/.orbstack/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
        )}
        # The persistent scheduler is disabled locally to prevent duplicate triggers.
        command = [docker, "compose", "exec", "-T", "backend", "python", "-c", (
            "import asyncio; from app.config import get_settings; "
            "from app.scheduler import run_daily_cycle; "
            "asyncio.run(run_daily_cycle(get_settings().model_copy(update={"
            "'daily_scheduler_api_url':'http://127.0.0.1:8000'})))"
        )]
        try:
            result = subprocess.run(command, cwd=runtime, env=environment, timeout=13 * 3600)
            returncode = result.returncode
        except subprocess.TimeoutExpired:
            returncode = 124
            print("Collection exceeded the cycle timeout.", flush=True)
        # Preserve observations even when later recommendation/enrichment steps fail.
        try:
            with urlopen("http://127.0.0.1:8000/api/crawl/timing?days=30", timeout=60) as response:
                report = json.load(response)
            report["trigger_started_at"] = started.isoformat()
            report["trigger_finished_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
            report["cycle_exit_code"] = returncode
            filename = started.strftime("%Y-%m-%d_%H%M%S") + ".json"
            encoded = json.dumps(report, ensure_ascii=False, indent=2)
            (output / filename).write_text(encoded, encoding="utf-8")
            temporary = output / "latest.tmp"
            temporary.write_text(encoded, encoding="utf-8")
            temporary.replace(output / "latest.json")
            print(f"Timing report saved; cycle exit code {returncode}.", flush=True)
        except Exception as exc:
            print(f"Timing report unavailable ({type(exc).__name__}).", flush=True)
            returncode = returncode or 1
        return returncode


if __name__ == "__main__":
    raise SystemExit(main())
