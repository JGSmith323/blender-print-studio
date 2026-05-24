#!/usr/bin/env bash
set -euo pipefail

echo "=== blender-print-studio setup ==="

# Check uv
if ! command -v uv &>/dev/null; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  source "$HOME/.local/bin/env"
fi

echo "Installing Python dependencies..."
uv sync

echo ""
echo "✅ MCP server ready."
echo ""
echo "Next steps:"
echo "  1. Install the Blender addon:"
echo "     Blender → Edit → Preferences → Add-ons → Install → select addon/addon.py"
echo "     Enable 'Interface: Blender MCP' and click 'Start MCP Server' in the 3D View sidebar"
echo ""
echo "  2. Add the MCP server to Claude Code:"
echo "     Merge config/claude_code_mcp.json into ~/.claude/settings.json"
echo "     (see README.md for exact instructions)"
echo ""
echo "  3. In Claude Code, ask: 'Take a viewport screenshot' to verify the connection"
