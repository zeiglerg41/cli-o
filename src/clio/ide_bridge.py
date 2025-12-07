"""IDE Bridge - WebSocket client for connecting to IDE extensions."""
import json
import os
import asyncio
from pathlib import Path
from typing import Optional, Callable, Any
import websockets


class IDEBridge:
    """WebSocket client that connects to IDE extension bridge server."""

    def __init__(self):
        """Initialize IDE bridge."""
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        self.port: Optional[int] = None
        self.message_callback: Optional[Callable[[dict], Any]] = None

    def discover_port(self) -> Optional[int]:
        """Discover IDE bridge port from env var or lock file."""
        # Try environment variable first (for integrated terminals)
        env_port = os.getenv('CLIO_IDE_PORT')
        if env_port:
            try:
                return int(env_port)
            except ValueError:
                pass

        # Try lock file
        lock_path = Path.home() / '.clio' / 'ide' / 'bridge.json'
        if lock_path.exists():
            try:
                with open(lock_path, 'r') as f:
                    data = json.load(f)
                    return data.get('port')
            except Exception as e:
                print(f"[IDE Bridge] Failed to read lock file: {e}")

        return None

    async def connect(self) -> bool:
        """Connect to IDE bridge server."""
        self.port = self.discover_port()

        if not self.port:
            print("[IDE Bridge] No IDE found, falling back to file-based edits")
            return False

        try:
            uri = f"ws://127.0.0.1:{self.port}"
            print(f"[IDE Bridge] Connecting to {uri}...")

            self.ws = await websockets.connect(uri)
            self.connected = True

            # Send connect message
            await self.send({
                "type": "connect",
                "clientVersion": "0.1.0"
            })

            # Wait for connected response
            response = await self.ws.recv()
            data = json.loads(response)

            if data.get('type') == 'connected':
                print(f"[IDE Bridge] Connected to {data.get('ideName', 'IDE')}")
                return True

        except Exception as e:
            print(f"[IDE Bridge] Connection failed: {e}")
            self.connected = False
            self.ws = None

        return False

    async def send(self, message: dict) -> None:
        """Send message to IDE."""
        if not self.ws or not self.connected:
            return

        try:
            await self.ws.send(json.dumps(message))
        except Exception as e:
            print(f"[IDE Bridge] Failed to send message: {e}")
            self.connected = False

    async def open_diff(self, file_path: str, before: str, after: str, description: str = "") -> bool:
        """Show diff in IDE without applying."""
        if not self.connected:
            return False

        await self.send({
            "type": "openDiff",
            "file": str(Path(file_path).resolve()),
            "before": before,
            "after": after,
            "description": description
        })

        # Wait for response (diffAccepted or diffRejected)
        try:
            response = await asyncio.wait_for(self.ws.recv(), timeout=30.0)
            data = json.loads(response)

            if data.get('type') == 'diffAccepted':
                return True
            elif data.get('type') == 'diffRejected':
                return False

        except asyncio.TimeoutError:
            print("[IDE Bridge] Timeout waiting for diff response")

        return False

    async def propose_diff(self, file_path: str, edits: list, description: str = "") -> bool:
        """Propose diff with inline decorations and accept/reject buttons."""
        if not self.connected:
            return False

        await self.send({
            "type": "proposeDiff",
            "file": str(Path(file_path).resolve()),
            "edits": edits,
            "description": description
        })

        return True

    async def apply_diff(self, file_path: str, edits: list) -> bool:
        """Apply diff directly to IDE document (deprecated, use propose_diff)."""
        if not self.connected:
            return False

        await self.send({
            "type": "applyDiff",
            "file": str(Path(file_path).resolve()),
            "edits": edits
        })

        return True

    async def send_status(self, message: str, level: str = "info") -> None:
        """Send status update to IDE."""
        if not self.connected:
            return

        await self.send({
            "type": "status",
            "message": message,
            "level": level
        })

    async def close(self) -> None:
        """Close WebSocket connection."""
        if self.ws:
            await self.ws.close()
            self.ws = None
            self.connected = False
            print("[IDE Bridge] Disconnected")

    def is_connected(self) -> bool:
        """Check if connected to IDE."""
        return self.connected


# Singleton instance
_bridge_instance: Optional[IDEBridge] = None


def get_bridge() -> IDEBridge:
    """Get or create the global IDE bridge instance."""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = IDEBridge()
    return _bridge_instance
