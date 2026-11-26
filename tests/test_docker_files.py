"""The container files agree with each other and keep secrets and the internal port out of reach. (They do not build the image.)"""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKER = ROOT / "deploy/docker"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_image_copies_only_named_folders_that_exist():
    sources = [m for m in re.findall(r"^COPY\s+(\S+)\s+\S+", text(DOCKER / "Dockerfile"), re.M)]
    assert sources and "." not in sources and "./" not in sources
    for source in sources:
        assert (ROOT / source).exists(), source


def test_the_build_context_leaves_everything_out_except_those_folders():
    rules = [line.strip() for line in text(ROOT / ".dockerignore").splitlines() if line.strip() and not line.startswith("#")]
    assert rules[0] == "*"
    allowed = {r[1:] for r in rules if r.startswith("!")}
    assert allowed == {"worker", "web", "question_bank", "eval", "deploy/docker"}
    assert rules.index("**/.env") > max(i for i, r in enumerate(rules) if r.startswith("!"))     # after the folders it re-opens


def test_the_ports_are_published_on_the_server_only():
    ports = re.findall(r'^\s+- "([\d.:]+)"', text(DOCKER / "compose.yaml"), re.M)
    assert ports == ["127.0.0.1:8080:8080", "127.0.0.1:8081:8081"]
    assert "restart: unless-stopped" in text(DOCKER / "compose.yaml")


def test_the_example_settings_name_everything_the_start_needs_and_hold_no_key():
    spec = importlib.util.spec_from_file_location("supervisor_for_env", DOCKER / "supervisor.py")
    sup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sup)
    values = dict(line.split("=", 1) for line in text(DOCKER / ".env.example").splitlines() if line and not line.startswith("#"))
    for entry in sup.missing_settings({}):
        name = entry.split()[0]
        assert values[name] == ""
    assert values["MAX_SESSIONS"] == "10" and values["RETENTION_DAYS"] == "30"
    assert "MAX_SESSIONS=10" in text(DOCKER / "Dockerfile")


def test_container_files_keep_linux_line_endings():
    assert "deploy/docker/** text eol=lf" in text(ROOT / ".gitattributes")
