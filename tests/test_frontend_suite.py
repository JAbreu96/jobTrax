"""Runs frontend/'s typecheck and Vitest suite as part of `pytest`.

There is no CI in this repo, so until this existed nothing ran `npm test` or
`tsc` except by hand. That was survivable while frontend/ was a scaffold with
no UI in it; it stops being survivable now that the field layer -- the
components /app actually renders -- lives there. A Python-only suite going
green while the React build is broken is precisely the blind spot
test_job_fields_js.py was written to close for job_fields.js.

Skipped, never failed, when the toolchain isn't there: node_modules is
gitignored and absent on a fresh clone, and a contributor touching only the
Python half should not be made to install npm packages to run the suite. The
skip reason names the fix.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
FRONTEND = REPO / "frontend"
# Vite 7 needs >= 20.19; scripts/build-frontend.sh enforces the same floor.
MIN_NODE = (20, 19)


def _version(node: str):
    out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30)
    m = re.match(r"v(\d+)\.(\d+)", out.stdout.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _node_bin():
    """A node binary meeting the floor, or None.

    Checks PATH first, then nvm's install dir. The fallback is not
    over-engineering: several of this repo's launchd wrappers pin PATH to node
    v18, so `node` on a developer's PATH here is frequently too old while a
    conforming version sits installed a directory away. Without it these tests
    would skip on the very machine they are meant to protect.
    """
    on_path = shutil.which("node")
    if on_path and (v := _version(on_path)) and v >= MIN_NODE:
        return on_path

    versions = Path(os.environ.get("NVM_DIR", Path.home() / ".nvm")) / "versions" / "node"
    if not versions.is_dir():
        return None
    candidates = []
    for d in versions.iterdir():
        node = d / "bin" / "node"
        if node.is_file() and (v := _version(str(node))) and v >= MIN_NODE:
            candidates.append((v, str(node)))
    return max(candidates)[1] if candidates else None


NODE = _node_bin()

pytestmark = [
    pytest.mark.skipif(NODE is None, reason="no node >= 20.19 found (see .nvmrc)"),
    pytest.mark.skipif(
        not (FRONTEND / "node_modules").is_dir(),
        reason="frontend deps not installed -- run ./scripts/build-frontend.sh",
    ),
]


def _npm(*args):
    """Run an npm script with the chosen node first on PATH.

    npm dispatches to whatever `node` it finds, so passing the binary is not
    enough -- the directory has to lead PATH or a too-old node still wins.
    """
    env = {**os.environ, "PATH": f"{Path(NODE).parent}{os.pathsep}{os.environ['PATH']}"}
    npm = shutil.which("npm", path=env["PATH"])
    if npm is None:
        pytest.skip("npm not found next to the selected node")
    return subprocess.run(
        [npm, "run", *args],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )


def test_typecheck_is_clean():
    proc = _npm("typecheck")
    assert proc.returncode == 0, f"tsc --noEmit failed:\n{proc.stdout}\n{proc.stderr}"


def test_vitest_suite_passes():
    proc = _npm("test")
    assert proc.returncode == 0, f"vitest failed:\n{proc.stdout}\n{proc.stderr}"
