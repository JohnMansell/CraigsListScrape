import os
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_entry_point_without_a_command_serves_the_search_page_and_logs_at_debug_level(tmp_path, monkeypatch):
    from craigslist import page
    from craigslist.__main__ import main

    monkeypatch.setenv("CRAIGSLIST_LOGDIR", str(tmp_path))
    served: list[int] = []
    monkeypatch.setattr(page, "serve", lambda port=page.PORT: served.append(port))

    main(["--log", "DEBUG"])

    assert served == [8080]
    assert "DEBUG" in (tmp_path / "craigslist.log").read_text()


def test_entry_point_runs_as_a_module(tmp_path):
    result = run_entry_point("--help", log_dir=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "listings" in result.stdout


def test_listings_command_prints_each_listing_count_and_curve_coefficients(tmp_path, monkeypatch, capsys):
    from craigslist.__main__ import main

    monkeypatch.setenv("CRAIGSLIST_LOGDIR", str(tmp_path))
    dealer_full = (REPO_ROOT / "tests" / "fixtures" / "dealer_full.json").read_text()
    urls: list[str] = []

    def fetch(url: str) -> str:
        urls.append(url)
        return dealer_full

    main(
        ["listings", "--state", "CA", "--city", "orange county", "--make", "honda", "--model", "civic", "--owner-type", "dealer"],
        fetch,
    )

    lines = capsys.readouterr().out.splitlines()
    assert len(urls) == 1 and "purveyor=dealer" in urls[0]
    assert len(lines) == 20
    assert "2017 Honda Civic EX Sedan 4D" in lines[0]
    assert lines[-1].startswith("dealer: 19 Listings, API reported total 15; curve coefficients a=")
    assert " b=" in lines[-1]
    assert " c=" in lines[-1]


def test_carfax_command_prints_each_listing_and_the_total(tmp_path, monkeypatch, capsys):
    from craigslist.__main__ import main

    monkeypatch.setenv("CRAIGSLIST_LOGDIR", str(tmp_path))
    page = (REPO_ROOT / "tests" / "fixtures" / "carfax_last_page.json").read_text()

    def fetch(url: str) -> str:
        return page

    main(["carfax", "--state", "CA", "--city", "sf bay area", "--make", "honda", "--model", "fit"], fetch)

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 8  # 7 Listings plus the total line
    assert lines[-1].startswith("carfax: 7 Listings, API reported total")


def test_carfax_command_reports_an_invalid_lookup_value(tmp_path, monkeypatch, capsys):
    from craigslist.__main__ import main

    monkeypatch.setenv("CRAIGSLIST_LOGDIR", str(tmp_path))

    with pytest.raises(SystemExit) as error:
        main(["carfax", "--state", "XX", "--city", "Orange County", "--make", "honda", "--model", "civic"], lambda url: "")

    assert error.value.code == 2
    assert "unknown state 'XX'" in capsys.readouterr().err


def test_listings_command_reports_an_invalid_lookup_value(tmp_path, monkeypatch, capsys):
    from craigslist.__main__ import main

    monkeypatch.setenv("CRAIGSLIST_LOGDIR", str(tmp_path))

    with pytest.raises(SystemExit) as error:
        main(["listings", "--state", "XX", "--city", "Orange County", "--make", "honda", "--model", "civic"], lambda url: "")

    assert error.value.code == 2
    assert "unknown state 'XX'" in capsys.readouterr().err
