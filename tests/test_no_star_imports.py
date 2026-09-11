import ast
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "craigslist"


def star_imports(directory: Path) -> list[str]:
    found = []
    for path in sorted(directory.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
                found.append(f"{path.name}:{node.lineno} from {node.module} import *")
    return found


def test_new_code_has_no_star_imports():
    assert star_imports(PACKAGE_DIR) == []
