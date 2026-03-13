"""
WebSocket ↔ docker exec bridge.
Each WebSocket connection spawns a `docker exec -it <container> <shell>` subprocess.
stdin/stdout/stderr are relayed bidirectionally.
"""
import asyncio
import docker
from fastapi import WebSocket, WebSocketDisconnect

docker_client = docker.from_env()

async def terminal_session(websocket: WebSocket, container_name: str, shell: str = "/bin/sh"):
    """
    Open an interactive shell inside a container and relay I/O over WebSocket.
    Uses asyncio subprocess with docker exec for true PTY support.
    """
    await websocket.accept()

    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", "-i", container_name, shell,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
    )

    async def read_stdout():
        """Read from container stdout and send to WebSocket."""
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
                proc.kill()

    async def read_websocket():
        """Read from WebSocket and write to container stdin."""
        try:
            while True:
                data = await websocket.receive_bytes()
                if proc.stdin:
                    proc.stdin.write(data)
                    await proc.stdin.drain()
        except (WebSocketDisconnect, ConnectionError):
            pass
        finally:
            if proc.returncode is None:
                proc.kill()

    # Run both directions concurrently
    try:
        await asyncio.gather(read_stdout(), read_websocket())
    except Exception:
        pass
    finally:
        if proc.returncode is None:
            proc.kill()
        try:
            await websocket.close()
        except Exception:
            pass
