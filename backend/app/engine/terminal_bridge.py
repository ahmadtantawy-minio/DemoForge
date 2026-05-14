"""
WebSocket ↔ docker exec bridge with PTY via 'script' wrapper.
Each WebSocket connection spawns a docker exec session with a PTY allocated
by the 'script' command, giving full interactive shell behavior.
"""

from __future__ import annotations

import asyncio
import logging
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


async def terminal_session(websocket: WebSocket, container_name: str, shell: str = "/bin/sh"):
    """
    Open an interactive shell inside a container and relay I/O over WebSocket.
    Uses 'script' to allocate a PTY for docker exec.
    """
    await websocket.accept()

    # Use 'script' to allocate a PTY. This gives us echo, line editing, etc.
    # GNU script: -q (quiet), -c (command), /dev/null (no log file)
    proc = await asyncio.create_subprocess_exec(
        "script", "-q", "-c",
        f"docker exec -i {container_name} {shell}",
        "/dev/null",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    # Set up a nice prompt
    prompt_cmd = b'export PS1="\\[\\e[32m\\]\\u@\\h\\[\\e[0m\\]:\\[\\e[34m\\]\\w\\[\\e[0m\\]\\$ "\n'
    if proc.stdin:
        proc.stdin.write(prompt_cmd)
        await proc.stdin.drain()

    async def read_stdout():
        """Read from process stdout and send to WebSocket."""
        try:
            while True:
                data = await proc.stdout.read(4096)
                if not data:
                    break
                await websocket.send_bytes(data)
        except (WebSocketDisconnect, ConnectionError):
            pass
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

    async def read_websocket():
        """Read from WebSocket and write to process stdin."""
        try:
            while True:
                data = await websocket.receive_bytes()
                if proc.stdin and not proc.stdin.is_closing():
                    proc.stdin.write(data)
                    await proc.stdin.drain()
        except (WebSocketDisconnect, ConnectionError):
            pass
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

    try:
        await asyncio.gather(read_stdout(), read_websocket())
    except Exception:
        pass
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        try:
            await websocket.close()
        except Exception:
            pass
