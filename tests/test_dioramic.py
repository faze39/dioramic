import json
import os
from pathlib import Path

import pytest

from dioramic import Director, _safe, render, spec

EX = Path(__file__).resolve().parents[1] / "examples"
BLENDER = render.find_blender()


def test_examples_validate():
    for p in EX.glob("*.json"):
        if "tweak" in p.name:
            continue
        clean, warnings = spec.normalise(json.loads(p.read_text()))
        assert clean["objects"] and warnings == []


def test_limits_clamp_and_warn():
    clean, warnings = spec.normalise({"duration": 600, "samples": 999, "resolution": "4096x4096",
                                      "objects": [{"id": "a", "shape": "cube", "position": [1e9, 0, 0]}]})
    assert clean["duration"] == 8 and clean["samples"] == 16 and clean["resolution"] == "540x960"
    assert clean["objects"][0]["position"][0] == 12
    assert len(warnings) == 4


def test_hd_needs_opt_in():
    assert spec.normalise({"resolution": "1080x1920", "objects": [{"id": "a", "shape": "cube"}]})[0]["resolution"] == "540x960"
    assert spec.normalise({"resolution": "1080x1920", "objects": [{"id": "a", "shape": "cube"}]},
                          allow_hd=True)[0]["resolution"] == "1080x1920"


def test_problems_are_listed_not_guessed():
    with pytest.raises(spec.SpecError) as e:
        spec.normalise({"objects": [{"id": "A B", "shape": "teapot", "color": "ultraviolet"},
                                    {"id": "t", "shape": "text"}], "lighting": "disco"})
    joined = " ".join(e.value.problems)
    for word in ("teapot", "ultraviolet", "disco", "needs text", "A B"):
        assert word.lower() in joined.lower()


def test_text_is_data_only():
    clean, _ = spec.normalise({"objects": [{"id": "t", "shape": "text",
                                            "text": "__import__('os').system('x')\n\x00"}]})
    assert len(clean["objects"][0]["text"]) <= 24 and "\n" not in clean["objects"][0]["text"]


def test_merge_by_id_and_remove():
    base = {"objects": [{"id": "a", "shape": "cube", "color": "red"}, {"id": "b", "shape": "sphere"}],
            "camera": {"move": "orbit", "speed": 1}}
    out = spec.merge(base, {"objects": [{"id": "a", "color": "blue"}, {"id": "c", "shape": "cone"}],
                            "remove_objects": ["b"], "camera": {"speed": 0.5}})
    assert [o["id"] for o in out["objects"]] == ["a", "c"]
    assert out["objects"][0] == {"id": "a", "shape": "cube", "color": "blue"}
    assert out["camera"] == {"move": "orbit", "speed": 0.5}
    assert base["objects"][0]["color"] == "red"


def test_scene_ids_cannot_escape(tmp_path):
    for bad in ("../../etc", "/etc/passwd", "a/b", "", "UPPER", "x" * 80):
        with pytest.raises(render.RenderError):
            render.scene_dir(tmp_path, bad)


def test_subprocess_env_drops_secrets(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret")

    class P:
        returncode, pid = 0, 0

        def __init__(self, cmd, env, cwd, **kw):
            seen.update(env=env, cmd=cmd)
            Path(cwd, "preview.png").write_bytes(b"png")

        def communicate(self, timeout=None):
            return "DIORAMIC_DONE 1", None

    monkeypatch.setattr(render.subprocess, "Popen", P)
    render.run("/bin/true", {"x": 1}, tmp_path, "s-1", still_only=True, timeout=30)
    assert "OPENROUTER_API_KEY" not in seen["env"] and "sk-secret" not in json.dumps(seen["env"])
    assert seen["cmd"][-1] == "still"


def test_tool_errors_are_json(tmp_path):
    d = Director(lambda k, default=None: default, lambda: tmp_path)
    out = json.loads(_safe(d.render_scene)({"scene": {"objects": [{"id": "a", "shape": "teapot"}]}}))
    assert out["error"] == "scene spec has problems"
    out = json.loads(_safe(d.tweak)({"scene_id": "../x", "changes": {}}))
    assert "unknown scene id" in out["error"]


@pytest.mark.skipif(not BLENDER, reason="needs blender on PATH or BLENDER_BIN")
def test_real_preview_render(tmp_path):
    d = Director(lambda k, default=None: default, lambda: tmp_path)
    out = json.loads(_safe(d.render_scene)({"scene": json.loads((EX / "toy-desk.json").read_text()),
                                            "preview_only": True}))
    assert "error" not in out, out
    assert Path(out["preview"]).stat().st_size > 50_000
    assert Path(out["preview"]).parent.parent == tmp_path
