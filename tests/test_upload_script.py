"""deploy/vast/upload.sh sends the project to a rented machine owned by a third party. The repo root now IS the project root and can hold a
private SSH key, so the script must send only what is meant to go: git-known files minus a deny list, never "the current folder"."""
import pathlib
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "deploy" / "vast" / "upload.sh"


def find_bash():
    bash = shutil.which("bash")
    if not bash:
        return None
    probe = subprocess.run([bash, "-c", "command -v git && command -v tar && command -v grep"], capture_output=True, text=True)
    return bash if probe.returncode == 0 else None       # e.g. the Windows WSL launcher has no git inside


BASH = find_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash with git, tar and grep")

# what must be sent
MEANT = {"worker/a.py", "deploy/vast/upload.sh", ".env.example", "docs/new.md", "tests/test_x.py"}
# what must never be sent, with the reason
NEVER = ["ssh", "ssh.pub", "id_ed25519", "deploy/vast/.env", "prod.env", "cert.pem", "api.key", "experiments/x/a.py", ".venv/lib/x.py",
         ".venv-lab/y.py", ".model-cache/z.bin", "runs/r.json", "models/cache/m.onnx", "eval/data/d.wav", "pkg/__pycache__/a.pyc", ".pytest_cache/c"]


def make_repo(tmp_path, commit_secrets=False):
    def put(rel, text="x"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    tmp_path.mkdir(parents=True, exist_ok=True)
    git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    (tmp_path / "deploy" / "vast").mkdir(parents=True, exist_ok=True)
    shutil.copy(SCRIPT, tmp_path / "deploy" / "vast" / "upload.sh")
    for rel in ("worker/a.py", ".env.example", "tests/test_x.py"):
        put(rel)
    for rel in NEVER:
        put(rel, "SECRET")
    git("add", "worker", ".env.example", "tests", "deploy")
    if commit_secrets:                                   # a key committed by mistake: the deny list must still hold
        git("add", "-f", *NEVER)
    git("commit", "-q", "-m", "x")
    put("docs/new.md")                                   # a new file nobody added to git yet: it is meant to go
    return tmp_path


def listed(repo, cwd=None):
    out = subprocess.run([BASH, str(repo / "deploy" / "vast" / "upload.sh"), "--list"], cwd=cwd or repo, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return {line for line in out.stdout.splitlines() if line}


def test_only_the_meant_files_are_listed(tmp_path):
    assert listed(make_repo(tmp_path)) == MEANT


def test_a_committed_secret_is_still_not_sent(tmp_path):
    assert listed(make_repo(tmp_path, commit_secrets=True)) == MEANT


def test_it_does_not_depend_on_where_it_is_run_from(tmp_path):
    repo = make_repo(tmp_path / "repo")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert listed(repo, cwd=elsewhere) == MEANT


def test_a_gitignored_key_is_hidden_by_the_first_layer_too(tmp_path):
    repo = make_repo(tmp_path)
    (repo / ".gitignore").write_text("/ssh\n/ssh.pub\n", encoding="utf-8")
    assert listed(repo) == MEANT | {".gitignore"}
