"""L9R — the runtime self-modification fence (12 Jun: a builder edited the mutation gate it
was being examined by; technically sound, institutionally forbidden)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from infra.worktree import selfmod_fence

ROOT = Path(__file__).resolve().parents[1]


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "orch"
    (root / "validation").mkdir(parents=True)
    (root / "validation" / "gate.py").write_text("REAL = True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "baseline"], capture_output=True)
    return root


def test_fence_quarantines_reverts_and_reports(tmp_path):
    root = _repo(tmp_path)
    q = tmp_path / "quarantine"
    (root / "validation" / "gate.py").write_text("REAL = False  # tampered\n", encoding="utf-8")
    (root / "validation" / "planted.py").write_text("BACKDOOR = 1\n", encoding="utf-8")
    desc = selfmod_fence(root, quarantine=q)
    assert "gate.py" in desc and "planted.py" in desc
    assert (root / "validation" / "gate.py").read_text(encoding="utf-8") == "REAL = True\n", \
        "the examiner is restored"
    assert not (root / "validation" / "planted.py").exists(), "planted files are removed"
    patches = list(q.glob("selfmod_*.patch"))
    planted = list(q.glob("selfmod_*planted.py"))
    assert patches and "tampered" in patches[0].read_text(encoding="utf-8")
    assert planted and "BACKDOOR" in planted[0].read_text(encoding="utf-8"), \
        "nothing is destroyed — evidence is preserved"
    assert selfmod_fence(root, quarantine=q) == "", "clean tree -> fence silent"


def test_fence_ignores_runtime_dirs(tmp_path):
    root = _repo(tmp_path)
    (root / "state").mkdir()
    (root / "state" / "scratch.json").write_text("{}", encoding="utf-8")
    assert selfmod_fence(root, quarantine=tmp_path / "q") == ""


def test_pool_wires_the_fence():
    src = (ROOT / "control" / "pool.py").read_text(encoding="utf-8")
    assert "selfmod_fence()" in src and "L9R" in src, "every settle passes the fence"
