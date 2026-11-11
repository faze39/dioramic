"""dioramic: the agent describes a scene, Blender renders it as a vertical clip.

Tools take a structured scene spec (never code). The spec is validated with fixed
limits, written to a plugin-owned folder, and read as data by a fixed Blender
build script running headless with a scrubbed environment and a timeout.
"""

from __future__ import annotations

import json
import logging

from . import render, schemas, spec

logger = logging.getLogger(__name__)
PLUGIN = "dioramic"


class Director:
    def __init__(self, setting, root):
        self._setting, self._root = setting, root

    def _limits(self):
        s = self._setting
        return {"max_duration": max(1.0, min(20.0, float(s("max_duration", 8) or 8))),
                "allow_hd": bool(s("allow_hd", False)),
                "max_samples": max(1, min(64, int(s("max_samples", 16) or 16)))}

    def _blender(self):
        b = render.find_blender(self._setting("blender_path", "") or "")
        if not b:
            raise render.RenderError("Blender not found: set plugins.entries.dioramic.settings.blender_path "
                                     "or put blender on PATH")
        return b

    def _go(self, raw, scene_id, preview_only):
        clean, warnings = spec.normalise(raw, **self._limits())
        timeout = max(30, min(1800, int(self._setting("render_timeout", 600) or 600)))
        res = render.run(self._blender(), clean, self._root(), scene_id, still_only=bool(preview_only),
                         timeout=timeout)
        res["warnings"] = warnings
        res["frames"] = 1 if preview_only else int(round(clean["duration"] * clean["fps"]))
        res["spec"] = {k: clean[k] for k in ("title", "duration", "fps", "resolution", "lighting")}
        res["objects"] = [o["id"] for o in clean["objects"]]
        res["media"] = [f"MEDIA:{p}" for p in (res["clip"], res["preview"]) if p]
        return res

    def render_scene(self, args):
        raw = (args or {}).get("scene")
        title = raw.get("title", "scene") if isinstance(raw, dict) else "scene"
        return self._go(raw, render.slug(str(title)), (args or {}).get("preview_only"))

    def tweak(self, args):
        args = args or {}
        sid = str(args.get("scene_id") or "")
        base = json.loads((render.scene_dir(self._root(), sid) / "spec.json").read_text())
        merged = spec.merge(base, args.get("changes") or {})
        stem = sid.split("-v")[0] if "-v" in sid else sid
        n = 2
        while (self._root() / f"{stem}-v{n}").exists():
            n += 1
        res = self._go(merged, f"{stem}-v{n}", args.get("preview_only"))
        res["based_on"] = sid
        return res


def _safe(fn):
    def handler(args, **kwargs):
        try:
            return json.dumps(fn(args))
        except spec.SpecError as exc:
            return json.dumps({"error": "scene spec has problems", "problems": exc.problems})
        except render.RenderError as exc:
            return json.dumps({"error": str(exc)})
        except Exception as exc:  # never raise into the agent loop
            logger.exception("dioramic failed")
            return json.dumps({"error": f"dioramic failed: {exc}"})
    return handler


def register(ctx):
    from plugins.plugin_storage import plugin_data_dir

    director = Director(lambda k, d=None: ctx.get_config(k, default=d),
                        lambda: plugin_data_dir(PLUGIN) / "scenes")
    ctx.register_tool(name="dioramic_render", toolset="dioramic", schema=schemas.RENDER,
                      handler=_safe(director.render_scene), description="Render a 3D vertical clip in Blender",
                      emoji="🎬")
    ctx.register_tool(name="dioramic_tweak", toolset="dioramic", schema=schemas.TWEAK,
                      handler=_safe(director.tweak), description="Change a rendered scene and re-render",
                      emoji="🎬")
