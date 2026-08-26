import ast
from pathlib import Path


AI_ROOT = Path(__file__).resolve().parents[1] / "app" / "ai"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_ai_package_has_no_simulator_imports_or_scenario_dependencies():
    violations = []
    forbidden_names = {"SimWorld", "scenario", "scenario_name"}
    for path in AI_ROOT.rglob("*.py"):
        imports = _imports(path)
        forbidden_imports = sorted(
            module
            for module in imports
            if module == "simulator"
            or module.startswith("simulator.")
            or module == "app.services.simulator_clock"
        )
        source = path.read_text(encoding="utf-8")
        forbidden_symbols = sorted(name for name in forbidden_names if name in source)
        if forbidden_imports or forbidden_symbols:
            violations.append((str(path), forbidden_imports, forbidden_symbols))

    assert violations == []


def test_ai_adapters_import_operational_and_oem_service_boundaries():
    operational_imports = _imports(AI_ROOT / "tools" / "operational.py")
    oem_imports = _imports(AI_ROOT / "tools" / "oem.py")

    assert any(module.startswith("app.services.operational") for module in operational_imports)
    assert any(module.startswith("app.oem") for module in oem_imports)
    assert not any(module.startswith("simulator") for module in operational_imports | oem_imports)
