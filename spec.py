"""Scene spec validation. Pure Python, no Blender import.

The model only ever sends a JSON scene spec. This module checks every field
against fixed enums and numeric limits and returns a normalised copy. Blender
later reads that JSON as data; no model text is ever executed.
"""

from __future__ import annotations

import copy
import re

SHAPES = ("cube", "sphere", "cylinder", "cone", "torus", "gem", "capsule", "text")
FINISHES = ("toy", "matte", "metal", "glow")
ANIMS = ("spin", "bounce", "float", "pop_in", "move", "wobble")
CAMERA_MOVES = ("orbit", "push_in", "pull_out", "crane_up", "dolly", "static")
LIGHTING = ("soft", "sunset", "night")
RESOLUTIONS = {"540x960": (540, 960), "720x1280": (720, 1280), "1080x1920": (1080, 1920)}

PALETTE = {
    "red": "#e8453c", "coral": "#ff7a6b", "orange": "#ff9a3c", "yellow": "#ffd23f",
    "lime": "#b5e550", "mint": "#7fe0b5", "green": "#3fb873", "teal": "#2bb3b1",
    "sky": "#7cc8f5", "blue": "#3b7cf0", "navy": "#24346b", "purple": "#8b5cf6",
    "lilac": "#c4a7f5", "pink": "#ff8fc7", "white": "#f6f4ef", "cream": "#fbecd2",
    "peach": "#ffc9a8", "grey": "#9aa0a8", "black": "#22232a", "gold": "#e8b63c",
}
HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")
ID = re.compile(r"^[a-z0-9_-]{1,24}$")

LIMITS = {"objects": 24, "text_len": 24, "anims_per_object": 4, "coord": 12.0,
          "scale": 6.0, "duration_min": 1.0}


class SpecError(ValueError):
    def __init__(self, problems):
        self.problems = problems
        super().__init__("; ".join(problems))


def color(value, where, problems):
    if isinstance(value, str):
        v = value.strip().lower()
        if v in PALETTE:
            return PALETTE[v]
        if HEX.match(v):
            return "#" + v.lstrip("#")
    problems.append(f"{where}: '{value}' is not a colour; use a palette name ({', '.join(PALETTE)}) or #rrggbb")
    return "#ffffff"


def _num(value, lo, hi, default, where, warnings):
    if value is None:
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        warnings.append(f"{where}: not a number, used {default}")
        return default
    if f != f:  # NaN
        return default
    if f < lo or f > hi:
        warnings.append(f"{where}: {f:g} clamped to [{lo:g}, {hi:g}]")
    return max(lo, min(hi, f))


def _vec(value, default, lim, where, warnings):
    if value is None:
        return list(default)
    if isinstance(value, (int, float)):
        value = [value] * 3
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        warnings.append(f"{where}: expected [x, y, z], used {list(default)}")
        return list(default)
    return [_num(v, -lim, lim, d, f"{where}[{i}]", warnings) for i, (v, d) in enumerate(zip(value, default))]


def _enum(value, allowed, default, where, problems):
    if value is None:
        return default
    v = str(value).strip().lower()
    if v not in allowed:
        problems.append(f"{where}: '{value}' is not one of {', '.join(allowed)}")
        return default
    return v


def _anim(a, i, duration, where, problems, warnings):
    if not isinstance(a, dict):
        problems.append(f"{where}: animation must be an object")
        return None
    w = f"{where}.animate[{i}]"
    out = {"type": _enum(a.get("type"), ANIMS, "spin", f"{w}.type", problems)}
    out["start"] = _num(a.get("start"), 0, duration, 0.0, f"{w}.start", warnings)
    out["end"] = _num(a.get("end"), out["start"], duration, duration, f"{w}.end", warnings)
    if out["end"] - out["start"] < 0.1:
        out["end"] = min(duration, out["start"] + 0.5)
    t = out["type"]
    if t == "spin":
        out["turns"] = _num(a.get("turns"), -6, 6, 1.0, f"{w}.turns", warnings)
        out["axis"] = _enum(a.get("axis"), ("x", "y", "z"), "z", f"{w}.axis", problems)
    elif t in ("bounce", "float"):
        out["height"] = _num(a.get("height"), 0, 6, 1.0 if t == "bounce" else 0.3, f"{w}.height", warnings)
        out["count"] = _num(a.get("count"), 0.5, 12, 2 if t == "bounce" else 1, f"{w}.count", warnings)
    elif t == "move":
        out["to"] = _vec(a.get("to"), [0, 0, 0], LIMITS["coord"], f"{w}.to", warnings)
    elif t == "wobble":
        out["degrees"] = _num(a.get("degrees"), 0, 90, 12, f"{w}.degrees", warnings)
        out["count"] = _num(a.get("count"), 0.5, 12, 3, f"{w}.count", warnings)
    return out


def _object(o, i, duration, problems, warnings, seen):
    where = f"objects[{i}]"
    if not isinstance(o, dict):
        problems.append(f"{where}: must be an object")
        return None
    oid = str(o.get("id") or f"obj{i + 1}").strip().lower()
    if not ID.match(oid) or oid in seen:
        problems.append(f"{where}.id: '{oid}' must be unique, lowercase letters, digits, _ or - (max 24)")
    seen.add(oid)
    shape = _enum(o.get("shape"), SHAPES, "cube", f"{where}.shape", problems)
    out = {"id": oid, "shape": shape,
           "color": color(o.get("color", "white"), f"{where}.color", problems),
           "finish": _enum(o.get("finish"), FINISHES, "toy", f"{where}.finish", problems),
           "position": _vec(o.get("position"), [0, 0, 0], LIMITS["coord"], f"{where}.position", warnings),
           "rotation": _vec(o.get("rotation"), [0, 0, 0], 360, f"{where}.rotation", warnings),
           "scale": _vec(o.get("scale"), [1, 1, 1], LIMITS["scale"], f"{where}.scale", warnings)}
    out["scale"] = [max(0.05, s) for s in out["scale"]]
    if shape == "text":
        text = str(o.get("text") or "").strip()
        if not text:
            problems.append(f"{where}.text: a text object needs text")
        if len(text) > LIMITS["text_len"]:
            warnings.append(f"{where}.text: cut to {LIMITS['text_len']} characters")
        out["text"] = "".join(ch for ch in text[:LIMITS["text_len"]] if ch.isprintable())
    anims = o.get("animate") or []
    if isinstance(anims, dict):
        anims = [anims]
    if not isinstance(anims, list):
        problems.append(f"{where}.animate: must be a list")
        anims = []
    if len(anims) > LIMITS["anims_per_object"]:
        warnings.append(f"{where}.animate: only the first {LIMITS['anims_per_object']} kept")
    out["animate"] = [x for x in (_anim(a, j, duration, where, problems, warnings)
                                  for j, a in enumerate(anims[:LIMITS["anims_per_object"]])) if x]
    return out


def normalise(spec, *, max_duration=8.0, allow_hd=False, max_samples=16):
    """Return (clean_spec, warnings) or raise SpecError with every problem."""
    if not isinstance(spec, dict):
        raise SpecError(["scene must be a JSON object"])
    problems, warnings = [], []
    duration = _num(spec.get("duration"), LIMITS["duration_min"], max_duration, min(5.0, max_duration),
                    "duration", warnings)
    fps = int(_num(spec.get("fps"), 24, 30, 24, "fps", warnings))
    fps = 30 if fps >= 27 else 24
    res = str(spec.get("resolution") or "540x960")
    if res not in RESOLUTIONS or (res == "1080x1920" and not allow_hd):
        warnings.append(f"resolution {res} not allowed here, used 540x960")
        res = "540x960"
    cam = spec.get("camera") or {}
    if not isinstance(cam, dict):
        problems.append("camera: must be an object")
        cam = {}
    camera = {"move": _enum(cam.get("move"), CAMERA_MOVES, "orbit", "camera.move", problems),
              "speed": _num(cam.get("speed"), 0.1, 3, 1.0, "camera.speed", warnings),
              "distance": _num(cam.get("distance"), 3, 30, 13, "camera.distance", warnings),
              "height": _num(cam.get("height"), -2, 15, 3.0, "camera.height", warnings),
              "angle": _num(cam.get("angle"), -180, 180, 25, "camera.angle", warnings),
              "lens": _num(cam.get("lens"), 18, 135, 40, "camera.lens", warnings),
              "target": _vec(cam.get("target"), [0, 0, 1], LIMITS["coord"], "camera.target", warnings)}
    objs = spec.get("objects")
    if not isinstance(objs, list) or not objs:
        problems.append("objects: give at least one object")
        objs = []
    if len(objs) > LIMITS["objects"]:
        warnings.append(f"objects: only the first {LIMITS['objects']} kept")
    seen: set = set()
    objects = [x for x in (_object(o, i, duration, problems, warnings, seen)
                           for i, o in enumerate(objs[:LIMITS["objects"]])) if x]
    clean = {
        "title": str(spec.get("title") or "untitled")[:60],
        "style": "toy",
        "duration": duration, "fps": fps, "resolution": res,
        "samples": int(_num(spec.get("samples"), 1, max_samples, min(6, max_samples), "samples", warnings)),
        "background": color(spec.get("background", "cream"), "background", problems),
        "lighting": _enum(spec.get("lighting"), LIGHTING, "soft", "lighting", problems),
        "camera": camera, "objects": objects,
    }
    if problems:
        raise SpecError(problems)
    return clean, warnings


def merge(base, changes):
    """Apply a partial spec to a previous one. Objects merge by id; remove_objects drops ids."""
    if not isinstance(changes, dict):
        raise SpecError(["changes must be a JSON object"])
    out = copy.deepcopy(base)
    for key, value in changes.items():
        if key in ("objects", "remove_objects"):
            continue
        if key == "camera" and isinstance(value, dict):
            out["camera"] = {**out.get("camera", {}), **value}
        else:
            out[key] = value
    drop = {str(x).lower() for x in changes.get("remove_objects") or []}
    objects = [o for o in out.get("objects", []) if o.get("id") not in drop]
    index = {o.get("id"): o for o in objects}
    for patch in changes.get("objects") or []:
        if not isinstance(patch, dict):
            raise SpecError(["objects in changes must be JSON objects"])
        pid = str(patch.get("id") or "").lower()
        if pid in index:
            index[pid].update({k: v for k, v in patch.items() if k != "id"})
        else:
            objects.append(patch)
    out["objects"] = objects
    return out
