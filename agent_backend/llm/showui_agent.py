"""
ShowUI-2B Agent — primary visual-language-action model for Oryonix.

Replaces the Fara-7B (text-only LM Studio) + Claude Haiku (screen description) combo.
ShowUI directly maps: screenshot + task → action with normalized coordinates.

Model:  showlab/ShowUI-2B  (Qwen2.5-VL-2B fine-tuned on GUI navigation data)
VRAM:   ~3-4 GB with NF4 quantization  (safe on 4060 Ti 8 GB)
Output: {'action': 'CLICK', 'position': [0.49, 0.42], 'value': None}

Lifecycle:
  - Instantiate once (lazy load on first inference call)
  - Model stays resident in VRAM between steps — no reload per step
  - Falls back gracefully if torch/transformers are unavailable
"""
from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from typing import Optional

logger = logging.getLogger("desktopenv.agent")

# ── Navigation system prompt (ShowUI standard format) ─────────────────────────

_NAV_SYSTEM = """You are an assistant trained to navigate the {app_type} screen.
Given a task instruction, a screen observation, and an action history sequence,
output the next action and wait for the next observation.
Here is the action space:
{action_space}

Format the action as a dictionary with the following keys:
{{'action': 'ACTION_TYPE', 'value': 'element', 'position': [x,y]}}

If value or position is not applicable, set it as `None`.
Position represents the relative coordinates on the screenshot scaled to 0-1.
"""

_WEB_ACTION_SPACE = """
1. `CLICK`: Click on an element, value is None, position [x,y] required.
2. `INPUT`: Type a string, value is the text to type, position [x,y] required.
3. `SELECT`: Select an element, value is None, position [x,y] required.
4. `HOVER`: Hover on an element, value is None, position [x,y] required.
5. `ANSWER`: Provide an answer, value is the answer text, position is None.
6. `ENTER`: Press Enter, value and position are None.
7. `SCROLL`: Scroll the screen, value is 'up' or 'down', position is None.
8. `SELECT_TEXT`: Select a text span, position [[x1,y1],[x2,y2]] required.
9. `COPY`: Copy text, value is the text, position is None.
10. `NAVIGATE`: Navigate to a URL, value is the URL, position is None.
11. `DONE`: Task completed, value is a brief summary, position is None.
12. `FAIL`: Task cannot be completed, value is the reason, position is None.
"""

_DESKTOP_ACTION_SPACE = """
1. `CLICK`: Click on an element, value is None, position [x,y] required.
2. `INPUT`: Type a string, value is the text, position [x,y] required.
3. `SCROLL`: Scroll the screen, value is 'up' or 'down', position [x,y] required.
4. `HOTKEY`: Press a keyboard shortcut, value is the combo (e.g. 'ctrl+c'), position is None.
5. `NAVIGATE`: Navigate browser to URL, value is the URL, position is None.
6. `ENTER`: Press Enter, value and position are None.
7. `DONE`: Task completed, value is a brief summary, position is None.
8. `FAIL`: Task cannot be completed, value is the reason, position is None.
"""

MIN_PIXELS = 256 * 28 * 28
MAX_PIXELS = 1344 * 28 * 28
# Keep last N history entries to avoid inflating the prompt token count
_MAX_HISTORY = 6


class ShowUIAgent:
    """
    Wraps ShowUI-2B inference as an async-friendly action model.
    Lazy-loads on first call; stays resident in VRAM.
    """

    def __init__(self, model_path: str = "showlab/ShowUI-2B") -> None:
        import torch
        import transformers
        import qwen_vl_utils  # pre-flight import check — raises if missing

        self.model_path = model_path
        self._model = None
        self._processor = None
        self._device: str = "cpu"

    def unload(self) -> None:
        """Release model weights from VRAM so Ollama can use the GPU."""
        if self._model is not None:
            try:
                import torch
                del self._model
                del self._processor
                torch.cuda.empty_cache()
            except Exception:
                pass
            finally:
                self._model = None
                self._processor = None
        logger.info("[ShowUI] Model unloaded from VRAM.")

    # ── Public async API ─────────────────────────────────────────────────────

    async def get_action(
        self,
        screenshot: bytes,
        task: str,
        task_type: str = "desktop",
        history: list[str] | None = None,
    ) -> str:
        """
        Async entry point. Returns the raw model output string.
        ActionNormalizer (parse_mode="showui") turns it into a unified Action.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._infer,
            screenshot,
            task,
            task_type,
            (history or [])[-_MAX_HISTORY:],
        )

    # ── Internal sync inference ───────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        """Load model + processor into VRAM on first call."""
        if self._model is not None:
            return

        import torch
        from transformers import (
            Qwen2VLForConditionalGeneration,
            AutoProcessor,
            BitsAndBytesConfig,
        )

        logger.info(f"[ShowUI] Loading {self.model_path} with NF4 quantization…")

        quant = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        self._model = Qwen2VLForConditionalGeneration.from_pretrained(
            self.model_path,
            torch_dtype=torch.float16,
            device_map="auto",
            quantization_config=quant,
        )
        self._processor = AutoProcessor.from_pretrained(
            self.model_path,
            min_pixels=MIN_PIXELS,
            max_pixels=MAX_PIXELS,
        )
        # Detect which device the model landed on
        try:
            self._device = next(self._model.parameters()).device.type
        except Exception:
            self._device = "cuda"

        logger.info(f"[ShowUI] Model loaded on {self._device}.")

    def _infer(
        self,
        screenshot_bytes: bytes,
        task: str,
        task_type: str,
        history: list[str],
    ) -> str:
        """Synchronous model forward pass — called via run_in_executor."""
        from PIL import Image
        from qwen_vl_utils import process_vision_info

        self._ensure_loaded()

        action_space = _WEB_ACTION_SPACE if task_type == "web" else _DESKTOP_ACTION_SPACE
        system_prompt = _NAV_SYSTEM.format(app_type=task_type, action_space=action_space)

        history_text = ""
        if history:
            lines = "\n".join(f"  {i + 1}. {h}" for i, h in enumerate(history))
            history_text = f"\nPrevious actions:\n{lines}"

        image = Image.open(BytesIO(screenshot_bytes)).convert("RGB")

        content = [
            {"type": "text", "text": system_prompt},
            {"type": "text", "text": f"Task: {task}{history_text}"},
            {
                "type": "image",
                "image": image,
                "min_pixels": MIN_PIXELS,
                "max_pixels": MAX_PIXELS,
            },
        ]
        messages = [{"role": "user", "content": content}]

        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self._processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self._device)

        generated_ids = self._model.generate(**inputs, max_new_tokens=128)
        trimmed = [
            out[len(inp):]
            for inp, out in zip(inputs.input_ids, generated_ids)
        ]
        output_text = self._processor.batch_decode(
            trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0].strip()

        logger.info(f"[ShowUI] Raw output: {output_text[:200]}")
        return output_text
