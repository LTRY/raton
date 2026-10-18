"""Structure rules that used to live in CLAUDE.md as prose."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "api_route"}


def imported_modules(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_main_declares_no_route():
    # Routes live in app/web/routes/ and are plugged in with include_router (see the docstring of app/main.py).
    tree = ast.parse((APP / "main.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                    assert not (target.value.id == "app" and target.attr in ROUTE_METHODS), (
                        f"app/main.py declares a route on `{node.name}`: move it to app/web/routes/"
                    )


def test_web_shared_imports_no_other_web_module():
    # Every web module imports shared.py, so it must not import one back (circular import).
    offenders = sorted(
        module
        for module in imported_modules(APP / "web" / "shared.py")
        if module.startswith("app.web.") and module != "app.web.shared"
    )
    assert not offenders, f"app/web/shared.py imports {offenders}"
