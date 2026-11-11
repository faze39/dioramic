"""Runs Blender headless on a validated spec, inside a plugin-owned folder."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

BUILD_SCRIPT = Path(__file__).with_name("blender_build.py")
SCENE_ID = re.compile(r"^[a-z0-9-]{1,48}$")
# Only these variables reach Blender. API keys and tokens in the agent's
# environment are never passed to the subprocess.
ENV_KEEP = ("PATH", "LANG", "LC_ALL", "TMPDIR", "DISPLAY", "XDG_RUNTIME_DIR")


class RenderError(RuntimeError):
    pass


def find_blender(configured: str = "") -> str | None:
    for cand in (configured, os.environ.get("BLENDER_BIN", ""), shutil.which("blender") or ""):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:28] or "scene"
    return f"{s}-{time.strftime('%m%d-%H%M%S')}"


def scene_dir(root: Path, scene_id: str) -> Path:
    """Resolve a scene id to its folder; ids are plugin generated, never paths."""
    if not SCENE_ID.match(scene_id or ""):
        raise RenderError(f"unknown scene id '{scene_id}'")
    d = (root / scene_id).resolve()
    if d.parent != root.resolve() or not (d / "spec.json").is_file():
        raise RenderError(f"unknown scene id '{scene_id}'")
    return d


def run(blender: str, spec: dict, root: Path, scene_id: str, *, still_only: bool, timeout: int) -> dict:
    out = root / scene_id
    out.mkdir(parents=True, exist_ok=False)
    (out / "spec.json").write_text(json.dumps(spec, indent=1))
    env = {k: os.environ[k] for k in ENV_KEEP if k in os.environ}
    env["HOME"] = str(out)
    cmd = [blender, "-b", "--factory-startup", "-noaudio", "--python-exit-code", "1",
           "-P", str(BUILD_SCRIPT), "--", str(out / "spec.json"), str(out)]
    if still_only:
        cmd.append("still")
    started = time.time()
    proc = subprocess.Popen(cmd, cwd=out, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, start_new_session=True)
    try:
        log, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        log, _ = proc.communicate()
        (out / "render.log").write_text(log or "")
        raise RenderError(f"render stopped after the {timeout}s limit; shorten duration or lower samples")
    (out / "render.log").write_text(log or "")
    seconds = round(time.time() - started, 1)
    clip, still = out / "clip.mp4", out / "preview.png"
    if proc.returncode != 0 or "DIORAMIC_DONE" not in log or not still.is_file():
        tail = "\n".join((log or "").splitlines()[-8:])
        raise RenderError(f"blender failed (exit {proc.returncode}):\n{tail}")
    if not still_only and (not clip.is_file() or clip.stat().st_size < 1000):
        raise RenderError("blender finished but wrote no clip")
    return {"scene_id": scene_id, "preview": str(still), "clip": None if still_only else str(clip),
            "render_seconds": seconds}
