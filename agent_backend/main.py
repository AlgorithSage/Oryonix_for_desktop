"""
Oryonix Agent Backend — entry point.
Adds Agent-S3 to sys.path, then starts the WebSocket server with fully injected Orchestrator.
"""
import asyncio
import subprocess
import sys
from pathlib import Path


def _free_port(port: int) -> None:
    """Kill any process holding the given TCP port before we try to bind it.
    Silently does nothing if the port is already free or the command is unavailable.
    """
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                pid = parts[-1]
                if pid.isdigit() and int(pid) != 0:
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   capture_output=True, timeout=5)
    except Exception:
        pass  # best-effort — if it fails, websockets will surface the OSError normally


_free_port(8765)

# Make Agent-S3 importable as `gui_agents.s3.*`
_AGENT_S_PATH = Path(__file__).parent.parent / "Agent-S"
if str(_AGENT_S_PATH) not in sys.path:
    sys.path.insert(0, str(_AGENT_S_PATH))

from core.config import get_config
from core.task_manager import TaskManager
from llm.router import LLMRouter
from sandbox.sandbox_aci import SandboxACI
from verifier.verifier import Verifier
from context.compressor import ContextCompressor
from memory.memory_layer import MemoryLayer
from recipe.recipe_engine import RecipeEngine
from audit.audit_logger import AuditLogger
from core.orchestrator import Orchestrator
from bridge.ws_server import WebSocketServer


async def main() -> None:
    config = get_config()
    
    # 1. Initialize core infrastructure dependencies
    task_manager = TaskManager(config)
    router = LLMRouter(config)
    verifier = Verifier(config)
    compressor = ContextCompressor()
    
    # 2. Resilient memory SQLite layer setup
    memory = MemoryLayer(config)
    await memory.init()
    
    # 3. Sandbox instantiation with memory dependency
    # Uses Sandbox.ephemeral(Image.linux()) — correct for both the cua mock and (when cua is
    # installed) the real SDK factory.  The mock returns a SandboxACI-compatible object directly;
    # the real cua SDK's async-context-manager path requires a future refactor to async-with.
    import sandbox.sandbox_aci as s_aci
    sandbox_backend = s_aci.Sandbox.ephemeral(s_aci.Image.linux())
    sandbox = SandboxACI(sandbox_backend, config, memory)
    
    # 4. Recipe matching fast-path engine
    recipe_engine = RecipeEngine()
    recipes_path = Path(__file__).parent / "recipes.json"
    if recipes_path.exists():
        recipe_engine.load_recipes(str(recipes_path))
    
    # 5. Hash-chained audit logger
    audit = AuditLogger(config)
    
    # 5. WebSocket bridge server
    server = WebSocketServer(host=config.ws_host, port=config.ws_port)
    
    # 6. Driving E2E Orchestrator
    orchestrator = Orchestrator(
        config=config,
        task_manager=task_manager,
        router=router,
        sandbox=sandbox,
        verifier=verifier,
        compressor=compressor,
        memory=memory,
        recipe_engine=recipe_engine,
        audit=audit,
        ws_server=server
    )
    
    server.set_orchestrator(orchestrator)
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
