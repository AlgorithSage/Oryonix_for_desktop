# Oryonix — Project Context

**What we are building:** A desktop Computer Use Agent (CUA) application. Natural-language goal in the chat UI → agent autonomously controls the computer (clicks, types, reads screen) to achieve it.

**Stack:**
- Frontend: React + TypeScript + Vite + Tailwind CSS (Tauri shell)
- Agent backend: Python (`agent_backend/`) on port 8765 (WebSocket)
- Agent core: Agent-S3 (Python, cloned at `Agent-S/`) — added to sys.path at runtime
- Sandbox: pyautogui host-mode (real Windows desktop, no VM for now)

---

## Current State (2026-05-31) — FULLY WIRED AND RUNNING

### What is built and working:
- Full agent backend wired end-to-end: Orchestrator → Brain → Actor → Verifier → WebSocket
- Chat UI fully connected to Python WebSocket backend via `useAgentBridge.ts`
- Chat queries (conversational) use Groq API directly from the frontend (`useChatStore.ts`)
- Task execution uses the Python backend + Groq APIs

### Model Stack (all Groq, no local models required, no Claude):
| Role | Model | When |
|---|---|---|
| Brain (sub-goal planner) | Groq Maverick (`llama-4-maverick-17b-128e-instruct`) | Once per sub-goal |
| Actor (step executor) | ShowUI-2B local → Groq Scout fallback | Every step |
| Cloud escalation | Groq Maverick | Actor fails 2× |
| Verifier Tier 4 | Groq Scout (`llama-4-scout-17b-16e-instruct`) | Every step |
| Frontend chat | Groq Scout | Every chat message |

### API Keys (in `agent_backend/.env` and root `.env`):
- `GROQ_API_KEY` — required, get free at console.groq.com
- `ANTHROPIC_API_KEY` — present but unused (all Claude replaced with Groq)
- `VITE_GROQ_API_KEY` — root `.env`, used by frontend chat

### Key config flags in `agent_backend/.env`:
- `AIR_GAP=false` — allows cloud API calls
- `BRAIN_ACTOR_MODE=true` — Brain (Maverick) decomposes goal, Actor (Scout) executes

---

## Architecture Layers (all built)

1. **WebSocket bridge** — `bridge/ws_server.py`, port 8765
2. **Task Manager** — `core/task_manager.py`, state machine: IDLE → PLANNING → EXECUTING → VERIFYING → SUCCEEDED/FAILED
3. **Orchestrator** — `core/orchestrator.py`, drives full loop; has Brain-Actor separation, ShowUI integration, escalation
4. **SandboxACI** — `sandbox/sandbox_aci.py`, pyautogui host-mode (real Windows desktop)
5. **LLM Router** — `llm/router.py`, tier routing (local/cloud); mostly bypassed now that Brain/Actor call Groq directly
6. **ShowUI Agent** — `llm/showui_agent.py`, Qwen2.5-VL-2B fine-tuned, NF4 4-bit quant, lazy-loaded
7. **ActionNormalizer** — `llm/action_normalizer.py`, families: claude_gpt / fara / opencua / showui / groq
8. **4-tier Verifier** — `verifier/verifier.py`, T1 rules → T2 accessibility → T3 Qwen (skipped) → T4 Groq Scout
9. **Memory Layer** — `memory/memory_layer.py`, SQLite L0 raw trace + L1 distilled
10. **Audit Logger** — `audit/audit_logger.py`, hash-chained append-only
11. **Recipe Engine** — `recipe/recipe_engine.py`, perceptual hash + OCR fast path
12. **Context Compressor** — `context/compressor.py`, Mermaid graph + history compression
13. **Config** — `core/config.py`, all env vars wired including Groq fields

---

## Frontend Split

| User action | Code path | Backend needed |
|---|---|---|
| Chat message (conversational) | `useChatStore.sendMessage()` → Groq API direct | No |
| Task execution (CUA) | `useAgentBridge.sendTask()` → WebSocket → Python | Yes (`python main.py`) |

---

## Known Issues / Not Yet Built
- ShowUI-2B requires local GPU (4060 Ti 8GB) + transformers/bitsandbytes installed
- Without GPU: falls back to Groq Scout as Actor (fully wired, works via `GROQ_API_KEY`)
- UI-TARS coordinate verification (`verifier.verify_coordinate()`) is wired but needs UI-TARS server running on `LOCAL_VLLM_URL`
- Co-presence VNC streaming not built yet (placeholder)
- No E2E automated tests

---

## To Run

```bash
# Terminal 1 — backend
cd agent_backend && python main.py

# Terminal 2 — frontend
npm run tauri dev
```
