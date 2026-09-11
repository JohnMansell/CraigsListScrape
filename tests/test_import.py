import os
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "craigslist"


def package_modules(package_dir: Path) -> list[str]:
    modules = []
    for path in package_dir.rglob("*.py"):
        parts = path.relative_to(package_dir.parent).with_suffix("").parts
        modules.append(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    return sorted(modules)


def test_importing_every_module_ignores_argv_and_creates_nothing(tmp_path):
    # A copy in an empty directory, so the default logs/ next to the package is observable too.
    shutil.copytree(PACKAGE_DIR, tmp_path / "craigslist", ignore=shutil.ignore_patterns("__pycache__"))
    modules = package_modules(tmp_path / "craigslist")
    assert modules, "craigslist package has no modules"
    before = sorted(tmp_path.rglob("*"))
    code = (
        "import importlib, os, sys\n"
        "for name in os.environ['MODULES'].split(','):\n"
        "    importlib.import_module(name)\n"
        "print(sys.modules['craigslist'].__file__)"
    )

    result = subprocess.run(
        [sys.executable, "-B", "-c", code, "--unrelated-flag", "value"],
        cwd=tmp_path,
        env={**os.environ, "CRAIGSLIST_LOGDIR": str(tmp_path / "logdir-from-env"), "MODULES": ",".join(modules)},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(str(tmp_path)), "imported the repo package instead of the copy"
    assert sorted(tmp_path.rglob("*")) == before
