"""Static integrity checks for the consolidated ClaimGuard project package."""
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"


def test_expected_pipeline_modules_are_present():
    required = [
        BACKEND_ROOT / "main.py",
        BACKEND_ROOT / "config.py",
        BACKEND_ROOT / "data" / "database.py",
        BACKEND_ROOT / "invoice" / "extractor.py",
        BACKEND_ROOT / "invoice" / "extraction" / "quality.py",
        BACKEND_ROOT / "invoice" / "extraction" / "provenance.py",
        BACKEND_ROOT / "invoice" / "market_research.py",
        BACKEND_ROOT / "invoice" / "price_comparison.py",
        BACKEND_ROOT / "invoice" / "risk_engine.py",
        BACKEND_ROOT / "invoice" / "report_service.py",
        BACKEND_ROOT / "invoice" / "routes.py",
    ]
    missing = [str(path.relative_to(PROJECT_ROOT)) for path in required if not path.is_file()]
    assert not missing, f"Missing integrated source files: {missing}"


def test_archived_patch_tree_is_not_in_active_project():
    assert not (BACKEND_ROOT / "cg_patch").exists(), (
        "Remove the obsolete backend/cg_patch archive after backing it up; "
        "its tests conflict with the active test suite."
    )


def test_active_python_sources_do_not_import_archived_patch_code():
    matches = []
    import_pattern = re.compile(
        r"(?m)^\s*(?:from\s+(?:backend\.)?cg_patch\b|import\s+(?:backend\.)?cg_patch\b)"
    )
    for path in BACKEND_ROOT.rglob("*.py"):
        if "cg_patch" in path.parts:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if import_pattern.search(source):
            matches.append(str(path.relative_to(PROJECT_ROOT)))
    assert not matches, f"Active Python sources import archived patch code: {matches}"


def test_environment_template_exists():
    # Existing deployments may have a real .env; this test must not require or remove it.
    assert (BACKEND_ROOT / ".env.example").is_file()


def test_searxng_sample_port_matches_compose_default():
    backend_example = (BACKEND_ROOT / ".env.example").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "searxng" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "SEARXNG_URL=http://127.0.0.1:8080" in backend_example
    assert "${SEARXNG_PORT:-8080}:${SEARXNG_PORT:-8080}" in compose
