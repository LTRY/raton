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


# Package -> packages it may import, inside app/services/. A package missing from a value
# must not be imported by the key; the orchestration modules at the root sit on top of all of them.
SERVICE_PACKAGE_DEPENDENCIES = {
    "youtube": set(),
    "llm": set(),
    "media": {"youtube"},
    "channels": {"media", "youtube"},
    "playlists": {"channels", "youtube"},
    "videos": {"media"},
    "rag": {"channels", "llm", "videos", "youtube"},
}
SERVICE_ORCHESTRATION_MODULES = {"background_jobs", "scheduler"}


def service_package(module: str) -> str | None:
    parts = module.split(".")
    if parts[:2] != ["app", "services"] or len(parts) < 3:
        return None
    return parts[2] if parts[2] in SERVICE_PACKAGE_DEPENDENCIES else None


def test_services_import_no_web_module():
    # The web layer calls the services, never the reverse: a service is also called by /api and jobs.
    offenders = sorted(
        f"{path.relative_to(APP)}: {module}"
        for path in (APP / "services").rglob("*.py")
        for module in imported_modules(path)
        if module == "app.web" or module.startswith("app.web.")
    )
    assert not offenders, f"services import the web layer: {offenders}"


def test_service_packages_form_a_dag():
    # Orchestration modules (jobs, scheduler) call the packages; nothing calls them back.
    offenders = []
    for path in sorted((APP / "services").rglob("*.py")):
        relative = path.relative_to(APP / "services")
        owner = relative.parts[0] if len(relative.parts) > 1 else relative.stem
        if owner in SERVICE_ORCHESTRATION_MODULES:
            continue
        for module in imported_modules(path):
            if module in {f"app.services.{name}" for name in SERVICE_ORCHESTRATION_MODULES} or any(
                module.startswith(f"app.services.{name}.") for name in SERVICE_ORCHESTRATION_MODULES
            ):
                offenders.append(f"{relative}: {module}")
            target = service_package(module)
            if (
                target
                and target != owner
                and target not in SERVICE_PACKAGE_DEPENDENCIES.get(owner, set())
            ):
                offenders.append(f"{relative}: {module}")
    assert not offenders, "forbidden service imports: " + ", ".join(sorted(set(offenders)))


# Writes still done by the web layer itself, waiting to move into a service. The counts may only go
# down: a route reads the request, calls a service and renders; the service owns the business rule
# and its commit (docs/spec/03-architecture.md). Lower a count when you move a write out.
WEB_DB_WRITES_LEFT = {
    "api/routes.py": 1,  # PUT /api/settings, twin of POST /settings
    "web/raton.py": 2,  # visit tracking of the home hero
    "web/routes/library_chat.py": 5,  # applying a library chat answer, clearing the chat
    "web/routes/media.py": 1,  # deleting one media file
    "web/routes/settings.py": 1,  # saving the settings form
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
