"""Build an ignored runnable snapshot without overwriting missing workspace files."""

import io
import shutil
import subprocess
import tarfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    target = root / "data" / "runtime.local"
    target.mkdir(parents=True, exist_ok=True)
    archive = subprocess.check_output(["git", "archive", "HEAD"], cwd=root)
    with tarfile.open(fileobj=io.BytesIO(archive)) as files:
        files.extractall(
            target,
            members=[
                member
                for member in files.getmembers()
                if member.name != "data" and not member.name.startswith("data/")
            ],
            filter="data",
        )
    # Existing edits and new source files take precedence over committed fallbacks.
    for dirname in ("backend", "frontend", "scripts"):
        for path in (root / dirname).rglob("*"):
            if not path.is_file() or any(
                part
                in {
                    "node_modules",
                    "dist",
                    "__pycache__",
                    ".cache",
                    ".pytest_cache",
                    ".ruff_cache",
                }
                for part in path.parts
            ):
                continue
            destination = target / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    for filename in ("compose.yaml", "run.sh", ".env", ".env.example"):
        path = root / filename
        if path.exists():
            shutil.copy2(path, target / filename)
    # Mount the real ignored data through the snapshot's compose-relative path.
    local_data = target / "data"
    if local_data.is_dir() and not local_data.is_symlink():
        shutil.rmtree(local_data)
    if not local_data.exists():
        local_data.symlink_to(root / "data", target_is_directory=True)
    print(f"Prepared local runtime: {target}")


if __name__ == "__main__":
    main()
