"""Socket connection to the Blender MCP addon.

The Blender addon (ahujasid/blender-mcp) opens a TCP server on port 9876.
Each command is a JSON object of the form ``{"type": ..., "params": {...}}``
and the response is a JSON object with ``{"status": "success"|"error",
"result": {...}, "message": "..."}``.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from typing import Any, Optional

logger = logging.getLogger(__name__)


class BlenderConnection:
    """A persistent TCP connection to a running Blender MCP server."""

    def __init__(self, host: str = "localhost", port: int = 9876) -> None:
        # Allow environment overrides so the same package works from WSL2,
        # a container, or a remote host.
        self.host: str = os.environ.get("BLENDER_HOST", host)
        try:
            self.port: int = int(os.environ.get("BLENDER_PORT", str(port)))
        except ValueError:
            self.port = port
        self.sock: Optional[socket.socket] = None

    # ------------------------------------------------------------------ #
    # Connection management
    # ------------------------------------------------------------------ #
    def connect(self) -> None:
        """Open the TCP socket. Raises ConnectionError on failure."""
        if self.sock is not None:
            return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Generous timeout — some Blender ops (renders, exports) can be slow.
            s.settimeout(180.0)
            s.connect((self.host, self.port))
            self.sock = s
            logger.info("Connected to Blender at %s:%s", self.host, self.port)
        except (socket.error, OSError) as exc:
            self.sock = None
            raise ConnectionError(
                f"Could not connect to Blender at {self.host}:{self.port}. "
                f"Make sure Blender is running, the 'Blender MCP' addon is "
                f"enabled, and you clicked 'Start MCP Server' in the 3D "
                f"viewport sidebar (N-panel → BlenderMCP). Original error: {exc}"
            ) from exc

    def disconnect(self) -> None:
        """Close the socket if open."""
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            finally:
                self.sock = None
                logger.info("Disconnected from Blender")

    # ------------------------------------------------------------------ #
    # Wire protocol
    # ------------------------------------------------------------------ #
    def _receive_full_response(self, sock: socket.socket, buffer_size: int = 8192) -> bytes:
        """Read from the socket in 8KB chunks until we have a complete JSON document."""
        chunks: list[bytes] = []
        while True:
            try:
                chunk = sock.recv(buffer_size)
            except socket.timeout as exc:
                raise TimeoutError(
                    "Timed out waiting for a response from Blender."
                ) from exc
            if not chunk:
                # Socket closed before we got valid JSON.
                if chunks:
                    break
                raise ConnectionError(
                    "Blender closed the connection before sending a response."
                )
            chunks.append(chunk)
            # Try to parse what we have so far; if it parses, we're done.
            try:
                data = b"".join(chunks)
                json.loads(data.decode("utf-8"))
                return data
            except json.JSONDecodeError:
                # Not done yet — keep reading.
                continue
        # If we fell out of the loop, try one final parse.
        data = b"".join(chunks)
        json.loads(data.decode("utf-8"))  # raises if still invalid
        return data

    def send_command(
        self, command_type: str, params: Optional[dict[str, Any]] = None
    ) -> Any:
        """Send a command and return the ``result`` field of the response.

        Raises ``RuntimeError`` if the Blender side reports an error.
        """
        if self.sock is None:
            self.connect()
        assert self.sock is not None

        payload = {"type": command_type, "params": params or {}}
        try:
            self.sock.sendall(json.dumps(payload).encode("utf-8"))
            raw = self._receive_full_response(self.sock)
        except (socket.error, OSError, TimeoutError, ConnectionError) as exc:
            # Drop the broken socket so the next call reconnects.
            self.disconnect()
            raise ConnectionError(
                f"Lost connection to Blender while sending '{command_type}': {exc}"
            ) from exc

        try:
            response = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Blender returned invalid JSON: {raw[:200]!r}"
            ) from exc

        status = response.get("status", "error")
        if status == "success":
            # The addon returns the payload under "result"; fall back to the
            # whole response if a tool doesn't follow that convention.
            return response.get("result", response)

        message = response.get("message") or response.get("error") or "Unknown error"
        raise RuntimeError(f"Blender error ({command_type}): {message}")


# ---------------------------------------------------------------------- #
# Singleton helper
# ---------------------------------------------------------------------- #
_connection: Optional[BlenderConnection] = None


def get_connection() -> BlenderConnection:
    """Return a lazily-created, auto-reconnecting connection singleton."""
    global _connection
    if _connection is None:
        _connection = BlenderConnection()
    if _connection.sock is None:
        try:
            _connection.connect()
        except ConnectionError:
            # Surface the error to the caller — they decide how to report it.
            raise
    return _connection
