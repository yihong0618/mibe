## 2026-02-24 - Codex exec_command escalation confirmation handling

### Requirement Background
- Codex session logs can include `response_item -> function_call(name="exec_command")` with `arguments.sandbox_permissions == "require_escalated"`.
- This is a user confirmation step (approval for elevated command execution), and should be handled like `request_user_input`.
- Previously, `mibe` only announced `request_user_input`, so escalation confirmations could be missed.

### Solution Design
- Extend Codex `response_item -> function_call` handling with an additional branch for `exec_command`.
- Only trigger confirmation flow when `arguments.sandbox_permissions == "require_escalated"` to avoid false positives from normal commands.
- Reuse the same notification strategy as `request_user_input` (stop keepalive, restore volume, then speak) to keep user experience consistent.
- TTS text selection strategy for escalation prompts:
  - prefer `arguments.justification`
  - fallback to sanitized `arguments.cmd`
  - fallback to generic terminal reminder if both are unavailable

### Implementation Process
- Added `exec_command` escalation event parsing and TTS builder logic in `mibe.py`.
- Added a dedicated handler to run the same confirmation notification flow used by `request_user_input`.
- Wired the new handler into Codex `response_item` processing.
- Added unit tests for triggered and ignored cases (`require_escalated` vs non-escalated).
- Added file-monitor integration coverage for JSONL ingestion of escalation confirmation events.
- Updated `README.md`, `README_EN.md`, and `AGENTS.md` to document the new confirmation trigger rule.
