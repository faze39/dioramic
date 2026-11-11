_OBJ = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Unique lowercase id, used by dioramic_tweak."},
        "shape": {"type": "string", "enum": ["cube", "sphere", "cylinder", "cone", "torus", "gem", "capsule", "text"]},
        "text": {"type": "string", "description": "Only for shape=text, max 24 chars."},
        "color": {"type": "string", "description": "Palette name (red coral orange yellow lime mint green teal sky blue navy purple lilac pink white cream peach grey black gold) or #rrggbb."},
        "finish": {"type": "string", "enum": ["toy", "matte", "metal", "glow"]},
        "position": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z] in metres, z up, floor at z=0, about -4..4 fits a vertical frame."},
        "rotation": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z] degrees."},
        "scale": {"description": "Number or [x, y, z]. Base shapes are 2 m across.", "type": ["number", "array"]},
        "animate": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["spin", "bounce", "float", "pop_in", "move", "wobble"]},
                "start": {"type": "number"}, "end": {"type": "number"},
                "turns": {"type": "number"}, "axis": {"type": "string", "enum": ["x", "y", "z"]},
                "height": {"type": "number"}, "count": {"type": "number"},
                "degrees": {"type": "number"}, "to": {"type": "array", "items": {"type": "number"}},
            },
            "required": ["type"],
        }},
    },
    "required": ["id", "shape"],
}
_SCENE_PROPS = {
    "title": {"type": "string"},
    "duration": {"type": "number", "description": "Seconds (limit set by the user, default max 8)."},
    "fps": {"type": "integer", "enum": [24, 30]},
    "resolution": {"type": "string", "enum": ["540x960", "720x1280", "1080x1920"]},
    "background": {"type": "string", "description": "Backdrop colour, palette name or #rrggbb."},
    "lighting": {"type": "string", "enum": ["soft", "sunset", "night"]},
    "camera": {"type": "object", "properties": {
        "move": {"type": "string", "enum": ["orbit", "push_in", "pull_out", "crane_up", "dolly", "static"]},
        "speed": {"type": "number"}, "distance": {"type": "number"}, "height": {"type": "number"},
        "angle": {"type": "number"}, "lens": {"type": "number"},
        "target": {"type": "array", "items": {"type": "number"}}}},
    "objects": {"type": "array", "items": _OBJ},
}

RENDER = {
    "name": "dioramic_render",
    "description": (
        "Build and render a short vertical (9:16) 3D clip in headless Blender from a structured scene "
        "spec: toy-style shapes and 3D text, colours, lighting, a camera move and simple keyframed "
        "animation. Returns a scene_id, an MP4 path and a still preview path (as MEDIA: tags). Set "
        "preview_only=true for a fast still to check the layout before the full render."
    ),
    "parameters": {
        "type": "object",
        "properties": {"scene": {"type": "object", "properties": _SCENE_PROPS, "required": ["objects"]},
                       "preview_only": {"type": "boolean"}},
        "required": ["scene"],
    },
}

TWEAK = {
    "name": "dioramic_tweak",
    "description": (
        "Change a scene you already rendered and render it again as a new version. Send only what "
        "changes: top-level fields, camera fields, objects matched by id (unknown ids are added), "
        "and remove_objects. Example: make the cube red and the camera slower -> "
        '{"objects":[{"id":"cube","color":"red"}],"camera":{"speed":0.5}}.'
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "scene_id": {"type": "string", "description": "scene_id returned by an earlier render."},
            "changes": {"type": "object", "properties": {**_SCENE_PROPS, "remove_objects": {
                "type": "array", "items": {"type": "string"}}}},
            "preview_only": {"type": "boolean"},
        },
        "required": ["scene_id", "changes"],
    },
}
