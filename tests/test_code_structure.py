"""Structure rules that used to live in CLAUDE.md as prose."""

import ast
import re
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


# Package -> packages it may import, inside app/services/. Every service module lives in one of these
# packages; `jobs` is the orchestration on top of all of them, so no other package imports it.
SERVICE_PACKAGE_DEPENDENCIES = {
    "common": set(),
    "youtube": {"common"},
    "llm": {"common"},
    "media": {"common"},
    "channels": {"common", "youtube"},
    "ingest": {"common", "media", "youtube"},
    "playlists": {"common", "ingest", "youtube"},
    "videos": {"common", "media"},
    "rag": {"channels", "common", "llm", "videos", "youtube"},
    "jobs": {"channels", "common", "ingest", "llm", "media", "rag", "videos", "youtube"},
}


def service_package(module: str) -> str | None:
    parts = module.split(".")
    if parts[:2] != ["app", "services"] or len(parts) < 3:
        return None
    return parts[2]


def test_services_import_no_web_module():
    # The web layer calls the services, never the reverse: a service is also called by /api and jobs.
    offenders = sorted(
        f"{path.relative_to(APP)}: {module}"
        for path in (APP / "services").rglob("*.py")
        for module in imported_modules(path)
        if module == "app.web" or module.startswith("app.web.")
    )
    assert not offenders, f"services import the web layer: {offenders}"


def test_every_service_module_belongs_to_a_known_package():
    loose = sorted(
        str(path.relative_to(APP / "services"))
        for path in (APP / "services").rglob("*.py")
        if path.name != "__init__.py"
        and path.relative_to(APP / "services").parts[0] not in SERVICE_PACKAGE_DEPENDENCIES
    )
    assert not loose, f"put these modules in a package of SERVICE_PACKAGE_DEPENDENCIES: {loose}"


def test_service_packages_form_a_dag():
    offenders = []
    for path in sorted((APP / "services").rglob("*.py")):
        relative = path.relative_to(APP / "services")
        if len(relative.parts) < 2:
            continue
        owner = relative.parts[0]
        allowed = SERVICE_PACKAGE_DEPENDENCIES.get(owner, set())
        for module in imported_modules(path):
            target = service_package(module)
            # `from app.services import x` names a package too.
            if target is None and module.startswith("app.services."):
                target = module.split(".")[2]
            if target and target != owner and target not in allowed:
                offenders.append(f"{relative}: {module}")
    assert not offenders, "forbidden service imports: " + ", ".join(sorted(set(offenders)))


# Writes still done by the web layer itself, waiting to move into a service. The counts may only go
# down: a route reads the request, calls a service and renders; the service owns the business rule
# and its commit (docs/spec/03-architecture.md). Lower a count when you move a write out.
WEB_DB_WRITES_LEFT = {
    "web/raton.py": 2,  # visit tracking of the home hero
    "web/routes/library_chat.py": 5,  # applying a library chat answer, clearing the chat
    "web/routes/media.py": 1,  # deleting one media file
    "web/routes/transcript.py": 2,  # applying an LLM job result
}
DB_WRITE = re.compile(r"\bdb\.(add|add_all|commit|delete|flush|merge)\(|\.delete\(\)")


def test_web_layer_leaves_db_writes_to_services():
    counts = {}
    for path in sorted([*(APP / "web").rglob("*.py"), *(APP / "api").rglob("*.py")]):
        found = len(DB_WRITE.findall(path.read_text(encoding="utf-8")))
        if found:
            counts[str(path.relative_to(APP))] = found
    assert counts == WEB_DB_WRITES_LEFT, (
        "a route writes to the DB itself: move the write into app/services/ "
        "(or lower WEB_DB_WRITES_LEFT after moving one out)"
    )
