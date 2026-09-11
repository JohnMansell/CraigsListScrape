import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "craigslist"


def package_modules() -> list[str]:
    return sorted(
        "craigslist" if path.stem == "__init__" else f"craigslist.{path.stem}"
        for path in PACKAGE_DIR.glob("*.py")
    )


def test_importing_every_module_ignores_argv_and_creates_nothing(tmp_path):
    modules = package_modules()
    assert modules, "craigslist package has no modules"
    log_dir = tmp_path / "logs-that-must-not-exist"
    code = "import importlib, os\nfor name in os.environ['MODULES'].split(','):\n    importlib.import_module(name)"

    result = subprocess.run(
        [sys.executable, "-c", code, "--unrelated-flag", "value"],
        cwd=REPO_ROOT,
        env={**os.environ, "CRAIGSLIST_LOGDIR": str(log_dir), "MODULES": ",".join(modules)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not log_dir.exists()
