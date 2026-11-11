"""End-to-end: the real Hermes agent loop renders a clip, then tweaks it.

Runs only with DIORAMIC_E2E=1, hermes on PATH and Blender available. Uses a
throwaway HERMES_HOME and demo/scripted_model.py, so it needs no API key.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERMES = os.environ.get("HERMES_BIN") or shutil.which("hermes")
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender")
pytestmark = pytest.mark.skipif(not (HERMES and BLENDER and os.environ.get("DIORAMIC_E2E") == "1"),
                                reason="set DIORAMIC_E2E=1 with hermes and blender available")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _hermes(home, *args, timeout=1500):
    env = {**os.environ, "HERMES_HOME": str(home)}
    return subprocess.run([HERMES, *args], env=env, capture_output=True, text=True, timeout=timeout,
                          cwd=home.parent)


def test_render_then_tweak(tmp_path):
    home = tmp_path / "home"
    (home / "plugins").mkdir(parents=True)
    shutil.copytree(ROOT, home / "plugins" / "dioramic",
                    ignore=shutil.ignore_patterns(".git", "tests", "demo", "__pycache__"))
    assert _hermes(home, "plugins", "enable", "dioramic").returncode == 0
    port = _free_port()
    for key, value in (("model.provider", "custom"), ("model.base_url", f"http://127.0.0.1:{port}/v1"),
                       ("model.default", "scripted"), ("model.api_key", "local-demo"),
                       ("tools.tool_search.enabled", "off"),
                       ("plugins.entries.dioramic.settings.blender_path", BLENDER)):
        _hermes(home, "config", "set", key, value)
    model = subprocess.Popen([sys.executable, str(ROOT / "demo" / "scripted_model.py"), str(port),
                              str(ROOT / "examples" / "toy-desk.json"), str(ROOT / "examples" / "toy-desk-tweak.json")])
    try:
        time.sleep(1)
        out = _hermes(home, "chat", "-q", "make a toy desk scene, then make the cube blue", "--oneshot")
        assert out.returncode == 0, out.stderr
    finally:
        model.terminate()
        _hermes(home, "gateway", "stop")
    scenes = sorted((home / "plugin-data" / "dioramic" / "scenes").iterdir())
    assert len(scenes) == 2 and scenes[1].name.endswith("-v2")
    for d in scenes:
        assert (d / "clip.mp4").stat().st_size > 20_000 and (d / "preview.png").is_file()
    assert "rendered in blender" in out.stdout
