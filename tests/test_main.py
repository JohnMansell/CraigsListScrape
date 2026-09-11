import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_entry_point(*args: str, log_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "craigslist", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "CRAIGSLIST_LOGDIR": str(log_dir)},
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_entry_point_at_debug_level_exits_cleanly_and_writes_debug_lines(tmp_path):
    result = run_entry_point("--log", "DEBUG", log_dir=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "DEBUG" in (tmp_path / "craigslist.log").read_text()
