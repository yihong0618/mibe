# mibe

[![CI](https://github.com/yihong0618/mibe/actions/workflows/ci.yml/badge.svg)](https://github.com/yihong0618/mibe/actions/workflows/ci.yml)

Monitor Codex / Kimi session logs and broadcast task status via Xiaomi smart speaker.

## Notes

Voice broadcast content can be customized through configuration file.

## Quick Start

Refer to the project [MiService](https://github.com/yihong0618/MiService)

```bash
# Install dependencies
uv venv
uv sync

# Set environment variables
export MI_USER="Your Xiaomi Account"
export MI_PASS="Your Xiaomi Password"
export MI_DID="Device miotDID"  # Optional, uses first device if not set


# Verify login & list devices
uv run python mibe.py login

# Start monitoring
uv run python mibe.py monitor
```

## Subcommands

| Command | Description |
|---------|-------------|
| `login` | Test login, list available devices |
| `monitor` | Monitor Codex/Kimi logs and broadcast |

`monitor` optional arguments:

- `--replay-existing {none,latest,all}` — Replay existing logs on startup (default: `none`)
- `--verbose` — Verbose logging
- `--codex-only` — Monitor Codex sessions only
- `--kimi-only` — Monitor Kimi sessions only
- `-c, --config PATH` — Specify configuration file path

## Behavior

| Event | Broadcast | Action |
|-------|-----------|--------|
| Codex `task_started` | codex started | Mute after broadcast, send silent TTS periodically to keep light on |
| Codex `task_complete` | codex completed | Restore volume, then broadcast |
| Codex `turn_aborted` | codex aborted | Restore volume, then broadcast |
| Codex `request_user_input` (function call) | codex needs your input + question text | Stop keepalive, restore volume, broadcast, and keep volume unmuted while waiting for user response |
| Codex `function_call` (new-format escalation confirmation: `sandbox_permissions=require_escalated`) | codex needs your input + approval reason/command summary | Stop keepalive, restore volume, broadcast, and keep volume unmuted while waiting for user response |
| Kimi `TurnBegin` | kimi started | Mute after broadcast, send silent TTS periodically to keep light on |
| Kimi `TurnEnd` | kimi completed | Restore volume, then broadcast |

Volume is automatically restored on exit (Ctrl+C / SIGTERM).
When Codex asks via `request_user_input`, or requests an escalation confirmation via `exec_command`, mibe broadcasts a short confirmation summary.
For multiple questions, it broadcasts the count plus the first question only.

## Configuration File

Supports customization of broadcast messages and settings via TOML configuration file.

Configuration file search paths (in priority order):
1. Path specified by `-c, --config`
2. `./config.toml`
3. `~/.config/mibe/config.toml`

### Example Configuration

```toml
[messages]
# Codex related messages
codex_started = "codex started"
codex_complete = "codex completed"
codex_aborted = "codex aborted"
codex_input_required = "codex needs your input"
# Template placeholders: {alert_text}, {first_question}
codex_input_single_template = "{alert_text}. {first_question}"
# Template placeholders: {alert_text}, {question_count}, {first_question}
codex_input_multi_template = "{alert_text}. There are {question_count} questions. First question: {first_question}"
codex_input_fallback_question = "Please check the question in the terminal"

# Kimi related messages
kimi_started = "kimi started"
kimi_complete = "kimi completed"

[settings]
# Silence duration for Kimi completion detection (seconds)
kimi_completion_silence = 2.0
# Max words from the first question to read in TTS (CJK/English-compatible count: English chunks + Han chars)
codex_input_question_max_words = 160
```

### Codex Input Prompt Templates

When mibe detects a Codex function call that requires user confirmation, it broadcasts a prompt.

- Triggers:
  - `response_item -> function_call(name="request_user_input")`
  - `response_item -> function_call(*)` with `arguments.sandbox_permissions == "require_escalated"` (new-format escalation confirmation)
- Template placeholders: `{alert_text}`, `{question_count}`, `{first_question}`
- `request_user_input` multi-question behavior: broadcast summary of the first question (plus total count)
- New-format escalation approval behavior: prefer `justification`, otherwise read a command summary from `cmd`
- Long questions are truncated using `codex_input_question_max_words` (CJK/English-compatible count: English chunks + Han chars), and then users can read the full text in the terminal

Copy `config.toml.example` as a starting point:

```bash
cp config.toml.example config.toml
# Edit config.toml to customize your broadcast messages
```

## Thanks

- yetone
