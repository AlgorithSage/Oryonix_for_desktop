"""
Tier 0 Intent Executor — direct OS execution, zero LLM inference.

Handles ~70% of everyday commands in <100ms:
  open chrome / youtube / notion / brave
  go to github.com
  search for python tutorials
  create folder "projects" on desktop
  open downloads folder
  open samay raina's yt channel
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("desktopenv.agent")

# ── App name → shell command ───────────────────────────────────────────────────
# Values are passed to subprocess with shell=True on Windows.
# Apps with desktop installers (Discord, Notion, Spotify…) often aren't in PATH,
# so we fall back to Start-Menu .lnk search when the direct launch fails.
_APPS: dict[str, str] = {
    # Browsers
    "chrome":               "chrome",
    "google chrome":        "chrome",
    "brave":                "brave",
    "brave browser":        "brave",
    "firefox":              "firefox",
    "mozilla firefox":      "firefox",
    "edge":                 "msedge",
    "microsoft edge":       "msedge",
    # Productivity
    "notepad":              "notepad",
    "notepad++":            "notepad++",
    "calculator":           "calc",
    "calc":                 "calc",
    "paint":                "mspaint",
    "task manager":         "taskmgr",
    "file explorer":        "explorer",
    "explorer":             "explorer",
    "snipping tool":        "snippingtool",
    "control panel":        "control",
    "settings":             "ms-settings:",
    # Dev
    "vs code":              "code",
    "vscode":               "code",
    "visual studio code":   "code",
    "terminal":             "wt",
    "windows terminal":     "wt",
    "cmd":                  "cmd",
    "command prompt":       "cmd",
    "powershell":           "powershell",
    # Office
    "word":                 "winword",
    "excel":                "excel",
    "powerpoint":           "powerpnt",
    "outlook":              "outlook",
    # Communication / apps
    "teams":                "teams",
    "discord":              "discord",
    "slack":                "slack",
    "zoom":                 "zoom",
    "notion":               "notion",
    "obsidian":             "obsidian",
    "spotify":              "spotify",
    "steam":                "steam",
    "vlc":                  "vlc",
}

# ── Website name → canonical URL ──────────────────────────────────────────────
# Only pure websites — desktop apps (spotify, discord…) are intentionally absent
# so "open spotify" launches the app, not the web player.
_SITES: dict[str, str] = {
    "youtube":          "https://www.youtube.com",
    "yt":               "https://www.youtube.com",
    "google":           "https://www.google.com",
    "gmail":            "https://mail.google.com",
    "google drive":     "https://drive.google.com",
    "google docs":      "https://docs.google.com",
    "github":           "https://github.com",
    "reddit":           "https://www.reddit.com",
    "twitter":          "https://twitter.com",
    "x":                "https://x.com",
    "facebook":         "https://www.facebook.com",
    "instagram":        "https://www.instagram.com",
    "linkedin":         "https://www.linkedin.com",
    "netflix":          "https://www.netflix.com",
    "amazon":           "https://www.amazon.com",
    "wikipedia":        "https://www.wikipedia.org",
    "stackoverflow":    "https://stackoverflow.com",
    "stack overflow":   "https://stackoverflow.com",
    "chatgpt":          "https://chat.openai.com",
    "claude":           "https://claude.ai",
    "perplexity":       "https://www.perplexity.ai",
    "huggingface":      "https://huggingface.co",
    "hugging face":     "https://huggingface.co",
    "figma":            "https://www.figma.com",
    "canva":            "https://www.canva.com",
    "trello":           "https://trello.com",
    "notion web":       "https://www.notion.so",
}

# ── Common folder shortcuts ───────────────────────────────────────────────────
_FOLDERS: dict[str, Path] = {
    "desktop":   Path.home() / "Desktop",
    "downloads": Path.home() / "Downloads",
    "documents": Path.home() / "Documents",
    "pictures":  Path.home() / "Pictures",
    "videos":    Path.home() / "Videos",
    "music":     Path.home() / "Music",
    "home":      Path.home(),
}


@dataclass
class Tier0Result:
    success: bool
    message: str


class IntentExecutor:
    """
    Tier 0 — instant OS dispatch.
    Call execute(goal) → Tier0Result if handled, None to fall through to LLM.
    """

    def execute(self, goal: str) -> Optional[Tier0Result]:
        g = goal.strip().lower()
        return (
            self._direct_url(g)
            or self._yt_channel(g)
            or self._site_open(g)
            or self._app_launch(g)
            or self._web_search(g)
            or self._folder_create(g)
            or self._folder_open(g)
            or self._system_op(g)
        )

    # ── Direct https:// URL ───────────────────────────────────────────────────

    def _direct_url(self, g: str) -> Optional[Tier0Result]:
        m = re.search(r'https?://\S+', g)
        if m:
            url = m.group().rstrip(".,)")
            webbrowser.open(url)
            return Tier0Result(True, f"Opened {url}")
        return None

    # ── YouTube channel search ────────────────────────────────────────────────

    def _yt_channel(self, g: str) -> Optional[Tier0Result]:
        # "open samay raina's yt/youtube channel" or "open samay raina yt channel"
        m = re.search(
            r"(?:open\s+)?(.+?)(?:'s|s'|\s+)(?:yt|youtube)\s+channel", g
        )
        if not m:
            # "open youtube channel of samay raina"
            m = re.search(r"(?:yt|youtube)\s+channel\s+(?:of|for)\s+(.+)", g)
        if not m:
            return None
        name = m.group(1).strip()
        if name.endswith("'s"):
            name = name[:-2]
        elif name.endswith("s'"):
            name = name[:-1]
        url = f"https://www.youtube.com/results?search_query={name.replace(' ', '+')}+channel"
        webbrowser.open(url)
        return Tier0Result(True, f"Searching YouTube for '{name}' channel")

    # ── Known site open ───────────────────────────────────────────────────────

    def _site_open(self, g: str) -> Optional[Tier0Result]:
        # Patterns: "open X", "go to X", "visit X", "navigate to X"
        for pat in (
            r"(?:go to|visit|navigate to|show me)\s+(.+?)\.?\s*$",
            r"(?:open|launch)\s+(.+?)(?:\s+in\s+\w+)?\s*$",
        ):
            m = re.search(pat, g)
            if not m:
                continue
            target = m.group(1).strip().rstrip(".")

            # Must be in _SITES (never an app name)
            url = _SITES.get(target)
            if url:
                webbrowser.open(url)
                return Tier0Result(True, f"Opened {target} → {url}")

            # Bare domain like "github.com"
            if re.match(r'^[\w\-]+\.(com|org|net|io|ai|dev|co|edu|gov|app|tech)$', target):
                url = f"https://{target}"
                webbrowser.open(url)
                return Tier0Result(True, f"Opened {url}")

        return None

    # ── App launch ────────────────────────────────────────────────────────────

    def _app_launch(self, g: str) -> Optional[Tier0Result]:
        m = re.search(
            r"(?:open|launch|start|run)\s+(.+?)(?:\s*$|\s+(?:and|then|,)\s)",
            g
        )
        if not m:
            return None

        raw = m.group(1).strip().rstrip(".")

        # Ignore generic pronouns/words to prevent false positive matches (e.g. "open it")
        if raw.lower() in (
            "it", "them", "that", "this", "file", "folder", "app", "application",
            "program", "window", "website", "page", "site", "link", "url", "shortcut"
        ):
            return None

        # Don't intercept URL/site goals
        if raw in _SITES or re.match(r'.+\.(com|org|net|io|ai|dev)$', raw):
            return None

        # Registry lookup (exact → partial)
        exe = _APPS.get(raw)
        if not exe:
            for key, val in _APPS.items():
                if key in raw or raw in key:
                    exe = val
                    break

        if exe:
            try:
                if exe.startswith("ms-"):
                    os.startfile(exe)
                else:
                    subprocess.Popen(exe, shell=True)
                return Tier0Result(True, f"Launched {raw}")
            except Exception as err:
                logger.warning(f"[Tier0] Registry launch failed for {exe!r}: {err}")

        # Start Menu .lnk fallback (handles Notion, Discord, etc.)
        lnk = self._find_lnk(raw)
        if lnk:
            try:
                os.startfile(lnk)
                return Tier0Result(True, f"Launched {raw} from Start Menu")
            except Exception as err:
                logger.warning(f"[Tier0] startfile failed for {lnk!r}: {err}")

        # PowerShell Start-Process (last resort — searches AppData, registry)
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f'Start-Process "{raw}" -ErrorAction Stop'],
                capture_output=True, text=True, timeout=4
            )
            if result.returncode == 0:
                return Tier0Result(True, f"Launched {raw}")
        except Exception:
            pass

        return None

    def _find_lnk(self, name: str) -> Optional[str]:
        """Search Windows Start Menu for a matching .lnk shortcut."""
        search_roots = [
            Path(os.environ.get("APPDATA", ""))
            / "Microsoft" / "Windows" / "Start Menu" / "Programs",
            Path("C:/ProgramData/Microsoft/Windows/Start Menu/Programs"),
        ]
        name_lower = name.lower()
        for root in search_roots:
            if not root.exists():
                continue
            for lnk in root.rglob("*.lnk"):
                if name_lower in lnk.stem.lower():
                    return str(lnk)
        return None

    # ── Web search ────────────────────────────────────────────────────────────

    def _web_search(self, g: str) -> Optional[Tier0Result]:
        # Exclude local search targets like Start Menu, search bar, etc.
        local_keywords = {
            "start menu", "search menu", "windows search", "windows menu",
            "file explorer", "explorer", "computer", "my pc", "local",
            "search bar", "desktop search", "start", "taskbar", "win key",
            "windows key", "win button", "windows button", "win+s", "windows+s",
            "win search", "win menu", "control panel", "settings"
        }
        if any(kw in g for kw in local_keywords):
            return None

        m = re.search(
            r"(?:search|google|look up|find)\s+(?:for\s+)?(.+?)"
            r"(?:\s+(?:on|in|using)\s+\w+)?\.?\s*$",
            g
        )
        if not m:
            return None
        query = m.group(1).strip()
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        webbrowser.open(url)
        return Tier0Result(True, f"Searched Google for '{query}'")

    # ── Folder create ─────────────────────────────────────────────────────────

    def _folder_create(self, g: str) -> Optional[Tier0Result]:
        m = re.search(
            r"(?:create|make|new)\s+(?:a\s+)?(?:new\s+)?(?:folder|directory)\s+"
            r"(?:called\s+|named\s+)?['\"]?([^'\"]+?)['\"]?"
            r"(?:\s+(?:on|in|at|inside)\s+([a-z]+))?\.?\s*$",
            g
        )
        if not m:
            return None
        folder_name = m.group(1).strip().strip("'\"")
        
        # Skip if folder name contains compound indicators or action verbs (e.g. "and open it")
        folder_name_lower = folder_name.lower()
        if any(w in folder_name_lower for w in (" and ", " then ", " open ", " delete ", " move ", " copy ", " launch ")):
            return None

        loc = (m.group(2) or "desktop").lower()
        base = _FOLDERS.get(loc, _FOLDERS["desktop"])
        target = base / folder_name
        try:
            target.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["explorer", str(target)])
            return Tier0Result(True, f"Created folder '{folder_name}' at {target}")
        except Exception as e:
            return Tier0Result(False, f"Could not create folder: {e}")

    # ── Folder open ───────────────────────────────────────────────────────────

    def _folder_open(self, g: str) -> Optional[Tier0Result]:
        m = re.search(
            r"(?:open|show|browse|explore)\s+(?:my\s+|the\s+)?(\w+)\s+folder", g
        )
        if not m:
            return None
        name = m.group(1).lower()
        path = _FOLDERS.get(name)
        if path and path.exists():
            subprocess.Popen(["explorer", str(path)])
            return Tier0Result(True, f"Opened {name} folder ({path})")
        return None

    # ── System operations ─────────────────────────────────────────────────────

    def _system_op(self, g: str) -> Optional[Tier0Result]:
        if any(x in g for x in ("show desktop", "minimize all windows", "win+d")):
            try:
                import pyautogui
                pyautogui.hotkey("win", "d")
                return Tier0Result(True, "Showed desktop (Win+D)")
            except Exception:
                pass

        if "task manager" in g:
            subprocess.Popen(["taskmgr"])
            return Tier0Result(True, "Opened Task Manager")

        if "screenshot" in g or "screen shot" in g:
            try:
                import datetime
                from PIL import ImageGrab
                fname = (
                    _FOLDERS["desktop"]
                    / f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                )
                ImageGrab.grab().save(str(fname))
                return Tier0Result(True, f"Screenshot saved → {fname.name}")
            except Exception as e:
                return Tier0Result(False, f"Screenshot failed: {e}")

        return None
