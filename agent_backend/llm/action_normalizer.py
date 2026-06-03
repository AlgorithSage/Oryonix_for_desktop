"""
Action Normalizer — unifies heterogeneous LLM output formats into one Action object.

Claude / GPT-5 output  →  ```python code block```  →  Action
Fara-7B output         →  JSON dict                →  Action
OpenCUA-7B output      →  JSON dict                →  Action

SandboxACI always receives a unified Action — it never sees raw LLM strings.
This is the bridge between the two model families (Gap 4).
"""
from __future__ import annotations

import ast
import json
import re
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

# Configure logger
logger = logging.getLogger("desktopenv.agent")

@dataclass
class Action:
    type: str                                     # "click" | "type" | "scroll" | "hotkey" |
                                                  # "open" | "switch_applications" |
                                                  # "drag_and_drop" | "done" | "fail" | "wait" |
                                                  # "save_to_knowledge" | "call_code_agent" | "hold_and_press" | "highlight_text_span"
    target_description: Optional[str] = None      # natural-language ref (Claude/GPT path)
    element_id: Optional[str] = None              # explicit element id (Fara/OpenCUA path)
    params: dict[str, Any] = field(default_factory=dict)
    is_stateful: bool = False                     # True → action mutates persistent state


class ActionNormalizer:
    """Parses a raw LLM output string into a unified Action object."""

    def normalize(self, raw_output: str, model_family: str) -> Action:
        """
        model_family: "claude_gpt" | "fara" | "opencua" | "showui" | "groq"
        Raises ValueError if the output cannot be parsed.
        """
        raw_output = raw_output.strip()
        if model_family == "claude_gpt":
            action = self._parse_claude_gpt(raw_output)
        elif model_family in ("fara", "opencua", "groq"):
            action = self._parse_local_json(raw_output)
        elif model_family == "showui":
            action = self._parse_showui(raw_output)
        else:
            raise ValueError(f"Unknown model family: {model_family}")

        if action:
            action.is_stateful = self._is_stateful(action)
        return action

    def _is_stateful(self, action: Action) -> bool:
        """Determine if an action is stateful / risk-heavy and requires human-in-the-loop approval."""
        if action.type in ("open", "call_code_agent"):
            return True
            
        desc = (action.target_description or action.element_id or "").lower()
        stateful_keywords = {"delete", "destroy", "remove", "submit", "confirm", "pay", "buy", "purchase", "save", "run", "execute", "install", "uninstall"}
        
        if action.type == "click" and any(kw in desc for kw in stateful_keywords):
            return True
            
        if action.type == "type" and ("terminal" in desc or "console" in desc or "bash" in desc or "cmd" in desc):
            return True
            
        return False

    def _parse_claude_gpt(self, raw: str) -> Action:
        """
        Extract the first ```python ... ``` block and map the function call to Action.
        E.g.: aci.click("Submit button") → Action(type="click", target_description="Submit button")
        """
        # If the raw output is a JSON string (e.g., from our own fallback error handler),
        # parse it as JSON directly to preserve keys like "reason".
        raw_stripped = raw.strip()
        if raw_stripped.startswith("{") and raw_stripped.endswith("}"):
            try:
                return self._parse_local_json(raw_stripped)
            except Exception:
                pass

        code = self._extract_code_block(raw)
        if not code:
            # Fallback if there are no backticks but a command exists
            if "agent." in raw or "aci." in raw:
                code = raw
            else:
                # Direct signal indicators
                if "DONE" in raw.upper():
                    return Action(type="done")
                elif "FAIL" in raw.upper():
                    return Action(type="fail")
                raise ValueError("Could not find executable Python code block or action in response.")

        code = code.strip()

        # Regex match call expression like: agent.click("...", ...)
        pattern = r"(?:agent|aci)\.(\w+)\((.*)\)"
        match = re.search(pattern, code, re.DOTALL)
        if not match:
            if "done()" in code or "done" in code:
                return Action(type="done")
            elif "fail()" in code or "fail" in code:
                return Action(type="fail")
            raise ValueError(f"Unsupported python command format: {code}")

        action_type = match.group(1)
        args_str = match.group(2).strip()

        # Safely parse arguments using AST
        try:
            tree = ast.parse(f"f({args_str})")
            call_node = tree.body[0].value  # type: ignore[attr-defined]
            
            # Literal evaluation of positional arguments
            pos_args = []
            for arg in call_node.args:
                try:
                    pos_args.append(ast.literal_eval(arg))
                except ValueError:
                    if isinstance(arg, ast.Name):
                        pos_args.append(arg.id)
                    elif isinstance(arg, ast.Constant):
                        pos_args.append(arg.value)
                    elif isinstance(arg, ast.List):
                        pos_args.append([ast.literal_eval(el) for el in arg.elts])
                    else:
                        pos_args.append(ast.unparse(arg))

            # Literal evaluation of keyword arguments
            kwargs = {}
            for kw in call_node.keywords:
                try:
                    kwargs[kw.arg] = ast.literal_eval(kw.value)
                except ValueError:
                    if isinstance(kw.value, ast.Name):
                        kwargs[kw.arg] = kw.value.id
                    elif isinstance(kw.value, ast.Constant):
                        kwargs[kw.arg] = kw.value.value
                    elif isinstance(kw.value, ast.List):
                        kwargs[kw.arg] = [ast.literal_eval(el) for el in kw.value.elts]
                    else:
                        kwargs[kw.arg] = ast.unparse(kw.value)
        except Exception as e:
            logger.error(f"AST parsing failed for arguments '{args_str}': {e}. Falling back to empty lists.")
            pos_args = []
            kwargs = {}

        params: dict[str, Any] = kwargs
        target_description: Optional[str] = None

        # Map actions to unified format
        if action_type == "click":
            target_description = pos_args[0] if len(pos_args) > 0 else kwargs.get("element_description")
            if len(pos_args) > 1:
                params["num_clicks"] = pos_args[1]
            if len(pos_args) > 2:
                params["button_type"] = pos_args[2]
            if len(pos_args) > 3:
                params["hold_keys"] = pos_args[3]

        elif action_type == "type":
            target_description = pos_args[0] if len(pos_args) > 0 else kwargs.get("element_description")
            if len(pos_args) > 1:
                params["text"] = pos_args[1]
            if len(pos_args) > 2:
                params["overwrite"] = pos_args[2]
            if len(pos_args) > 3:
                params["enter"] = pos_args[3]

        elif action_type == "scroll":
            target_description = pos_args[0] if len(pos_args) > 0 else kwargs.get("element_description")
            if len(pos_args) > 1:
                params["clicks"] = pos_args[1]

        elif action_type == "hotkey":
            key_val = pos_args[0] if len(pos_args) > 0 else kwargs.get("key") or kwargs.get("keys")
            params["key"] = key_val

        elif action_type == "hold_and_press":
            params["hold_keys"] = pos_args[0] if len(pos_args) > 0 else kwargs.get("hold_keys", [])
            params["press_keys"] = pos_args[1] if len(pos_args) > 1 else kwargs.get("press_keys", [])

        elif action_type == "open":
            app_val = pos_args[0] if len(pos_args) > 0 else kwargs.get("app_or_filename")
            params["app_or_filename"] = app_val

        elif action_type == "switch_applications":
            app_code = pos_args[0] if len(pos_args) > 0 else kwargs.get("app_code")
            params["app_code"] = app_code

        elif action_type == "drag_and_drop":
            start_desc = pos_args[0] if len(pos_args) > 0 else kwargs.get("starting_description") or kwargs.get("source_description")
            end_desc = pos_args[1] if len(pos_args) > 1 else kwargs.get("ending_description") or kwargs.get("target_description")
            params["starting_description"] = start_desc
            params["ending_description"] = end_desc
            if len(pos_args) > 2:
                params["hold_keys"] = pos_args[2]

        elif action_type == "highlight_text_span":
            start = pos_args[0] if len(pos_args) > 0 else kwargs.get("starting_phrase")
            end = pos_args[1] if len(pos_args) > 1 else kwargs.get("ending_phrase")
            params["starting_phrase"] = start
            params["ending_phrase"] = end
            if len(pos_args) > 2:
                params["button"] = pos_args[2]

        elif action_type == "save_to_knowledge":
            text_val = pos_args[0] if len(pos_args) > 0 else kwargs.get("text")
            params["text"] = text_val

        elif action_type == "call_code_agent":
            task_val = pos_args[0] if len(pos_args) > 0 else kwargs.get("task")
            params["task"] = task_val

        elif action_type == "wait":
            time_val = pos_args[0] if len(pos_args) > 0 else kwargs.get("time")
            params["time"] = time_val

        elif action_type == "done":
            pass

        elif action_type == "fail":
            reason_val = pos_args[0] if len(pos_args) > 0 else kwargs.get("reason", "")
            params["reason"] = reason_val

        else:
            raise ValueError(f"Unknown action type in Python block: {action_type}")

        return Action(
            type=action_type,
            target_description=target_description,
            params=params
        )

    def _parse_local_json(self, raw: str) -> Action:
        """
        Parse JSON dict from Fara-7B / OpenCUA-7B output.
        Handles two formats:
          1. Native <tool_call> format: {"name": "computer", "arguments": {"action": "left_click", ...}}
          2. Our JSON format:           {"action": "click", "element_id": ..., ...}
        """
        # Try native <tool_call> format first (Fara-7B fine-tuned default)
        tool_call_action = self._try_parse_tool_call(raw)
        if tool_call_action is not None:
            return tool_call_action

        # Fallback: our own JSON format
        data = self._extract_json(raw)
        if not data:
            raise ValueError(f"Could not parse valid JSON from local model output: {raw[:200]!r}")

        action_type = data.get("action")
        if not action_type:
            raise ValueError("JSON response missing 'action' field")

        element_id = data.get("element_id")
        params = {k: v for k, v in data.items() if k not in ("action", "element_id", "thoughts")}

        return Action(
            type=action_type,
            element_id=element_id,
            params=params
        )

    def _parse_showui(self, raw: str) -> Action:
        """
        Parse ShowUI-2B output: {'action': 'CLICK', 'position': [0.49, 0.42], 'value': None}
        Positions are normalized [0-1] — stored as x_norm/y_norm for SandboxACI to scale.
        """
        # ShowUI outputs Python dict syntax (single quotes, None not null) — json.loads() fails on it.
        # Strategy: try JSON first, then ast.literal_eval on the extracted dict substring,
        # then ast.literal_eval on the full string as a last resort.
        data: Optional[dict[str, Any]] = self._extract_json(raw)
        if not data:
            dict_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if dict_match:
                try:
                    data = ast.literal_eval(dict_match.group())
                except Exception:
                    pass
        if not data:
            try:
                data = ast.literal_eval(raw)
            except Exception:
                raise ValueError(f"Could not parse ShowUI output: {raw[:200]!r}")

        raw_action = (data.get("action") or "").upper()
        position = data.get("position")
        value = data.get("value")

        params: dict[str, Any] = {}

        if position is not None and isinstance(position, list) and len(position) == 2:
            if isinstance(position[0], list):
                # SELECT_TEXT: [[x1,y1],[x2,y2]]
                params["x1_norm"] = float(position[0][0])
                params["y1_norm"] = float(position[0][1])
                params["x2_norm"] = float(position[1][0])
                params["y2_norm"] = float(position[1][1])
            else:
                params["x_norm"] = float(position[0])
                params["y_norm"] = float(position[1])

        if raw_action == "CLICK":
            return Action(type="click", params=params)

        elif raw_action in ("INPUT", "TYPE"):
            params["text"] = str(value or "")
            return Action(type="type", params=params)

        elif raw_action == "SELECT":
            return Action(type="click", params=params)

        elif raw_action == "HOVER":
            return Action(type="wait", params={"time": 0.2})

        elif raw_action == "SCROLL":
            params["direction"] = str(value or "down").lower()
            params["amount"] = 3
            return Action(type="scroll", params=params)

        elif raw_action == "HOTKEY":
            return Action(type="hotkey", params={"key": str(value or "")})

        elif raw_action == "ENTER":
            return Action(type="hotkey", params={"key": "enter"})

        elif raw_action == "NAVIGATE":
            return Action(type="navigate", params={"url": str(value or "")})

        elif raw_action == "COPY":
            return Action(type="hotkey", params={"key": "ctrl+c"})

        elif raw_action == "SELECT_TEXT":
            if "x1_norm" in params:
                return Action(type="drag_and_drop", params=params)
            return Action(type="wait", params={"time": 0.1})

        elif raw_action == "ANSWER":
            return Action(type="done", params={"answer": str(value or "")})

        elif raw_action == "DONE":
            summary = str(value or data.get("summary") or "")
            return Action(type="done", params={"summary": summary})

        elif raw_action == "FAIL":
            # "value" is the ShowUI-native field; "reason" is used by our fallback error JSON
            reason = str(value or data.get("reason") or "Task cannot be completed")
            return Action(type="fail", params={"reason": reason})

        else:
            raise ValueError(f"Unknown ShowUI action: {raw_action!r}")

    @staticmethod
    def _try_parse_tool_call(raw: str) -> Optional[Action]:
        """
        Parse Fara-7B's native <tool_call> XML-wrapped JSON format.
        Example: <tool_call>{"name": "computer", "arguments": {"action": "left_click", "coordinate": [x, y]}}</tool_call>
        Maps computer-use primitive actions to our unified Action schema.
        """
        match = re.search(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", raw, re.DOTALL)
        if not match:
            return None
        try:
            tool_data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

        arguments = tool_data.get("arguments", {})
        raw_action = arguments.get("action", "")
        coordinate = arguments.get("coordinate", [])

        if raw_action in ("left_click", "right_click", "double_click"):
            params: dict[str, Any] = {}
            if len(coordinate) >= 2:
                params["x"] = int(coordinate[0])
                params["y"] = int(coordinate[1])
            if raw_action == "right_click":
                params["button_type"] = "right"
            elif raw_action == "double_click":
                params["num_clicks"] = 2
            return Action(type="click", params=params)

        elif raw_action == "type":
            return Action(type="type", params={"text": arguments.get("text", "")})

        elif raw_action == "key":
            return Action(type="hotkey", params={"key": arguments.get("key", "")})

        elif raw_action in ("scroll_up", "scroll_down", "scroll"):
            direction = "up" if raw_action == "scroll_up" else "down"
            amount = int(arguments.get("amount", 3))
            params = {"direction": direction, "amount": amount}
            if len(coordinate) >= 2:
                params["x"] = int(coordinate[0])
                params["y"] = int(coordinate[1])
            return Action(type="scroll", params=params)

        elif raw_action == "screenshot":
            return Action(type="wait", params={"time": 0.3})

        elif raw_action == "move_mouse":
            params = {}
            if len(coordinate) >= 2:
                params["x"] = int(coordinate[0])
                params["y"] = int(coordinate[1])
            return Action(type="wait", params={"time": 0.1})

        elif raw_action in ("done", "fail", "wait"):
            return Action(type=raw_action, params=arguments)

        # ── Browser tool actions (name="browser") ──────────────────────────
        elif raw_action in ("visit", "navigate", "goto", "open_url", "go"):
            url = arguments.get("url") or arguments.get("href") or arguments.get("link", "")
            return Action(type="navigate", params={"url": url})

        elif raw_action in ("back", "go_back", "browser_back"):
            return Action(type="hotkey", params={"key": "alt+left"})

        elif raw_action in ("forward", "go_forward", "browser_forward"):
            return Action(type="hotkey", params={"key": "alt+right"})

        elif raw_action in ("refresh", "reload", "browser_refresh"):
            return Action(type="hotkey", params={"key": "ctrl+r"})

        elif raw_action in ("new_tab", "open_tab"):
            url = arguments.get("url", "")
            return Action(type="navigate", params={"url": url, "new_tab": True})

        elif raw_action in ("close_tab",):
            return Action(type="hotkey", params={"key": "ctrl+w"})

        elif raw_action in ("find", "search_page"):
            text = arguments.get("text") or arguments.get("query", "")
            return Action(type="hotkey", params={"key": "ctrl+f", "search_text": text})

        return None

    @staticmethod
    def _extract_code_block(text: str) -> Optional[str]:
        """Return contents of first ```python block, or None."""
        match = re.search(r"```python\s*(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Fallback to general code blocks if not labeled python
        match = re.search(r"```\s*(.*?)```", text, re.DOTALL)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_json(text: str) -> Optional[dict[str, Any]]:
        """Return first JSON object found in text, or None."""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
        return None
