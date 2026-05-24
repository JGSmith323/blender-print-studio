# Setup Guide (WSL2 + Windows Blender)

This guide walks you end-to-end from a clean WSL2 box to a working
Claude → Blender pipeline. Everything below assumes Blender is installed
on the **Windows** side and you run Claude Code / MCP servers from **WSL2**.

If you're on native Linux or macOS, skip the WSL2-specific notes — the rest
of the steps are identical.

---

## 1. Install Blender (Windows)

1. Download Blender 4.x from <https://www.blender.org/download/>.
2. Install the default way. Open it once to make sure it launches.

## 2. Clone this repo (WSL2)

```bash
cd ~/Projects
git clone https://github.com/JGSmith323/blender-print-studio.git
cd blender-print-studio
./setup.sh
```

`setup.sh` does three things:

1. Installs [`uv`](https://github.com/astral-sh/uv) if it isn't already.
2. Runs `uv sync`, which builds a `.venv/` and installs the pinned
   dependencies (`mcp`, `httpx`).
3. Prints the next steps.

## 3. Install the Blender addon

The addon lives at `addon/addon.py` in this repo. Because Blender is on
Windows but the file is in WSL2, you need to get the file to the Windows
side. Easiest path:

```bash
# From WSL2, copy the addon somewhere Blender can see it.
cp addon/addon.py /mnt/c/Users/$USER/Downloads/blender-print-studio-addon.py
```

(Replace `$USER` with your Windows username if WSL doesn't match — check
`ls /mnt/c/Users/`.)

Then in Blender:

1. **Edit → Preferences → Add-ons → Install…**
2. Browse to `C:\Users\<you>\Downloads\blender-print-studio-addon.py`.
3. Click **Install Add-on**.
4. Tick the checkbox next to **Interface: Blender MCP**.
5. Close Preferences.
6. In the 3D viewport, press **N** to open the sidebar.
7. Find the **BlenderMCP** tab on the right edge of the viewport.
8. Click **Start MCP Server**.

You should now see a confirmation that the server is listening on port
9876.

> **Firewall note.** Windows Defender may pop up the first time the addon
> binds the socket. Allow it on Private networks; you don't need Public.

## 4. Wire up Claude Code

Open `~/.claude/settings.json` (or create it). Add the
`blender-print-studio` entry under `mcpServers`. If the file is empty:

```json
{
  "mcpServers": {
    "blender-print-studio": {
      "command": "uv",
      "args": ["run", "blender-print-studio"],
      "env": {
        "BLENDER_HOST": "localhost",
        "BLENDER_PORT": "9876"
      },
      "cwd": "/home/<you>/Projects/blender-print-studio"
    }
  }
}
```

If it already has other servers, just merge the inner object in.

Restart Claude Code (`claude` from your terminal).

## 5. Smoke test

In Claude Code, ask:

> *Take a viewport screenshot.*

Claude should call `get_viewport_screenshot` and return the image. If you
get an error about connecting to Blender, double-check that:

- Blender is running.
- The **BlenderMCP** sidebar panel says the server is started.
- Nothing else is listening on port 9876 (`netstat -ano | findstr 9876` on
  Windows).

## 6. Troubleshooting

**`ConnectionRefusedError` when calling tools.**
Blender isn't listening. Open Blender → BlenderMCP panel →
**Start MCP Server**.

**`uv: command not found` when Claude starts the server.**
Add `~/.local/bin` to your PATH or set `command` to the absolute path
(`/home/<you>/.local/bin/uv`).

**Tools time out.**
The default socket timeout is 180 s — generous, but renders can be slower.
Bump `BLENDER_HOST` / your blend file complexity, or rework the script
into smaller chunks.

**STL exports go somewhere unexpected.**
`export_stl` takes an **absolute** path. On WSL2, remember that `/mnt/c/...`
is your Windows C: drive, while `/home/...` is the WSL2 filesystem.

**Newer Blender complains about `bpy.ops.wm.stl_export`.**
That operator was added in Blender 4.0. On 3.x, edit the call inside
`export_stl` (or send Claude a one-off `execute_blender_code` with
`bpy.ops.export_mesh.stl(...)` instead).
