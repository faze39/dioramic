"""Runs inside Blender: `blender -b --factory-startup -P blender_build.py -- spec.json outdir`.

Reads an already validated scene spec as JSON data and builds the scene. It
never evaluates text from the spec; strings are only used as object names and
as the body of 3D text objects.
"""

import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
SPEC = json.load(open(argv[0]))
OUT = argv[1]
STILL_ONLY = len(argv) > 2 and argv[2] == "still"
D, FPS = SPEC["duration"], SPEC["fps"]
FRAMES = max(2, int(round(D * FPS)))


def lin(hexcol):
    h = hexcol.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c] + [1.0]


def ease(t):  # smooth in-out
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def frame_of(sec):
    return 1 + sec * FPS


# ---------- scene, render settings ----------
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE_NEXT"
w, h = (int(x) for x in SPEC["resolution"].split("x"))
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = w, h, 100
sc.render.fps = FPS
sc.frame_start, sc.frame_end = 1, FRAMES
sc.eevee.taa_render_samples = SPEC["samples"]
for attr, val in (("use_shadows", True), ("shadow_ray_count", 2), ("shadow_step_count", 6),
                  ("use_gtao", False)):
    try:
        setattr(sc.eevee, attr, val)
    except Exception:
        pass
sc.view_settings.view_transform = "AgX"
try:
    sc.view_settings.look = "AgX - Medium High Contrast"
except Exception:
    pass
sc.render.film_transparent = False

bg = lin(SPEC["background"])
world = bpy.data.worlds.new("w")
sc.world = world
world.use_nodes = True
wb = world.node_tree.nodes["Background"]
wb.inputs[0].default_value = [min(1, c * 1.15) for c in bg[:3]] + [1]
wb.inputs[1].default_value = 0.55 if SPEC["lighting"] != "night" else 0.25


def material(name, hexcol, finish):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = lin(hexcol)
    rough = {"toy": 0.32, "matte": 0.75, "metal": 0.22, "glow": 0.4}[finish]
    p.inputs["Roughness"].default_value = rough
    if finish == "metal":
        p.inputs["Metallic"].default_value = 1.0
    if finish == "toy":
        p.inputs["Coat Weight"].default_value = 0.35
        p.inputs["Coat Roughness"].default_value = 0.15
        p.inputs["Subsurface Weight"].default_value = 0.05
    if finish == "glow":
        p.inputs["Emission Color"].default_value = lin(hexcol)
        p.inputs["Emission Strength"].default_value = 1.1
    return m


# ---------- backdrop: a seamless studio sweep ----------
def backdrop():
    bm = bmesh.new()
    prof = [(-30 + i * 2.0, 0.0) for i in range(16)]  # floor y from -30 to 0
    r = 7.0
    for k in range(1, 17):
        a = k / 16 * math.pi / 2
        prof.append((r * math.sin(a), r - r * math.cos(a)))
    prof.append((r, 60.0))
    xs = (-90.0, 90.0)
    rows = [[bm.verts.new((x, y + 8, z)) for (y, z) in prof] for x in xs]
    for i in range(len(prof) - 1):
        bm.faces.new((rows[0][i], rows[1][i], rows[1][i + 1], rows[0][i + 1]))
    me = bpy.data.meshes.new("sweep")
    bm.to_mesh(me)
    for poly in me.polygons:
        poly.use_smooth = True
    ob = bpy.data.objects.new("sweep", me)
    sc.collection.objects.link(ob)
    m = material("sweep", SPEC["background"], "matte")
    m.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
    me.materials.append(m)


backdrop()


# ---------- lights ----------
def area(name, loc, power, size, col, target=(0, 0, 1)):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy, ld.size, ld.color = power, size, col
    ob = bpy.data.objects.new(name, ld)
    sc.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return ob


L = SPEC["lighting"]
if L == "soft":
    area("key", (-6, -6, 9), 1600, 7, (1, 0.97, 0.92))
    area("fill", (8, -4, 4), 450, 9, (0.9, 0.95, 1))
    area("rim", (2, 7, 7), 700, 4, (1, 1, 1))
elif L == "sunset":
    area("key", (-8, -3, 5), 1900, 5, (1, 0.62, 0.35))
    area("fill", (7, -6, 4), 380, 9, (0.55, 0.6, 1))
    area("rim", (3, 7, 6), 1100, 3, (1, 0.45, 0.6))
else:  # night
    area("key", (-6, -6, 8), 700, 6, (0.6, 0.7, 1))
    area("rim_a", (-5, 6, 4), 1400, 3, (1, 0.25, 0.75))
    area("rim_b", (6, 5, 4), 1400, 3, (0.2, 0.85, 1))


# ---------- objects ----------
def add_mesh(shape):
    ops = bpy.ops.mesh
    if shape == "cube":
        ops.primitive_cube_add(size=2)
    elif shape == "sphere":
        ops.primitive_uv_sphere_add(radius=1, segments=64, ring_count=32)
    elif shape == "cylinder":
        ops.primitive_cylinder_add(radius=1, depth=2, vertices=64)
    elif shape == "cone":
        ops.primitive_cone_add(radius1=1, depth=2, vertices=64)
    elif shape == "torus":
        ops.primitive_torus_add(major_radius=1, minor_radius=0.38, major_segments=72, minor_segments=32)
    elif shape == "gem":
        ops.primitive_ico_sphere_add(radius=1, subdivisions=1)
    elif shape == "capsule":
        ops.primitive_cylinder_add(radius=0.6, depth=2, vertices=48)
    ob = bpy.context.active_object
    if shape != "gem":
        for poly in ob.data.polygons:
            poly.use_smooth = True
    if shape in ("cube", "cylinder", "cone", "capsule"):
        bev = ob.modifiers.new("round", "BEVEL")
        bev.width = 0.55 if shape == "capsule" else 0.16
        bev.segments = 8 if shape == "capsule" else 5
        bev.limit_method = "ANGLE"
        bev.harden_normals = False
        ob.modifiers.new("ws", "WEIGHTED_NORMAL").keep_sharp = True
    return ob


def add_text(body):
    cu = bpy.data.curves.new("txt", "FONT")
    cu.body = body
    cu.align_x, cu.align_y = "CENTER", "CENTER"
    cu.extrude, cu.bevel_depth, cu.bevel_resolution = 0.18, 0.045, 4
    cu.size = 1.2
    ob = bpy.data.objects.new("txt", cu)
    sc.collection.objects.link(ob)
    return ob


def key_series(ob, path, fn, start, end, index=None):
    f0, f1 = int(math.floor(frame_of(start))), int(math.ceil(frame_of(end)))
    for f in range(f0, f1 + 1):
        t = (f - f0) / max(1, f1 - f0)
        fn(t)
        if index is None:
            ob.keyframe_insert(path, frame=f)
        else:
            ob.keyframe_insert(path, index=index, frame=f)


for o in SPEC["objects"]:
    ob = add_text(o["text"]) if o["shape"] == "text" else add_mesh(o["shape"])
    ob.name = o["id"]
    if o["shape"] == "text":
        ob.rotation_mode = "XYZ"
    ob.data.materials.append(material(o["id"], o["color"], o["finish"]))
    base_loc = Vector(o["position"])
    if o["shape"] == "text":
        base_rot = Vector([math.radians(90 + o["rotation"][0]), math.radians(o["rotation"][1]),
                           math.radians(o["rotation"][2])])
    else:
        base_rot = Vector([math.radians(v) for v in o["rotation"]])
    base_scale = Vector(o["scale"])
    ob.location, ob.rotation_euler, ob.scale = base_loc, base_rot, base_scale
    # Each animation writes absolute values, layered on the base pose in order.
    for a in o["animate"]:
        s, e, t = a["start"], a["end"], a["type"]
        if t == "spin":
            ax = "xyz".index(a["axis"])
            r0 = ob.rotation_euler[ax]

            def f(u, ax=ax, r0=r0, turns=a["turns"]):
                ob.rotation_euler[ax] = r0 + ease(u) * turns * 2 * math.pi
            key_series(ob, "rotation_euler", f, s, e, ax)
        elif t == "wobble":
            def f(u, deg=a["degrees"], n=a["count"]):
                ob.rotation_euler[1] = base_rot[1] + math.radians(deg) * math.sin(u * n * 2 * math.pi) * (1 - u)
            key_series(ob, "rotation_euler", f, s, e, 1)
        elif t in ("bounce", "float"):
            z0 = ob.location[2]

            def f(u, z0=z0, hgt=a["height"], n=a["count"], kind=t):
                ph = u * n
                if kind == "bounce":
                    y = abs(math.sin(ph * math.pi))
                    ob.location[2] = z0 + hgt * y
                    sq = 1 - 0.18 * max(0.0, 1 - y * 4)  # squash near contact
                    ob.scale = Vector((base_scale[0] / math.sqrt(sq), base_scale[1] / math.sqrt(sq),
                                       base_scale[2] * sq))
                else:
                    ob.location[2] = z0 + hgt * math.sin(ph * 2 * math.pi)
            key_series(ob, "location", f, s, e, 2)
            if t == "bounce":
                key_series(ob, "scale", f, s, e)
        elif t == "move":
            p0, p1 = ob.location.copy(), Vector(a["to"])

            def f(u, p0=p0, p1=p1):
                ob.location = p0.lerp(p1, ease(u))
            key_series(ob, "location", f, s, e)
        elif t == "pop_in":
            sc0 = base_scale.copy()

            def f(u, sc0=sc0):
                k = min(1.0, u * 3) * (1 + 0.25 * math.sin(u * math.pi) * (1 - u)) if u < 1 else 1
                ob.scale = sc0 * max(0.0001, k)
            ob.scale = sc0 * 0.0001
            ob.keyframe_insert("scale", frame=1)
            key_series(ob, "scale", f, s, e)
            ob.scale = sc0

# ---------- camera ----------
c = SPEC["camera"]
cd = bpy.data.cameras.new("cam")
cd.lens = c["lens"]
cd.sensor_fit = "VERTICAL"
cd.sensor_height = 36
cd.dof.use_dof = True
cd.dof.aperture_fstop = 4.0
cam = bpy.data.objects.new("cam", cd)
sc.collection.objects.link(cam)
sc.camera = cam
tgt = bpy.data.objects.new("target", None)
sc.collection.objects.link(tgt)
tgt.location = c["target"]
cd.dof.focus_object = tgt
tr = cam.constraints.new("TRACK_TO")
tr.target, tr.track_axis, tr.up_axis = tgt, "TRACK_NEGATIVE_Z", "UP_Y"
T = Vector(c["target"])
sp = c["speed"]


def cam_at(u):
    dist, hgt, ang = c["distance"], c["height"], c["angle"]
    m = c["move"]
    if m == "orbit":
        ang += 70 * sp * (u - 0.5)
    elif m == "push_in":
        dist *= 1 - 0.32 * sp * ease(u)
    elif m == "pull_out":
        dist *= 0.7 + 0.32 * sp * ease(u)
    elif m == "crane_up":
        hgt += 4 * sp * (ease(u) - 0.3)
    a = math.radians(ang)
    pos = T + Vector((math.sin(a) * dist, -math.cos(a) * dist, hgt))
    if m == "dolly":
        pos += Vector((math.cos(a), math.sin(a), 0)) * (4 * sp * (u - 0.5))
    pos.z = max(0.3, pos.z)
    return pos


for f in range(1, FRAMES + 1):
    u = (f - 1) / max(1, FRAMES - 1)
    cam.location = cam_at(u)
    cam.keyframe_insert("location", frame=f)

# ---------- output ----------
sc.render.image_settings.file_format = "PNG"
sc.frame_set(max(1, int(FRAMES * 0.6)))
sc.render.filepath = os.path.join(OUT, "preview.png")
bpy.ops.render.render(write_still=True)
if STILL_ONLY:
    print("DIORAMIC_DONE", 1)
    sys.exit(0)
sc.render.image_settings.file_format = "FFMPEG"
sc.render.ffmpeg.format = "MPEG4"
sc.render.ffmpeg.codec = "H264"
sc.render.ffmpeg.constant_rate_factor = "HIGH"
sc.render.ffmpeg.ffmpeg_preset = "GOOD"
sc.render.ffmpeg.audio_codec = "NONE"
sc.render.filepath = os.path.join(OUT, "clip.mp4")
sc.render.use_file_extension = False
bpy.ops.render.render(animation=True)
print("DIORAMIC_DONE", FRAMES)
