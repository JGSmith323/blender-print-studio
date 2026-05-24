# blender-print-studio

A [Model Context Protocol](https://modelcontextprotocol.io) server that lets
Claude drive Blender for 3D-printing workflows. It extends
[`ahujasid/blender-mcp`](https://github.com/ahujasid/blender-mcp) with a
suite of print-focused tools: dimension queries in millimetres, fit-to-bed
scaling, origin/bed alignment, modifier baking, printability checks,
bed-adhesion bases, and one-shot STL export.

Tuned out of the box for the **Anycubic Kobra S1 Combo** (220 x 220 x 250 mm,
0.4 mm nozzle, AMS-style multi-material).

## Attribution

The Blender addon shipped under [`addon/addon.py`](addon/addon.py) is a
verbatim copy of [`ahujasid/blender-mcp`](https://github.com/ahujasid/blender-mcp)
(MIT License, © 2025 Siddharth Ahuja). Everything in `src/blender_print_studio/`
is original work and licensed MIT as well. See [LICENSE](LICENSE).

## Architecture

```
+---------------------+         TCP :9876         +---------------------------+
|  Claude  (LLM)      | <---------------------->  |  Blender + blender-mcp     |
|                     |   JSON {type, params}     |  addon (TCP server)        |
|   |  MCP stdio      |                            |                            |
|   v                 |                            |   - get_scene_info         |
|  blender-print-     |                            |   - get_object_info        |
|  studio  (this pkg) |                            |   - get_viewport_screenshot|
|                     |                            |   - execute_code           |
|  - core tools       |                            +---------------------------+
|  - print tools      |
+---------------------+
```

On a WSL2 box the MCP server runs in Linux and Blender runs on Windows.
That works out of the box because WSL2 forwards `localhost` to the Windows
host: the addon listens on `127.0.0.1:9876` inside Windows and we connect to
`localhost:9876` from WSL2.

## Prerequisites

- **Blender 3.0+** (4.x recommended — `wm.stl_export` is the modern operator)
- **Python 3.10+**
- **[`uv`](https://github.com/astral-sh/uv)** — installed automatically by
  `setup.sh` if missing
- (Optional) **Claude Code** or **Claude Desktop** for the LLM side

## Installation

```bash
git clone https://github.com/JGSmith323/blender-print-studio.git
cd blender-print-studio
./setup.sh
```

`setup.sh` will install `uv`, then run `uv sync` to create a `.venv` with
the right dependencies pinned by `uv.lock`.

### 1. Install the Blender addon

1. Open Blender.
2. **Edit → Preferences → Add-ons → Install…**
3. Pick `addon/addon.py` from this repo and click **Install Add-on**.
4. Enable the **Interface: Blender MCP** checkbox.
5. In the 3D viewport, press **N** to open the sidebar and find the
   **BlenderMCP** panel.
6. Click **Start MCP Server**.

You should now see "MCP server running on port 9876" in Blender's status.

### 2. Wire the MCP server into Claude Code

Merge [`config/claude_code_mcp.json`](config/claude_code_mcp.json) into
`~/.claude/settings.json`. The contents you want under `mcpServers`:

```json
{
  "mcpServers": {
    "blender-print-studio": {
      "command": "uv",
      "args": ["run", "blender-print-studio"],
      "env": {
        "BLENDER_HOST": "localhost",
        "BLENDER_PORT": "9876"
      }
    }
  }
}
```

If you already have other servers in `~/.claude/settings.json`, just add the
`"blender-print-studio"` entry under your existing `mcpServers` object — do
not overwrite the whole file.

You may also need to set the server's working directory to the cloned repo
so `uv run` picks up the local `pyproject.toml`. Either run Claude Code from
the repo root, or add `"cwd": "/path/to/blender-print-studio"` to the server
config (Claude Code supports this).

Restart Claude Code; you should see the **blender-print-studio** tools show
up in the MCP picker.

### 3. Sanity check

Ask Claude: *"Take a viewport screenshot."* If Claude returns an image of
your current scene, you're wired up.

## Tools

### Core (thin wrappers over the upstream addon)

| Tool | What it does |
|------|-------------|
| `get_scene_info` | Summary of objects, materials, and the frame range. |
| `get_object_info(object_name)` | Transform, mesh stats, materials for one object. |
| `get_viewport_screenshot(max_size=1024)` | PNG of the active viewport, returned inline so Claude can see it. |
| `execute_blender_code(code)` | Run arbitrary Python in Blender. Escape hatch. |

### 3D-print workflow

| Tool | What it does |
|------|-------------|
| `export_stl(filepath, object_name=None, ascii_format=False)` | Export the scene or one object to STL. |
| `get_dimensions_mm(object_name)` | Bounding-box dimensions in millimetres, honouring scene unit scale. |
| `scale_to_dimensions(object_name, x_mm=None, y_mm=None, z_mm=None)` | Uniformly scale so a chosen axis matches a target size in mm. |
| `scale_to_fit_printer(object_name, printer="kobra_s1_combo", margin_mm=5.0)` | Uniformly scale (down only) to fit the printer's build volume minus a margin. |
| `set_print_origin(object_name)` | Origin → bottom-centre, object placed on Z=0 (the bed). |
| `apply_all_modifiers(object_name)` | Bake the modifier stack for a clean STL. |
| `check_printability(object_name)` | Manifold / loose verts / inverted normals / dimensions report. |
| `add_print_base(object_name, thickness_mm=1.5, margin_mm=2.0)` | Add a thin rectangular base under the object for bed adhesion. |
| `list_print_presets()` | Printer profile (Kobra S1 Combo). |

Full reference with examples: [docs/tools-reference.md](docs/tools-reference.md).

## Kobra S1 Combo profile

| Setting | Value |
|---------|-------|
| Build volume | 220 x 220 x 250 mm |
| Nozzle | 0.4 mm |
| Layer heights | 0.10 / 0.15 / 0.20 / 0.30 mm |
| Max colours (AMS) | 8 |
| Recommended wall thickness | ≥ 1.2 mm (3 walls @ 0.4 mm) |
| Min feature size | 1.0 mm |
| Bed surface | PEI |

## Example session

```
You: Open the file at C:\models\widget.blend and tell me what's in it.
Claude: (calls get_scene_info)
        One mesh named "Widget", 12,348 tris, no materials, frame 1-250.

You: Is it print-ready for my Kobra S1?
Claude: (calls check_printability("Widget"))
        [OK]  Object is a mesh.
        [OK]  Mesh is manifold.
        [OK]  No loose vertices.
        [OK]  Normals look consistent.
              Dimensions: X=312.40mm Y=180.20mm Z=98.50mm
        [WARN] Largest dimension is > 220mm — won't fit your bed.

You: Scale it to fit with 5mm margin.
Claude: (calls scale_to_fit_printer("Widget"))
        Scaled "Widget" by 0.6722 to fit kobra_s1_combo (220 x 220 x 250 mm,
        margin 5mm). New dimensions: X=209.99mm Y=121.13mm Z=66.21mm.

You: Drop it on the bed, apply modifiers, add a 1.5mm base, and export.
Claude: (calls set_print_origin, apply_all_modifiers, add_print_base, export_stl)
        Exported to /mnt/c/Users/me/Downloads/widget.stl
```

## Development

```bash
uv sync                # install/lock deps
uv run blender-print-studio   # run the server (stdio)
```

The MCP server talks JSON-RPC on stdio — running it bare just blocks waiting
for a client. Drive it from Claude Code, or use the
[`mcp` CLI inspector](https://github.com/modelcontextprotocol/inspector):

```bash
uvx @modelcontextprotocol/inspector uv run blender-print-studio
```

## License

MIT. See [LICENSE](LICENSE).

The bundled `addon/addon.py` is © 2025 Siddharth Ahuja, also MIT.
