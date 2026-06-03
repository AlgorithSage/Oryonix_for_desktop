"""
WebSocket server — listens on 127.0.0.1:8765.
Tauri connects as the single client. Messages are JSON objects.

Inbound (Tauri → Python):
  {"type": "run_task",       "goal": str, "session_id": str}
  {"type": "approval_grant", "task_id": str}
  {"type": "approval_deny",  "task_id": str}
  {"type": "handback",       "task_id": str}
  {"type": "force_cloud",    "task_id": str}

Outbound (Python → Tauri):
  {"type": "state_change",  "state": str, "task_id": str}
  {"type": "step_update",   "step": int, "plan": str, "action": str, "task_id": str}
  {"type": "task_done",     "success": bool, "message": str, "task_id": str}
  {"type": "error",         "message": str}
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import websockets

logger = logging.getLogger(__name__)


class WebSocketServer:
    """asyncio WebSocket server bridging Tauri ↔ Python agent backend."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._client: Optional[Any] = None
        self._orchestrator: Optional[Any] = None
        self._approval_events: dict[str, asyncio.Event] = {}
        self._approval_granted: dict[str, bool] = {}

    def set_orchestrator(self, orchestrator: Any) -> None:
        self._orchestrator = orchestrator

    async def start(self) -> None:
        """Start the WebSocket server and block until process exit."""
        async with websockets.serve(self._handle_client, self.host, self.port):
            logger.info(f"[Oryonix] WebSocket server listening on ws://{self.host}:{self.port}")
            await asyncio.Future()  # run until cancelled / process exit

    async def send(self, message: dict[str, Any]) -> None:
        """Send a JSON message to the connected Tauri client. Silent no-op if not connected."""
        if self._client is None:
            return
        try:
            await self._client.send(json.dumps(message))
        except Exception as e:
            logger.warning(f"[Oryonix] WebSocket send failed: {e}")
            self._client = None

    async def wait_for_approval(self, task_id: str, timeout_seconds: int) -> bool:
        """
        Block until Tauri sends approval_grant or approval_deny.
        Returns True if granted, False if denied or timed out.
        """
        event = asyncio.Event()
        self._approval_events[task_id] = event
        self._approval_granted[task_id] = False
        try:
            await asyncio.wait_for(event.wait(), timeout=float(timeout_seconds))
        except asyncio.TimeoutError:
            logger.warning(f"[Oryonix] Approval timed out for task {task_id}")
            return False
        finally:
            self._approval_events.pop(task_id, None)
        return self._approval_granted.pop(task_id, False)

    async def _handle_client(self, websocket: Any) -> None:
        """Accept one Tauri connection and read messages until disconnect."""
        self._client = websocket
        logger.info("[Oryonix] Tauri UI connected")
        try:
            async for raw in websocket:
                await self._dispatch(raw)
        except Exception as e:
            logger.debug(f"[Oryonix] Client connection closed: {e}")
        finally:
            self._client = None
            logger.info("[Oryonix] Tauri UI disconnected")

    async def _dispatch(self, raw: str) -> None:
        """Parse an inbound JSON message and route it to the correct handler."""
        try:
            message: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            print(f"[WebSocket Server] Received non-JSON message: {raw!r}", flush=True)
            logger.error(f"[Oryonix] Received non-JSON message: {raw!r}")
            return

        msg_type = message.get("type", "")
        print(f"[WebSocket Server] Received msg_type: {msg_type} (raw: {raw})", flush=True)

        if msg_type == "run_task":
            goal = str(message.get("goal", ""))
            session_id = str(message.get("session_id", ""))
            if self._orchestrator is not None:
                print(f"[WebSocket Server] Dispatching run_task for goal='{goal}'", flush=True)
                task = asyncio.create_task(self._orchestrator.run(goal, session_id))
                if hasattr(self._orchestrator, "set_active_task"):
                    self._orchestrator.set_active_task(task)
            else:
                # Echo mode — Orchestrator not yet wired (active until Chunk 3)
                print("[WebSocket Server] Orchestrator is None, running echo response", flush=True)
                asyncio.create_task(self._echo_response(goal))

        elif msg_type == "pause_task":
            print("[WebSocket Server] Dispatching pause_task", flush=True)
            if self._orchestrator is not None and hasattr(self._orchestrator, "pause_task"):
                self._orchestrator.pause_task()

        elif msg_type == "resume_task":
            print("[WebSocket Server] Dispatching resume_task", flush=True)
            if self._orchestrator is not None and hasattr(self._orchestrator, "resume_task"):
                self._orchestrator.resume_task()

        elif msg_type == "kill_task":
            print("[WebSocket Server] Dispatching kill_task", flush=True)
            if self._orchestrator is not None and hasattr(self._orchestrator, "kill_task"):
                asyncio.create_task(self._orchestrator.kill_task())

        elif msg_type == "approval_grant":
            task_id = str(message.get("task_id", ""))
            print(f"[WebSocket Server] Dispatching approval_grant for task {task_id}", flush=True)
            if task_id in self._approval_events:
                self._approval_granted[task_id] = True
                self._approval_events[task_id].set()

        elif msg_type == "approval_deny":
            task_id = str(message.get("task_id", ""))
            print(f"[WebSocket Server] Dispatching approval_deny for task {task_id}", flush=True)
            if task_id in self._approval_events:
                self._approval_granted[task_id] = False
                self._approval_events[task_id].set()

        elif msg_type == "handback":
            task_id = str(message.get("task_id", ""))
            print(f"[WebSocket Server] Dispatching handback for task {task_id}", flush=True)
            if self._orchestrator is not None and hasattr(self._orchestrator, "handle_handback"):
                await self._orchestrator.handle_handback(task_id)

        elif msg_type == "force_cloud":
            print("[WebSocket Server] Dispatching force_cloud", flush=True)
            if self._orchestrator is not None and hasattr(self._orchestrator, "router"):
                self._orchestrator.router.force_cloud()

        else:
            print(f"[WebSocket Server] Unknown message type: {msg_type!r}", flush=True)
            logger.warning(f"[Oryonix] Unknown message type: {msg_type!r}")

    async def _echo_response(self, goal: str) -> None:
        """
        Temporary echo handler used while Orchestrator is not yet wired (Chunk 2).
        Sends realistic state transitions so the React UI can be fully tested.
        """
        await asyncio.sleep(0.15)
        await self.send({"type": "state_change", "state": "PLANNING", "task_id": "echo"})
        await asyncio.sleep(0.4)
        await self.send({"type": "state_change", "state": "EXECUTING", "task_id": "echo"})
        await asyncio.sleep(0.6)
        await self.send({
            "type": "task_done",
            "success": True,
            "message": f"[Backend online] Received: {goal}",
            "task_id": "echo",
        })
