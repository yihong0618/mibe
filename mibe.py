#!/usr/bin/env python3
"""Monitor Codex/Kimi session JSONL logs and notify via XiaoAi (miservice)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import sys
from pathlib import Path
from typing import Callable

from aiohttp import ClientSession
from miservice import MiAccount, MiNAService

try:
    import tomllib  # Python 3.11+
except ImportError:
    tomllib = None  # type: ignore[assignment]

# Session directories
CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"
KIMI_SESSIONS_DIR = Path.home() / ".kimi" / "sessions"

POLL_INTERVAL = 0.5
TOKEN_STORE = str(Path.home() / ".mi.token")

# How often (seconds) to send silent TTS to keep XiaoAi's light on.
KEEPALIVE_INTERVAL = 5.0
KEEPALIVE_TEXT = "。"

# Delay (seconds) after TTS to let it finish before muting.
TTS_SETTLE_DELAY = 3.0

# Silence detection for Kimi completion (seconds)
KIMI_COMPLETION_SILENCE = 5.0

# Configurable settings (can be overridden via config file)
SETTINGS: dict[str, float] = {
    "kimi_completion_silence": KIMI_COMPLETION_SILENCE,
    "codex_input_question_max_words": 160,
}

# Default TTS messages for each event type.
DEFAULT_MESSAGES: dict[str, str] = {
    "codex_started": "codex启动",
    "codex_complete": "codex完成",
    "codex_aborted": "codex中断",
    "codex_input_required": "codex需要你确认",
    "codex_input_single_template": "{alert_text}。{first_question}",
    "codex_input_multi_template": (
        "{alert_text}，共有{question_count}个问题。第一个问题：{first_question}"
    ),
    "codex_input_fallback_question": "请查看终端中的问题",
    "kimi_started": "kimi启动",
    "kimi_complete": "kimi完成",
}

# Global messages config (loaded from config file)
MESSAGES: dict[str, str] = DEFAULT_MESSAGES.copy()


def load_config(config_path: Path | str | None = None) -> dict:
    """Load config from TOML file. Returns empty dict if no config found."""
    global MESSAGES

    paths: list[Path] = []
    if config_path:
        paths.append(Path(config_path))
    else:
        # Search in common locations
        paths.extend(
            [
                Path("config.toml"),
                Path.home() / ".config" / "mibe" / "config.toml",
            ]
        )

    for p in paths:
        if p.exists():
            try:
                content = p.read_text(encoding="utf-8")
                if tomllib:
                    config = tomllib.loads(content)
                else:
                    # Fallback: use simple parsing for basic cases
                    config = _parse_simple_toml(content)

                # Update messages from config
                if "messages" in config:
                    for key in DEFAULT_MESSAGES:
                        if key in config["messages"]:
                            MESSAGES[key] = config["messages"][key]
                # Update settings from config
                if "settings" in config:
                    for key in SETTINGS:
                        if key in config["settings"]:
                            SETTINGS[key] = float(config["settings"][key])
                return config
            except Exception as exc:
                print(
                    f"[mibe] warning: failed to load config {p}: {exc}", file=sys.stderr
                )

    return {}


def _parse_simple_toml(content: str) -> dict:
    """Simple TOML parser fallback for basic cases (no tomllib)."""
    result: dict = {}
    current_section = None

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            result[current_section] = {}
        elif "=" in line and current_section:
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            # Remove quotes
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            result[current_section][key] = val

    return result


# ---------------------------------------------------------------------------
# miservice helpers
# ---------------------------------------------------------------------------


class XiaoAiNotifier:
    """Wraps miservice login and TTS via MiNAService."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self._session: ClientSession | None = None
        self._account: MiAccount | None = None
        self._mina: MiNAService | None = None
        self._device_id: str | None = None
        self._saved_volume: int | None = None
        self._keepalive_task: asyncio.Task | None = None

    @staticmethod
    def _parse_playing_flag(value: object) -> bool | None:
        """Parse a player state value into playing/idle/unknown."""
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            if value == 1:
                return True
            if value == 0:
                return False
            return None
        if isinstance(value, str):
            normalized = value.strip().lower()
            if not normalized:
                return None
            if normalized.isdigit():
                return XiaoAiNotifier._parse_playing_flag(int(normalized))
            if normalized in {"play", "playing", "start", "started"}:
                return True
            if normalized in {"idle", "stop", "stopped", "pause", "paused"}:
                return False
        return None

    async def login(self) -> None:
        mi_user = os.environ.get("MI_USER", "")
        mi_pass = os.environ.get("MI_PASS", "")
        mi_did = os.environ.get("MI_DID", "")

        if not mi_user or not mi_pass:
            print(
                "[mibe] error: MI_USER and MI_PASS environment variables required",
                file=sys.stderr,
            )
            raise SystemExit(1)

        self._session = ClientSession()
        self._account = MiAccount(self._session, mi_user, mi_pass, TOKEN_STORE)
        await self._account.login("micoapi")

        self._mina = MiNAService(self._account)
        devices = await self._mina.device_list()

        if mi_did:
            for d in devices:
                if d.get("miotDID", "") == str(mi_did):
                    self._device_id = d.get("deviceID")
                    break
            if not self._device_id:
                print(
                    f"[mibe] warning: MI_DID={mi_did} not found, using first device",
                    file=sys.stderr,
                )

        if not self._device_id and devices:
            self._device_id = devices[0].get("deviceID")

        if not self._device_id:
            print("[mibe] error: no XiaoAi device found", file=sys.stderr)
            raise SystemExit(1)

        if self.verbose:
            print(f"[mibe] logged in, device_id={self._device_id}")

    async def get_volume(self) -> int | None:
        """Get current volume (0-100) or None on failure."""
        if not self._mina or not self._device_id:
            return None
        try:
            status = await self._mina.player_get_status(self._device_id)
            info = json.loads(status.get("data", {}).get("info", "{}"))
            return info.get("volume")
        except Exception:  # noqa: BLE001
            return None

    async def set_volume(self, volume: int) -> None:
        if not self._mina or not self._device_id:
            return
        try:
            await self._mina.player_set_volume(self._device_id, volume)
            if self.verbose:
                print(f"[mibe] volume -> {volume}")
        except Exception as exc:  # noqa: BLE001
            print(f"[mibe] set_volume error: {exc}", file=sys.stderr)

    async def save_and_mute(self) -> None:
        """Save current volume then mute."""
        vol = await self.get_volume()
        if vol is not None:
            self._saved_volume = vol
            if self.verbose:
                print(f"[mibe] saved volume={vol}, muting")
        await self.set_volume(0)

    async def restore_volume(self) -> None:
        """Restore previously saved volume."""
        vol = self._saved_volume
        if vol is not None:
            await self.set_volume(vol)
            self._saved_volume = None

    async def speak(self, text: str) -> None:
        if not self._mina or not self._device_id:
            return
        try:
            await self._mina.text_to_speech(self._device_id, text)
            if self.verbose:
                print(f"[mibe] tts: {text}")
        except Exception as exc:  # noqa: BLE001
            print(f"[mibe] tts error: {exc}", file=sys.stderr)

    # -- keepalive: periodically send silent TTS to keep the light on --

    async def is_playing(self) -> bool | None:
        """Return whether the speaker is currently playing media."""
        if not self._mina or not self._device_id:
            return None
        try:
            status = await self._mina.player_get_status(self._device_id)
            info_raw = status.get("data", {}).get("info", "{}")
            info = json.loads(info_raw)
        except Exception:  # noqa: BLE001
            return None

        if not isinstance(info, dict):
            return None

        for key in ("isPlaying", "playing", "status", "playStatus", "playerStatus"):
            parsed = self._parse_playing_flag(info.get(key))
            if parsed is not None:
                return parsed

        return None

    async def _keepalive_tick(self) -> None:
        """Run one keepalive cycle with playback-aware guard."""
        playing = await self.is_playing()
        if playing is True:
            if self.verbose:
                print("[mibe] keepalive skipped: device playing")
            return
        if playing is None:
            if self.verbose:
                print("[mibe] keepalive skipped: status unknown")
            return

        if self.verbose:
            print("[mibe] keepalive tts")
        await self.speak(KEEPALIVE_TEXT)

    async def _keepalive_loop(self) -> None:
        """Send silent TTS at regular intervals so XiaoAi stays lit."""
        try:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                await self._keepalive_tick()
        except asyncio.CancelledError:
            pass

    def start_keepalive(self) -> None:
        if self._keepalive_task is None or self._keepalive_task.done():
            self._keepalive_task = asyncio.ensure_future(self._keepalive_loop())
            if self.verbose:
                print("[mibe] keepalive started")

    async def stop_keepalive(self) -> None:
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None
            if self.verbose:
                print("[mibe] keepalive stopped")

    async def close(self) -> None:
        await self.stop_keepalive()
        if self._session:
            await self._session.close()


# ---------------------------------------------------------------------------
# File monitoring
# ---------------------------------------------------------------------------


def list_session_files(sessions_dir: Path, pattern: str = "*.jsonl") -> list[Path]:
    if not sessions_dir.exists():
        return []
    return sorted(sessions_dir.rglob(pattern))


# ---------------------------------------------------------------------------
# Codex event processing
# ---------------------------------------------------------------------------

CODEX_WATCHED_EVENTS = frozenset({"task_started", "task_complete", "turn_aborted"})
CODEX_TTS_WORD_TOKEN_RE = re.compile(r"[\u3400-\u9fff]|[^\s\u3400-\u9fff]+")


def _sanitize_codex_question_text(text: object) -> str:
    """Normalize question text for TTS and cap by CJK/English-compatible tokens."""
    if not isinstance(text, str):
        return ""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return ""

    max_words = int(SETTINGS.get("codex_input_question_max_words", 160))
    token_iter = list(CODEX_TTS_WORD_TOKEN_RE.finditer(normalized))
    if max_words > 0 and len(token_iter) > max_words:
        suffix = "，后续请看终端"
        trimmed = normalized[: token_iter[max_words - 1].end()].rstrip()
        return f"{trimmed}{suffix}"
    return normalized


def _build_codex_request_user_input_tts(payload: dict) -> tuple[str, int]:
    """Build TTS text for Codex request_user_input function call."""
    alert_text = MESSAGES["codex_input_required"]
    fallback_question = MESSAGES["codex_input_fallback_question"]
    first_question = fallback_question
    question_count = 0

    arguments = payload.get("arguments")
    parsed: object = None
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            parsed = None

    if isinstance(parsed, dict):
        raw_questions = parsed.get("questions")
        if isinstance(raw_questions, list):
            question_count = len(raw_questions)
            first_question_text: str | None = None
            for item in raw_questions:
                if not isinstance(item, dict):
                    continue
                candidate = _sanitize_codex_question_text(item.get("question"))
                if not candidate:
                    candidate = _sanitize_codex_question_text(item.get("header"))
                if candidate:
                    first_question_text = candidate
                    break
            if first_question_text:
                first_question = first_question_text

    if not _sanitize_codex_question_text(first_question):
        first_question = fallback_question

    template_vars = {
        "alert_text": alert_text,
        "question_count": question_count,
        "first_question": first_question,
    }

    if question_count > 1:
        return (
            MESSAGES["codex_input_multi_template"].format(**template_vars),
            question_count,
        )
    return (
        MESSAGES["codex_input_single_template"].format(**template_vars),
        question_count,
    )


def _build_codex_escalation_confirmation_tts(payload: dict) -> tuple[str, bool]:
    """Build TTS text for function calls requiring escalated permissions."""
    if payload.get("type") != "function_call":
        return "", False

    arguments = payload.get("arguments")
    parsed: object = None
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            parsed = None

    if not isinstance(parsed, dict):
        return "", False
    if parsed.get("sandbox_permissions") != "require_escalated":
        return "", False

    prompt = _sanitize_codex_question_text(parsed.get("justification"))
    if not prompt:
        prompt = _sanitize_codex_question_text(parsed.get("cmd"))
    if not prompt:
        prompt = MESSAGES["codex_input_fallback_question"]

    tts_text = MESSAGES["codex_input_single_template"].format(
        alert_text=MESSAGES["codex_input_required"],
        question_count=1,
        first_question=prompt,
    )
    return tts_text, True


async def _handle_codex_task_event(
    payload: dict, path: Path, notifier: XiaoAiNotifier
) -> None:
    """Handle Codex task lifecycle events."""
    event_type = payload.get("type")
    if event_type not in CODEX_WATCHED_EVENTS:
        return

    turn_id = payload.get("turn_id")
    print(f"[mibe] codex {event_type} turn_id={turn_id} path={path}", flush=True)

    if event_type == "task_started":
        await notifier.speak(MESSAGES["codex_started"])
        await asyncio.sleep(TTS_SETTLE_DELAY)
        await notifier.save_and_mute()
        notifier.start_keepalive()
    elif event_type in ("task_complete", "turn_aborted"):
        await notifier.stop_keepalive()
        await notifier.restore_volume()
        msg_key = "codex_complete" if event_type == "task_complete" else "codex_aborted"
        await notifier.speak(MESSAGES[msg_key])


async def _handle_codex_request_user_input(
    payload: dict, path: Path, notifier: XiaoAiNotifier
) -> None:
    """Handle Codex request_user_input function call events."""
    if payload.get("type") != "function_call":
        return
    if payload.get("name") != "request_user_input":
        return

    tts_text, question_count = _build_codex_request_user_input_tts(payload)
    call_id = payload.get("call_id")
    print(
        "[mibe] codex request_user_input "
        f"call_id={call_id} questions={question_count} path={path}",
        flush=True,
    )

    await notifier.stop_keepalive()
    await notifier.restore_volume()
    await notifier.speak(tts_text)


async def _handle_codex_escalation_confirmation(
    payload: dict, path: Path, notifier: XiaoAiNotifier
) -> None:
    """Handle function call events that require user approval."""
    tts_text, matched = _build_codex_escalation_confirmation_tts(payload)
    if not matched:
        return

    call_id = payload.get("call_id")
    tool_name = payload.get("name")
    print(
        "[mibe] codex escalation_confirmation "
        f"tool={tool_name} call_id={call_id} path={path}",
        flush=True,
    )

    await notifier.stop_keepalive()
    await notifier.restore_volume()
    await notifier.speak(tts_text)


async def process_codex_event(
    event: dict, path: Path, notifier: XiaoAiNotifier
) -> None:
    """Process a single Codex event."""
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return

    event_kind = event.get("type")
    if event_kind == "event_msg":
        await _handle_codex_task_event(payload, path, notifier)
    elif event_kind == "response_item":
        await _handle_codex_request_user_input(payload, path, notifier)
        await _handle_codex_escalation_confirmation(payload, path, notifier)


# ---------------------------------------------------------------------------
# Kimi event processing
# ---------------------------------------------------------------------------


class KimiSessionState:
    """Track state for a single Kimi session to detect completion."""

    def __init__(self) -> None:
        self.active = False
        self.last_activity: float = 0.0
        self.completion_timer: asyncio.Task | None = None


KIMI_SESSION_STATES: dict[Path, KimiSessionState] = {}


async def _kimi_completion_handler(
    path: Path, notifier: XiaoAiNotifier, delay: float
) -> None:
    """Handle Kimi session completion after silence period."""
    await asyncio.sleep(delay)
    state = KIMI_SESSION_STATES.get(path)
    if state and state.active:
        state.active = False
        await notifier.stop_keepalive()
        await notifier.restore_volume()
        await notifier.speak(MESSAGES["kimi_complete"])
        print(f"[mibe] kimi complete (silence detected) path={path}", flush=True)


def _get_event_type(msg: dict) -> str | None:
    """Extract event type from Kimi message, handling nested SubagentEvent."""
    msg_type = msg.get("type")
    if not msg_type:
        return None

    # Handle SubagentEvent with nested TurnEnd/TurnBegin
    if msg_type == "SubagentEvent":
        payload = msg.get("payload", {})
        if isinstance(payload, dict):
            nested_event = payload.get("event", {})
            if isinstance(nested_event, dict):
                nested_type = nested_event.get("type")
                if nested_type:
                    return nested_type

    return msg_type


async def process_kimi_event(event: dict, path: Path, notifier: XiaoAiNotifier) -> None:
    """Process a single Kimi event."""
    msg = event.get("message", {})
    if not isinstance(msg, dict):
        msg = {}

    msg_type = _get_event_type(msg)

    # Get or create session state
    state = KIMI_SESSION_STATES.get(path)
    if state is None:
        state = KimiSessionState()
        KIMI_SESSION_STATES[path] = state

    # Handle TurnBegin (session start)
    if msg_type == "TurnBegin":
        if not state.active:
            state.active = True
            print(f"[mibe] kimi started path={path}", flush=True)
            await notifier.speak(MESSAGES["kimi_started"])
            await asyncio.sleep(TTS_SETTLE_DELAY)
            await notifier.save_and_mute()
            notifier.start_keepalive()
        state.last_activity = asyncio.get_event_loop().time()
        return

    # Handle TurnEnd (session complete) - including nested in SubagentEvent
    if msg_type == "TurnEnd" and state.active:
        state.active = False
        if state.completion_timer and not state.completion_timer.done():
            state.completion_timer.cancel()
        await notifier.stop_keepalive()
        await notifier.restore_volume()
        await notifier.speak(MESSAGES["kimi_complete"])
        print(f"[mibe] kimi complete (TurnEnd) path={path}", flush=True)
        return

    # For active sessions, ANY event resets the silence timer (not just typed ones).
    # This prevents false completion during long operations like WriteFile.
    if state.active:
        state.last_activity = asyncio.get_event_loop().time()

        # Cancel existing completion timer
        if state.completion_timer and not state.completion_timer.done():
            state.completion_timer.cancel()

        # Schedule new completion timer as fallback
        state.completion_timer = asyncio.create_task(
            _kimi_completion_handler(
                path, notifier, SETTINGS["kimi_completion_silence"]
            )
        )


# ---------------------------------------------------------------------------
# Generic file reading
# ---------------------------------------------------------------------------


async def read_new_lines(
    path: Path,
    offsets: dict[Path, int],
    notifier: XiaoAiNotifier,
    processor: Callable[[dict, Path, XiaoAiNotifier], asyncio.Future[None] | None],
) -> None:
    """Read new lines from a file and process them."""
    old_offset = offsets.get(path, 0)
    try:
        file_size = path.stat().st_size
    except OSError:
        return
    if file_size < old_offset:
        old_offset = 0

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        fh.seek(old_offset)
        while True:
            line_start = fh.tell()
            line = fh.readline()
            if not line:
                break
            if not line.endswith("\n"):
                fh.seek(line_start)  # incomplete line, retry next poll
                break
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                result = processor(event, path, notifier)
                if result is not None:
                    await result
        offsets[path] = fh.tell()


def init_offsets(
    sessions_dir: Path, replay: str, pattern: str = "*.jsonl"
) -> dict[Path, int]:
    """Build initial file-offset map based on replay strategy."""
    files = list_session_files(sessions_dir, pattern)
    offsets: dict[Path, int] = {}

    if replay == "all":
        for p in files:
            offsets[p] = 0
    elif replay == "latest" and files:
        latest = max(files, key=lambda p: p.stat().st_mtime_ns)
        for p in files:
            offsets[p] = 0 if p == latest else p.stat().st_size
    else:
        for p in files:
            offsets[p] = p.stat().st_size

    return offsets


# ---------------------------------------------------------------------------
# CLI: subcommands
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mibe",
        description="Monitor Codex/Kimi session logs and notify via XiaoAi.",
    )
    sub = parser.add_subparsers(dest="command")

    # --- login ---
    sub.add_parser("login", help="Test miservice login and list devices.")

    # --- monitor ---
    mon = sub.add_parser(
        "monitor", help="Watch session logs and send TTS notifications."
    )
    mon.add_argument(
        "--replay-existing",
        choices=("none", "latest", "all"),
        default="none",
        help="Replay events on startup (default: none).",
    )
    mon.add_argument(
        "--verbose",
        action="store_true",
        help="Print event and command details.",
    )
    mon.add_argument(
        "--codex-only",
        action="store_true",
        help="Only monitor Codex sessions.",
    )
    mon.add_argument(
        "--kimi-only",
        action="store_true",
        help="Only monitor Kimi sessions.",
    )
    mon.add_argument(
        "-c", "--config", metavar="PATH", help="Path to config file (TOML)."
    )

    return parser


async def cmd_login() -> int:
    """Test login and print device list."""
    mi_user = os.environ.get("MI_USER", "")
    mi_pass = os.environ.get("MI_PASS", "")

    if not mi_user or not mi_pass:
        print(
            "[mibe] error: set MI_USER and MI_PASS environment variables",
            file=sys.stderr,
        )
        return 1

    async with ClientSession() as session:
        account = MiAccount(session, mi_user, mi_pass, TOKEN_STORE)
        await account.login("micoapi")
        print("[mibe] login successful!")

        mina = MiNAService(account)
        devices = await mina.device_list()

        if not devices:
            print("[mibe] no devices found")
            return 0

        mi_did = os.environ.get("MI_DID", "")
        print(f"\n{'#':<4} {'Name':<20} {'Hardware':<12} {'miotDID':<16} {'Selected'}")
        print("-" * 70)
        for i, d in enumerate(devices, 1):
            did = d.get("miotDID", "")
            selected = (
                " <--"
                if (mi_did and did == mi_did)
                else ("" if mi_did else (" <-- (default)" if i == 1 else ""))
            )
            print(
                f"{i:<4} {d.get('name', '?'):<20} {d.get('hardware', '?'):<12} {did:<16} {selected}"
            )

        if not mi_did:
            print(
                f"\n[mibe] tip: set MI_DID={devices[0].get('miotDID', '')} to choose a device"
            )

    return 0


async def cmd_monitor(args: argparse.Namespace) -> int:
    """Main monitoring loop."""
    # Load config file if specified
    load_config(args.config)

    monitor_codex = not args.kimi_only
    monitor_kimi = not args.codex_only

    notifier = XiaoAiNotifier(verbose=args.verbose)
    await notifier.login()

    # Initialize offsets for both session types
    offsets: dict[Path, int] = {}

    if monitor_codex:
        codex_dir = Path(os.path.expanduser(str(CODEX_SESSIONS_DIR)))
        offsets.update(init_offsets(codex_dir, args.replay_existing))
        print(f"[mibe] watching codex: {codex_dir}")

    if monitor_kimi:
        kimi_dir = Path(os.path.expanduser(str(KIMI_SESSIONS_DIR)))
        # Kimi uses wire.jsonl files in subdirectories
        for p in list_session_files(kimi_dir, "wire.jsonl"):
            if p not in offsets:
                offsets[p] = 0 if args.replay_existing == "all" else p.stat().st_size
        print(f"[mibe] watching kimi: {kimi_dir}")

    print("[mibe] press Ctrl+C to stop")

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        print("\n[mibe] signal received, restoring volume and exiting...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    try:
        while not stop_event.is_set():
            # Monitor Codex
            if monitor_codex:
                codex_dir = Path(os.path.expanduser(str(CODEX_SESSIONS_DIR)))
                for path in list_session_files(codex_dir, "*.jsonl"):
                    if path not in offsets:
                        offsets[path] = 0
                    await read_new_lines(path, offsets, notifier, process_codex_event)

            # Monitor Kimi
            if monitor_kimi:
                kimi_dir = Path(os.path.expanduser(str(KIMI_SESSIONS_DIR)))
                for path in list_session_files(kimi_dir, "wire.jsonl"):
                    if path not in offsets:
                        offsets[path] = 0
                    await read_new_lines(path, offsets, notifier, process_kimi_event)

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass
    finally:
        await notifier.restore_volume()
        await notifier.close()
        print("[mibe] stopped")

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "login":
        return asyncio.run(cmd_login())
    elif args.command == "monitor":
        return asyncio.run(cmd_monitor(args))
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
