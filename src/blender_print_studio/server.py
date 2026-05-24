"""FastMCP server exposing Blender control + 3D-printing tools.

The server talks to a running Blender instance over a TCP socket (the
``ahujasid/blender-mcp`` addon). On top of the upstream addon's commands
we add a suite of print-focused tools that execute Blender Python in the
running Blender process via the ``execute_code`` command.

Implementation note: the upstream addon's ``execute_code`` handler returns
the *captured stdout* of the executed snippet — not the value of the final
expression. Every snippet below therefore uses ``print(...)`` to report
its result. Direct attribute assignment (``obj.scale = ...``,
``obj.location = ...``) is preferred over ``bpy.ops.transform.*`` because
operator calls require a viewport context that ``execute_code`` does not
provide.
"""

from __future__ import annotations

import base64
import json
import logging
from textwrap import dedent
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from .blender_conn import get_connection

logger = logging.getLogger(__name__)

mcp = FastMCP("blender-print-studio")

# --------------------------------------------------------------------------- #
# Printer presets
# --------------------------------------------------------------------------- #
PRINTER_VOLUMES_MM: dict[str, tuple[float, float, float]] = {
    # Anycubic Kobra S1 Combo
    "kobra_s1_combo": (220.0, 220.0, 250.0),
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _run_code(code: str) -> Any:
    """Execute Blender Python via the socket and return its ``result``."""
    return get_connection().send_command("execute_code", {"code": dedent(code)})


def _format_dict(data: Any, indent: int = 2) -> str:
    """Pretty-print a dict/list for tool responses."""
    try:
        return json.dumps(data, indent=indent, default=str)
    except (TypeError, ValueError):
        return str(data)


def _extract_text_result(result: Any) -> str:
    """Pull a useful text payload out of whatever ``execute_code`` returned.

    The upstream addon's ``execute_code`` handler returns a dict shaped like
    ``{"executed": True, "result": "<captured stdout>"}``. Fall back to the
    raw structure for anything else.
    """
    if isinstance(result, str):
        return result.rstrip()
    if isinstance(result, dict):
        for key in ("result", "output", "message", "executed"):
            value = result.get(key)
            if isinstance(value, str):
                return value.rstrip()
            if isinstance(value, (int, float)):
                return str(value)
        return _format_dict(result)
    return str(result)


# --------------------------------------------------------------------------- #
# Core Blender tools (thin wrappers over the upstream socket commands)
# --------------------------------------------------------------------------- #
@mcp.tool()
def get_scene_info() -> str:
    """Return a summary of the current Blender scene (objects, materials, frame range)."""
    try:
        info = get_connection().send_command("get_scene_info")
    except (ConnectionError, RuntimeError) as exc:
        return f"Error: {exc}"
    return _format_dict(info)


@mcp.tool()
def get_object_info(object_name: str) -> str:
    """Return detailed info about a single object (transform, mesh stats, materials).

    Args:
        object_name: Exact name of the object as it appears in Blender's outliner.
    """
    try:
        info = get_connection().send_command(
            "get_object_info", {"name": object_name}
        )
    except (ConnectionError, RuntimeError) as exc:
        return f"Error: {exc}"
    return _format_dict(info)


@mcp.tool()
def get_viewport_screenshot(max_size: int = 1024) -> list[Any]:
    """Grab a PNG screenshot of the active Blender 3D viewport.

    Args:
        max_size: Longest edge of the returned image in pixels (default 1024).

    Returns text + an inline PNG so Claude can actually see the scene.
    """
    try:
        result = get_connection().send_command(
            "get_viewport_screenshot", {"max_size": max_size}
        )
    except (ConnectionError, RuntimeError) as exc:
        return [TextContent(type="text", text=f"Error: {exc}")]

    # The addon may return either base64 in result["image"] / result["data"]
    # or a dict with an embedded data URI. Handle both.
    image_b64: Optional[str] = None
    if isinstance(result, dict):
        for key in ("image", "data", "image_data", "screenshot"):
            value = result.get(key)
            if isinstance(value, str) and value:
                if value.startswith("data:image"):
                    _, _, payload = value.partition(",")
                    image_b64 = payload
                else:
                    image_b64 = value
                break

    if image_b64:
        try:
            base64.b64decode(image_b64, validate=True)
        except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
            return [
                TextContent(
                    type="text",
                    text=(
                        "Viewport screenshot returned, but the base64 payload "
                        f"was not valid. Raw response: {_format_dict(result)}"
                    ),
                )
            ]
        return [
            TextContent(type="text", text="Viewport screenshot captured."),
            ImageContent(type="image", data=image_b64, mimeType="image/png"),
        ]

    return [TextContent(type="text", text=_format_dict(result))]


@mcp.tool()
def execute_blender_code(code: str) -> str:
    """Run arbitrary Python code inside the running Blender process.

    This is the escape hatch — anything you can do in Blender's scripting
    workspace, you can do here. Whatever the snippet ``print``s is returned
    (the upstream addon captures stdout, not the final expression).

    Args:
        code: Python source. ``bpy`` is preloaded in the execution
            namespace but it's good practice to ``import bpy``.
    """
    try:
        result = _run_code(code)
    except (ConnectionError, RuntimeError) as exc:
        return f"Error: {exc}"
    text = _extract_text_result(result)
    return text if text else "(executed; no output)"


# --------------------------------------------------------------------------- #
# 3D printing tools
# --------------------------------------------------------------------------- #
@mcp.tool()
def export_stl(
    filepath: str,
    object_name: Optional[str] = None,
    ascii_format: bool = False,
) -> str:
    """Export an STL file ready for slicing.

    Args:
        filepath: Absolute path of the STL to write. Parent directories are
            created if missing.
        object_name: If provided, only that object is exported. Otherwise the
            whole scene is exported.
        ascii_format: If True, write ASCII STL (larger, human-readable). The
            default is binary STL.
    """
    obj_literal = repr(object_name) if object_name else "None"
    code = f"""
        import bpy, os
        filepath = {filepath!r}
        object_name = {obj_literal}
        parent = os.path.dirname(filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if object_name:
            if object_name not in bpy.data.objects:
                raise ValueError("Object " + repr(object_name) + " not found in scene")
            bpy.ops.object.select_all(action='DESELECT')
            obj = bpy.data.objects[object_name]
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            use_selection = True
        else:
            use_selection = False
        bpy.ops.wm.stl_export(
            filepath=filepath,
            ascii_format={ascii_format},
            export_selected_objects=use_selection,
        )
        print("Exported to " + filepath)
    """
    try:
        result = _run_code(code)
    except (ConnectionError, RuntimeError) as exc:
        return f"Error: {exc}"
    return _extract_text_result(result)


@mcp.tool()
def get_dimensions_mm(object_name: str) -> str:
    """Return the object's bounding-box dimensions in millimetres.

    Honours the scene's unit scale so the answer is correct whether the file
    is set up in metres (Blender default), millimetres, or anything else.

    Args:
        object_name: Exact name of the object to measure.
    """
    code = f"""
        import bpy
        name = {object_name!r}
        if name not in bpy.data.objects:
            raise ValueError("Object " + repr(name) + " not found in scene")
        obj = bpy.data.objects[name]
        dims = obj.dimensions
        scene = bpy.context.scene
        unit_scale = scene.unit_settings.scale_length
        dims_mm = [d * unit_scale * 1000 for d in dims]
        print("Dimensions: X={{:.2f}}mm  Y={{:.2f}}mm  Z={{:.2f}}mm".format(
            dims_mm[0], dims_mm[1], dims_mm[2]
        ))
    """
    try:
        result = _run_code(code)
    except (ConnectionError, RuntimeError) as exc:
        return f"Error: {exc}"
    return _extract_text_result(result)


@mcp.tool()
def scale_to_dimensions(
    object_name: str,
    x_mm: Optional[float] = None,
    y_mm: Optional[float] = None,
    z_mm: Optional[float] = None,
) -> str:
    """Uniformly scale an object so a target dimension matches the requested size.

    At least one of ``x_mm``, ``y_mm``, or ``z_mm`` must be supplied. If
    multiple are given, the first non-null in X, Y, Z order is used as the
    scale reference — the scale is uniform, so the other axes follow
    proportionally.

    Args:
        object_name: Object to scale.
        x_mm: Desired X dimension in mm.
        y_mm: Desired Y dimension in mm.
        z_mm: Desired Z dimension in mm.
    """
    if x_mm is None and y_mm is None and z_mm is None:
        return "Error: provide at least one of x_mm, y_mm, z_mm."

    code = f"""
        import bpy
        name = {object_name!r}
        targets = {{'x': {x_mm!r}, 'y': {y_mm!r}, 'z': {z_mm!r}}}
        if name not in bpy.data.objects:
            raise ValueError("Object " + repr(name) + " not found in scene")
        obj = bpy.data.objects[name]
        scene = bpy.context.scene
        unit_scale = scene.unit_settings.scale_length
        dims = obj.dimensions
        dims_mm = {{
            'x': dims.x * unit_scale * 1000,
            'y': dims.y * unit_scale * 1000,
            'z': dims.z * unit_scale * 1000,
        }}
        axis = None
        for a in ('x', 'y', 'z'):
            if targets[a] is not None:
                axis = a
                break
        if dims_mm[axis] <= 0:
            raise ValueError(
                "Cannot scale: object " + repr(name)
                + " has zero size on the " + axis + " axis"
            )
        factor = targets[axis] / dims_mm[axis]
        # Apply uniform scale directly — works without a viewport context.
        obj.scale = (obj.scale.x * factor, obj.scale.y * factor, obj.scale.z * factor)
        # Refresh dependency graph so obj.dimensions reflects the new scale.
        bpy.context.view_layer.update()
        new_dims_mm = [d * unit_scale * 1000 for d in obj.dimensions]
        print(
            "Scaled {{!r}} by {{:.4f}} on axis {{}}; new dimensions "
            "X={{:.2f}}mm Y={{:.2f}}mm Z={{:.2f}}mm".format(
                name, factor, axis,
                new_dims_mm[0], new_dims_mm[1], new_dims_mm[2],
            )
        )
    """
    try:
        result = _run_code(code)
    except (ConnectionError, RuntimeError) as exc:
        return f"Error: {exc}"
    return _extract_text_result(result)


@mcp.tool()
def scale_to_fit_printer(
    object_name: str,
    printer: str = "kobra_s1_combo",
    margin_mm: float = 5.0,
) -> str:
    """Uniformly scale an object down (never up) to fit inside a printer's build volume.

    Args:
        object_name: Object to scale.
        printer: Printer key. Currently supports ``kobra_s1_combo`` (220x220x250 mm).
        margin_mm: Safety margin subtracted from each axis (per side).
    """
    if printer not in PRINTER_VOLUMES_MM:
        known = ", ".join(sorted(PRINTER_VOLUMES_MM))
        return f"Error: unknown printer {printer!r}. Known printers: {known}."

    bx, by, bz = PRINTER_VOLUMES_MM[printer]
    code = f"""
        import bpy
        name = {object_name!r}
        printer = {printer!r}
        bx, by, bz = {bx!r}, {by!r}, {bz!r}
        margin = {margin_mm!r}
        if name not in bpy.data.objects:
            raise ValueError("Object " + repr(name) + " not found in scene")
        obj = bpy.data.objects[name]
        scene = bpy.context.scene
        unit_scale = scene.unit_settings.scale_length
        dims_mm = [d * unit_scale * 1000 for d in obj.dimensions]
        usable = (
            max(bx - 2 * margin, 0.001),
            max(by - 2 * margin, 0.001),
            max(bz - 2 * margin, 0.001),
        )
        if min(dims_mm) <= 0:
            raise ValueError(
                "Object " + repr(name) + " has zero size on at least one axis"
            )
        factors = [usable[i] / dims_mm[i] for i in range(3)]
        factor = min(factors)
        if factor >= 1.0:
            print(
                "{{!r}} already fits ({{:.1f}} x {{:.1f}} x {{:.1f}} mm) inside "
                "{{:.1f}} x {{:.1f}} x {{:.1f}} mm usable volume. No scaling applied.".format(
                    name, dims_mm[0], dims_mm[1], dims_mm[2],
                    usable[0], usable[1], usable[2],
                )
            )
        else:
            obj.scale = (
                obj.scale.x * factor,
                obj.scale.y * factor,
                obj.scale.z * factor,
            )
            bpy.context.view_layer.update()
            new_dims_mm = [d * unit_scale * 1000 for d in obj.dimensions]
            print(
                "Scaled {{!r}} by {{:.4f}} to fit {{!r}} ({{:.0f}} x {{:.0f}} x "
                "{{:.0f}} mm, margin {{}}mm). New dimensions: "
                "X={{:.2f}}mm Y={{:.2f}}mm Z={{:.2f}}mm".format(
                    name, factor, printer, bx, by, bz, margin,
                    new_dims_mm[0], new_dims_mm[1], new_dims_mm[2],
                )
            )
    """
    try:
        result = _run_code(code)
    except (ConnectionError, RuntimeError) as exc:
        return f"Error: {exc}"
    return _extract_text_result(result)


@mcp.tool()
def set_print_origin(object_name: str) -> str:
    """Move the object's origin to its bottom-centre and position it on Z=0.

    After running this, the object sits flat on the print bed — which is what
    every slicer expects.

    Args:
        object_name: Object to reposition.
    """
    code = f"""
        import bpy
        name = {object_name!r}
        if name not in bpy.data.objects:
            raise ValueError("Object " + repr(name) + " not found in scene")
        obj = bpy.data.objects[name]
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
        obj.location.z = obj.dimensions.z / 2
        bpy.context.view_layer.update()
        print("Origin set to bottom-center, object positioned on bed")
    """
    try:
        result = _run_code(code)
    except (ConnectionError, RuntimeError) as exc:
        return f"Error: {exc}"
    return _extract_text_result(result)


@mcp.tool()
def apply_all_modifiers(object_name: str) -> str:
    """Bake every modifier on a mesh, producing a clean static mesh for STL export.

    Args:
        object_name: Mesh object whose modifier stack should be flattened.
    """
    code = f"""
        import bpy
        name = {object_name!r}
        if name not in bpy.data.objects:
            raise ValueError("Object " + repr(name) + " not found in scene")
        obj = bpy.data.objects[name]
        if obj.type != 'MESH':
            raise ValueError(
                "Object " + repr(name) + " is a " + obj.type + ", not a mesh"
            )
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        applied = []
        # Iterate over a snapshot of names — applying mutates the collection.
        for mod_name in [m.name for m in obj.modifiers]:
            try:
                bpy.ops.object.modifier_apply(modifier=mod_name)
                applied.append(mod_name)
            except RuntimeError as exc:
                applied.append(mod_name + " (FAILED: " + str(exc) + ")")
        if not applied:
            print("No modifiers on " + repr(name) + "; nothing to do.")
        else:
            print(
                "Applied " + str(len(applied)) + " modifier(s) on "
                + repr(name) + ": " + ", ".join(applied)
            )
    """
    try:
        result = _run_code(code)
    except (ConnectionError, RuntimeError) as exc:
        return f"Error: {exc}"
    return _extract_text_result(result)


@mcp.tool()
def check_printability(object_name: str) -> str:
    """Run a battery of print-readiness checks against a mesh.

    Checks: mesh type, non-manifold edges, loose vertices, inverted normals,
    and a sanity check on overall dimensions.

    Args:
        object_name: Mesh object to inspect.
    """
    code = f"""
        import bpy, bmesh
        from mathutils import Vector

        name = {object_name!r}
        OK = "[OK]"
        WARN = "[WARN]"
        BAD = "[FAIL]"
        lines = []

        if name not in bpy.data.objects:
            lines.append(BAD + " Object " + repr(name) + " not found in scene.")
        else:
            obj = bpy.data.objects[name]

            # 1. Mesh type
            if obj.type != 'MESH':
                lines.append(
                    BAD + " " + repr(name) + " is a " + obj.type
                    + ", not a mesh - cannot print."
                )
            else:
                lines.append(OK + " Object is a mesh.")

                # Build a bmesh from the evaluated mesh so modifiers count.
                depsgraph = bpy.context.evaluated_depsgraph_get()
                eval_obj = obj.evaluated_get(depsgraph)
                mesh = eval_obj.to_mesh()
                bm = bmesh.new()
                bm.from_mesh(mesh)
                bm.normal_update()

                # 2. Non-manifold edges
                non_manifold = [e for e in bm.edges if not e.is_manifold]
                if non_manifold:
                    lines.append(
                        BAD + " " + str(len(non_manifold))
                        + " non-manifold edge(s) - mesh is not watertight."
                    )
                else:
                    lines.append(OK + " Mesh is manifold (watertight).")

                # 3. Loose vertices
                loose_verts = [v for v in bm.verts if not v.link_edges]
                if loose_verts:
                    lines.append(
                        WARN + " " + str(len(loose_verts))
                        + " loose vertex/vertices (not connected to any edge)."
                    )
                else:
                    lines.append(OK + " No loose vertices.")

                # 4. Inverted-normals heuristic: count faces whose normal
                # points toward the mesh centroid instead of away from it.
                if bm.faces:
                    centroid = Vector((0.0, 0.0, 0.0))
                    for f in bm.faces:
                        centroid += f.calc_center_median()
                    centroid /= len(bm.faces)

                    inward = 0
                    for f in bm.faces:
                        outward = f.calc_center_median() - centroid
                        if outward.length_squared == 0:
                            continue
                        if outward.normalized().dot(f.normal) < 0:
                            inward += 1
                    ratio = inward / max(len(bm.faces), 1)
                    if ratio > 0.5:
                        lines.append(
                            BAD + " " + str(inward) + "/" + str(len(bm.faces))
                            + " faces (" + "{{:.0f}}".format(ratio * 100)
                            + "%) appear to have inverted normals."
                        )
                    elif ratio > 0.1:
                        lines.append(
                            WARN + " " + str(inward) + "/" + str(len(bm.faces))
                            + " faces (" + "{{:.0f}}".format(ratio * 100)
                            + "%) may have inverted normals."
                        )
                    else:
                        lines.append(OK + " Normals look consistent.")
                else:
                    lines.append(BAD + " Mesh has no faces.")

                bm.free()
                eval_obj.to_mesh_clear()

            # 5. Dimensions in mm
            scene = bpy.context.scene
            unit_scale = scene.unit_settings.scale_length
            dims_mm = [d * unit_scale * 1000 for d in obj.dimensions]
            lines.append(
                "      Dimensions: X={{:.2f}}mm Y={{:.2f}}mm Z={{:.2f}}mm".format(
                    dims_mm[0], dims_mm[1], dims_mm[2]
                )
            )
            if min(dims_mm) <= 0:
                lines.append(BAD + " Object has zero size on at least one axis.")
            elif min(dims_mm) < 1.0:
                lines.append(
                    WARN + " Smallest dimension is < 1mm - may be too small to print."
                )
            elif max(dims_mm) > 400.0:
                lines.append(
                    WARN + " Largest dimension is > 400mm - won't fit most desktop printers."
                )
            else:
                lines.append(OK + " Dimensions are reasonable for desktop FDM.")

        print("\\n".join(lines))
    """
    try:
        result = _run_code(code)
    except (ConnectionError, RuntimeError) as exc:
        return f"Error: {exc}"
    return _extract_text_result(result)


@mcp.tool()
def add_print_base(
    object_name: str,
    thickness_mm: float = 1.5,
    margin_mm: float = 2.0,
) -> str:
    """Add a thin rectangular base under an object to improve bed adhesion.

    Useful when a part has a small footprint and tends to lift during
    printing. The base is a separate mesh object you can union later in
    your slicer (or in Blender with a boolean) if you want.

    Args:
        object_name: Object to put a base under. Its current XY footprint
            is used to size the base.
        thickness_mm: Base thickness in millimetres.
        margin_mm: How far the base extends past the object's footprint on
            each side, in millimetres.
    """
    code = f"""
        import bpy
        from mathutils import Vector

        name = {object_name!r}
        thickness_mm = {thickness_mm!r}
        margin_mm = {margin_mm!r}
        if name not in bpy.data.objects:
            raise ValueError("Object " + repr(name) + " not found in scene")
        obj = bpy.data.objects[name]
        scene = bpy.context.scene
        unit_scale = scene.unit_settings.scale_length
        # mm -> blender units
        to_bu = (1.0 / 1000.0) / unit_scale
        thickness_bu = thickness_mm * to_bu
        margin_bu = margin_mm * to_bu

        # World-space bounding box of the object.
        bbox_world = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        xs = [v.x for v in bbox_world]
        ys = [v.y for v in bbox_world]
        zs = [v.z for v in bbox_world]
        size_x = (max(xs) - min(xs)) + 2 * margin_bu
        size_y = (max(ys) - min(ys)) + 2 * margin_bu
        cx = (max(xs) + min(xs)) / 2
        cy = (max(ys) + min(ys)) / 2
        base_z_center = min(zs) - thickness_bu / 2

        bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, cy, base_z_center))
        base = bpy.context.active_object
        base.name = name + "_base"
        base.scale = (size_x, size_y, thickness_bu)
        # Bake scale into mesh data so dimensions read true.
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        print(
            "Added base " + repr(base.name) + " ("
            + "{{:.2f}} x {{:.2f}} x {{:.2f}} mm".format(
                size_x / to_bu, size_y / to_bu, thickness_mm
            )
            + ") under " + repr(name) + "."
        )
    """
    try:
        result = _run_code(code)
    except (ConnectionError, RuntimeError) as exc:
        return f"Error: {exc}"
    return _extract_text_result(result)


@mcp.tool()
def list_print_presets() -> str:
    """List recommended print settings for the supported printers.

    Currently profiles: Anycubic Kobra S1 Combo.
    """
    return dedent(
        """
        Anycubic Kobra S1 Combo
        =======================
        Build volume       : 220 x 220 x 250 mm
        Nozzle diameter    : 0.4 mm
        Layer heights      : 0.10 / 0.15 / 0.20 / 0.30 mm
        Max colors (AMS)   : 8
        Recommended wall   : >= 1.2 mm (3 walls at 0.4 mm)
        Min feature size   : 1.0 mm
        Bed surface        : PEI
        """
    ).strip()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main() -> None:
    """Console-script entry point used by ``uv run blender-print-studio``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    mcp.run()


if __name__ == "__main__":
    main()
