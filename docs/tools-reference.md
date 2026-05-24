# Tools Reference

Every tool returns plain text unless noted otherwise. Errors come back as
`Error: <message>` rather than raising — that's friendlier to LLM consumers.

The "Example call" snippets show the JSON payload an MCP client sends; you
don't normally write these by hand — Claude does.

---

## Core tools

### `get_scene_info()`

Summary of the current Blender scene (objects with type/location/dimensions,
materials, frame range, etc.). No arguments.

**Example call**
```json
{"name": "get_scene_info", "arguments": {}}
```

---

### `get_object_info(object_name)`

Detailed information about a single object.

| Parameter | Type | Description |
|-----------|------|-------------|
| `object_name` | string | Exact name from the outliner. |

**Example call**
```json
{"name": "get_object_info", "arguments": {"object_name": "Cube"}}
```

---

### `get_viewport_screenshot(max_size=1024)`

Renders the active viewport to PNG and returns it inline so Claude can see
the scene.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_size` | int | `1024` | Longest edge of the image in pixels. |

**Example call**
```json
{"name": "get_viewport_screenshot", "arguments": {"max_size": 800}}
```

---

### `execute_blender_code(code)`

Run any Python code in the live Blender process. The value of the final
expression is returned as a string.

| Parameter | Type | Description |
|-----------|------|-------------|
| `code` | string | Python source. `import bpy` is encouraged. |

**Example call**
```json
{"name": "execute_blender_code",
 "arguments": {"code": "import bpy; len(bpy.data.objects)"}}
```

---

## 3D print tools

### `export_stl(filepath, object_name=None, ascii_format=False)`

Write an STL ready for slicing.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filepath` | string | — | **Absolute** output path. Parent dirs are created. |
| `object_name` | string \| null | `null` | Export just this object if set, else the whole scene. |
| `ascii_format` | bool | `false` | ASCII vs binary STL. |

**Example call**
```json
{"name": "export_stl",
 "arguments": {"filepath": "/mnt/c/Users/me/Downloads/widget.stl",
               "object_name": "Widget"}}
```

---

### `get_dimensions_mm(object_name)`

Bounding-box dimensions in **millimetres**, honouring the scene's
`unit_settings.scale_length`. Works whether your blend file is in meters,
millimeters, or anything else.

**Example call**
```json
{"name": "get_dimensions_mm", "arguments": {"object_name": "Widget"}}
```

---

### `scale_to_dimensions(object_name, x_mm=None, y_mm=None, z_mm=None)`

Uniformly scale an object so a target axis matches the requested size. If
multiple axes are supplied, the first non-null in X→Y→Z order wins (the
scale is uniform, so the other axes follow proportionally).

**Example call**
```json
{"name": "scale_to_dimensions",
 "arguments": {"object_name": "Widget", "x_mm": 50.0}}
```

---

### `scale_to_fit_printer(object_name, printer="kobra_s1_combo", margin_mm=5.0)`

Uniformly scale (down only) so the object fits the printer's build volume
minus a per-side margin.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `object_name` | string | — | Object to scale. |
| `printer` | string | `"kobra_s1_combo"` | Currently the only supported preset (220×220×250 mm). |
| `margin_mm` | float | `5.0` | Margin per side. |

If the object already fits, the tool reports that and does **not** scale up.

**Example call**
```json
{"name": "scale_to_fit_printer",
 "arguments": {"object_name": "Widget"}}
```

---

### `set_print_origin(object_name)`

Sets the object's origin to its bounding-box centre, then moves it so the
bottom of the bounding box sits at Z=0 (the print bed).

**Example call**
```json
{"name": "set_print_origin", "arguments": {"object_name": "Widget"}}
```

---

### `apply_all_modifiers(object_name)`

Bakes every modifier on a mesh into permanent geometry. Required if you're
exporting an STL of something with subdivision, mirror, array, or boolean
modifiers and want them to show up in the print.

**Example call**
```json
{"name": "apply_all_modifiers", "arguments": {"object_name": "Widget"}}
```

---

### `check_printability(object_name)`

A battery of print-readiness checks. The report uses `[OK]`, `[WARN]`,
`[FAIL]` tags:

1. **Mesh type** — must be a mesh.
2. **Manifold edges** — every edge connects exactly two faces (watertight).
3. **Loose vertices** — none.
4. **Inverted normals** — heuristic ratio of faces whose normal points
   toward the mesh centroid instead of away.
5. **Dimensions** — non-zero, not microscopic (< 1 mm), not absurd (> 400 mm).

**Example call**
```json
{"name": "check_printability", "arguments": {"object_name": "Widget"}}
```

---

### `add_print_base(object_name, thickness_mm=1.5, margin_mm=2.0)`

Adds a separate rectangular cube under the object — sized to the object's
XY footprint plus a per-side margin and the requested thickness, with its
top surface just kissing the object's lowest point. Useful for parts with
small footprints that warp/lift during printing.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `object_name` | string | — | Object to put a base under. |
| `thickness_mm` | float | `1.5` | Base thickness in mm. |
| `margin_mm` | float | `2.0` | How far the base extends past the footprint per side, in mm. |

**Example call**
```json
{"name": "add_print_base",
 "arguments": {"object_name": "Widget", "thickness_mm": 2.0}}
```

---

### `list_print_presets()`

Static reference data for the currently profiled printers (Anycubic
Kobra S1 Combo). Useful as a "what should my slicer settings be" cheat
sheet.

**Example call**
```json
{"name": "list_print_presets", "arguments": {}}
```
