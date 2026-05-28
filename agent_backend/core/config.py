"""
Deployment configuration for Oryonix.
Loaded once at startup from environment variables or a .env file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # ── Deployment mode ───────────────────────────────────────────────────────
    air_gap: bool = False
    
    # ── Brain-Actor Mode (Phase P2) ──────────────────────────────────────────
    brain_actor_mode: bool = True

    # ── LLM endpoints ─────────────────────────────────────────────────────────
    local_vllm_url: str = "http://localhost:8000/v1"
    claude_api_key: str = ""
    openai_api_key: str = ""

    # ── Local model names ────────────────────────────────────────────────────
    fara_model_id: str = "microsoft/Fara-7B"
    opencua_model_id: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    uitars_model_id: str = "ByteDance/UI-TARS-1.5-7B"
    qwen_vlm_model_id: str = "Qwen/Qwen2-VL-2B-Instruct"

    # ── ShowUI — primary local VLA (vision-language-action) model ────────────
    # HuggingFace model ID or absolute local path to downloaded weights.
    # Set SHOWUI_MODEL_PATH= in .env to use a local copy.
    showui_model_path: str = "showlab/ShowUI-2B"

    # ── Separate VLM endpoint for Verifier Tier 3 ────────────────────────────
    # Leave empty to skip Tier 3 and go straight to Claude API (Tier 4).
    # Set to e.g. http://localhost:8001/v1 when Qwen2-VL-2B runs on a separate port.
    qwen_vlm_url: str = ""

    # ── Sandbox ───────────────────────────────────────────────────────────────
    sandbox_backend: Literal["local_qemu", "cua_cloud"] = "local_qemu"

    # ── Token budgets (per task tier) ─────────────────────────────────────────
    local_task_token_budget: int = 4_096
    cloud_task_token_budget: int = 16_384
    escalated_task_token_budget: int = 32_768

    # ── Approval timeout ─────────────────────────────────────────────────────
    approval_timeout_seconds: int = 300

    # ── WebSocket server ─────────────────────────────────────────────────────
    ws_host: str = "127.0.0.1"
    ws_port: int = 8765

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            air_gap=os.getenv("AIR_GAP", "false").lower() == "true",
            brain_actor_mode=os.getenv("BRAIN_ACTOR_MODE", "true").lower() == "true",
            local_vllm_url=os.getenv("LOCAL_VLLM_URL", "http://localhost:8000/v1"),
            claude_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            fara_model_id=os.getenv("FARA_MODEL_ID", "microsoft/Fara-7B"),
            opencua_model_id=os.getenv("OPENCUA_MODEL_ID", "Qwen/Qwen2.5-VL-7B-Instruct"),
            uitars_model_id=os.getenv("UITARS_MODEL_ID", "ByteDance/UI-TARS-1.5-7B"),
            qwen_vlm_model_id=os.getenv("QWEN_VLM_MODEL_ID", "Qwen/Qwen2-VL-2B-Instruct"),
            showui_model_path=os.getenv("SHOWUI_MODEL_PATH", "showlab/ShowUI-2B"),
            qwen_vlm_url=os.getenv("QWEN_VLM_URL", ""),
            sandbox_backend=os.getenv("SANDBOX_BACKEND", "local_qemu"),  # type: ignore[arg-type]
            local_task_token_budget=int(os.getenv("LOCAL_TASK_TOKEN_BUDGET", "500000")),
            cloud_task_token_budget=int(os.getenv("CLOUD_TASK_TOKEN_BUDGET", "500000")),
            escalated_task_token_budget=int(os.getenv("ESCALATED_TASK_TOKEN_BUDGET", "500000")),
            approval_timeout_seconds=int(os.getenv("APPROVAL_TIMEOUT_SECONDS", "300")),
            ws_host=os.getenv("WS_HOST", "127.0.0.1"),
            ws_port=int(os.getenv("WS_PORT", "8765")),
        )


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config
