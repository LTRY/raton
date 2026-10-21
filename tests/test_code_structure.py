"""Structure rules that used to live in CLAUDE.md as prose."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "back"
FRONT = ROOT / "front"
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
    # Routes live in back/api/ and are plugged in with include_router (see back/api/__init__.py).
    tree = ast.parse((APP / "main.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                    assert not (target.value.id == "app" and target.attr in ROUTE_METHODS), (
                        f"back/main.py declares a route on `{node.name}`: move it to back/api/"
                    )


def imports_of(root: Path, prefix: str) -> list[str]:
    return sorted(
        f"{path.relative_to(ROOT)}: {module}"
        for path in root.rglob("*.py")
        for module in imported_modules(path)
        if module == prefix or module.startswith(prefix + ".")
    )


def test_front_never_imports_the_back():
    # The front reads and writes only through the back's /api (docs/spec/03-architecture.md), so
    # another front, or an MCP server, can be built the same way.
    assert not imports_of(FRONT, "back"), imports_of(FRONT, "back")


def test_back_never_imports_the_front():
    assert not imports_of(APP, "front"), imports_of(APP, "front")


def test_front_speaks_http_only_through_its_api_client_and_relay():
    talkers = {path.split(":")[0] for path in imports_of(FRONT, "httpx")}
    assert talkers <= {"front/api.py", "front/proxy.py"}, talkers


# Package -> packages it may import, inside back/services/. Every service module lives in one of these
# packages; `jobs` is the orchestration on top of all of them, so no other package imports it.
SERVICE_PACKAGE_DEPENDENCIES = {
    "common": set(),
    "youtube": {"common"},
    "llm": {"common"},
    "media": {"common"},
    "channels": {"common", "youtube"},
    "ingest": {"common", "media", "youtube"},
    "playlists": {"common", "ingest", "youtube"},
    "videos": {"common", "media", "youtube"},
    "raton": {"common", "videos"},
    "rag": {"common", "llm", "videos"},
    "library_chat": {"channels", "common", "rag", "videos", "youtube"},
    "jobs": {
        "channels",
        "common",
        "ingest",
        "library_chat",
        "llm",
        "media",
        "playlists",
        "rag",
        "videos",
        "youtube",
    },
}


def service_package(module: str) -> str | None:
    parts = module.split(".")
    if parts[:2] != ["back", "services"] or len(parts) < 3:
        return None
    return parts[2]


def test_models_import_no_service():
    # Services build on the models; a model importing a service would make that service load with
    # every table, and its constants belong next to the column they size.
    offenders = sorted(
        f"{path.relative_to(APP)}: {module}"
        for path in (APP / "models").rglob("*.py")
        for module in imported_modules(path)
        if module == "back.services" or module.startswith("back.services.")
    )
    assert not offenders, f"models import services: {offenders}"


def test_only_jobs_open_a_db_session():
    # A background job owns its session; every other service works in the session it is given,
    # so a request or a job commits one unit of work (docs/spec/10-services.md).
    offenders = sorted(
        str(path.relative_to(APP / "services"))
        for path in (APP / "services").rglob("*.py")
        if path.relative_to(APP / "services").parts[0] != "jobs"
        and "back.db.session.SessionLocal" in imported_modules(path)
    )
    assert not offenders, f"open the session in back/services/jobs/ instead: {offenders}"


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
            # `from back.services import x` names a package too.
            if target is None and module.startswith("back.services."):
                target = module.split(".")[2]
            if target and target != owner and target not in allowed:
                offenders.append(f"{relative}: {module}")
    assert not offenders, "forbidden service imports: " + ", ".join(sorted(set(offenders)))


# The API writes nothing to the DB itself: a route reads the request, calls a service and answers;
# the service owns the business rule and its commit (docs/spec/10-services.md).
DB_WRITE = re.compile(r"\bdb\.(add|add_all|commit|delete|flush|merge)\(|\.delete\(\)")


def test_api_leaves_db_writes_to_services():
    offenders = sorted(
        str(path.relative_to(APP))
        for path in (APP / "api").rglob("*.py")
        if DB_WRITE.search(path.read_text(encoding="utf-8"))
    )
    assert not offenders, (
        f"these modules write to the DB: move the write into a service: {offenders}"
    )


SERVICES_SPEC = ROOT / "docs" / "spec" / "10-services.md"


def spec_table_rows(section: str) -> list[list[str]]:
    """Cells of the markdown table rows under the `## section` / `### section` heading."""
    text = SERVICES_SPEC.read_text(encoding="utf-8")
    body = re.split(rf"^#{{2,3}} {re.escape(section)}$", text, flags=re.MULTILINE)[1]
    body = re.split(r"^#{2,3} ", body, flags=re.MULTILINE)[0]
    return [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in body.splitlines()
        if line.startswith("| `")
    ]


def test_services_spec_lists_the_package_dependencies():
    # The overview table of docs/spec/10-services.md is the readable copy of SERVICE_PACKAGE_DEPENDENCIES.
    documented = {}
    for package, _role, depends in spec_table_rows("Vue d'ensemble"):
        name = package.strip("`/")
        documented[name] = set(re.findall(r"`(\w+)`", depends))
    assert documented == SERVICE_PACKAGE_DEPENDENCIES


def test_services_spec_lists_every_service_module():
    documented = set()
    for package in SERVICE_PACKAGE_DEPENDENCIES:
        for row in spec_table_rows(f"`{package}/`"):
            documented.update(f"{package}/{module}" for module in re.findall(r"`(\w+)`", row[0]))
    actual = {
        f"{path.parent.name}/{path.stem}"
        for path in (APP / "services").rglob("*.py")
        if path.name != "__init__.py"
    }
    assert documented == actual, (
        f"docs/spec/10-services.md: missing {sorted(actual - documented)}, "
        f"stale {sorted(documented - actual)}"
    )
