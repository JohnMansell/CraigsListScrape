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


def test_listings_command_prints_each_listing_and_the_count_and_total(tmp_path, monkeypatch, capsys):
    from craigslist.__main__ import main

    monkeypatch.setenv("CRAIGSLIST_LOGDIR", str(tmp_path))
    dealer_full = (REPO_ROOT / "tests" / "fixtures" / "dealer_full.json").read_text()
    urls: list[str] = []

    def fetch(url: str) -> str:
        urls.append(url)
        return dealer_full

    main(["listings", "--city", "orange county", "--make", "honda", "--model", "civic", "--owner-type", "dealer"], fetch)

    lines = capsys.readouterr().out.splitlines()
    assert len(urls) == 1 and "purveyor=dealer" in urls[0]
    assert len(lines) == 20
    assert "2017 Honda Civic EX Sedan 4D" in lines[0]
    assert lines[-1] == "dealer: 19 Listings, API reported total 15"
