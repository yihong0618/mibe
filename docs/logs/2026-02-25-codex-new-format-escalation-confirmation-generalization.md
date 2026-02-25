## 2026-02-25 - Generalize Codex new-format escalation confirmation alerts

### Requirement Background
- `mibe` already broadcasts audio prompts for Codex `request_user_input` and for `exec_command` when `arguments.sandbox_permissions == "require_escalated"`.
- In real Codex session JSONL output, the user-confirmation semantics come from the new-format escalation field (`sandbox_permissions=require_escalated`), not from a single fixed tool name.
- If the implementation stays hardcoded to `exec_command`, future new-format function calls with the same escalation requirement may be missed, and users would not receive an audio confirmation prompt at the moment Codex is waiting for approval.
- The required behavior is to keep using the new-format field as the source of truth, trigger audio prompts for any `function_call` carrying `sandbox_permissions=require_escalated`, and explicitly avoid adding compatibility logic for old formats in this iteration.

### Solution Design
- Keep `request_user_input` as a dedicated path because it carries different payload semantics and a different summary strategy (question list/count).
- Generalize escalation-confirmation detection from `exec_command`-specific matching to a semantic rule:
  - `payload.type == "function_call"`
  - parsed JSON `arguments.sandbox_permissions == "require_escalated"`
- Continue using the existing confirmation TTS template (`codex_input_single_template`) and alert phrase (`codex_input_required`) for a consistent user experience.
- Keep new-format-only parsing assumptions:
  - prompt extraction priority: `justification` -> `cmd` -> generic fallback message
  - no support for old-format fields such as `command` or `with_escalated_permissions`
- Update logging to a semantic label (`codex escalation_confirmation`) and include the tool name for observability/debugging.

### Implementation Process
- Renamed and generalized the escalation TTS builder in `mibe.py` so it no longer hardcodes `payload.name == "exec_command"`.
- Renamed and generalized the corresponding handler to process any new-format escalated `function_call`.
- Kept `process_codex_event()` response-item flow order unchanged:
  - handle `request_user_input`
  - handle escalation confirmation
- Added unit tests covering:
  - existing `exec_command + require_escalated` behavior (no regression)
  - non-escalated `exec_command` ignored
  - future tool name with `sandbox_permissions=require_escalated` triggers confirmation
  - fallback behavior from `justification` to `cmd` to generic prompt
  - invalid `arguments` ignored
- Added an integration test verifying JSONL ingestion for a non-`exec_command` new-format escalated `function_call`.
- Updated `README.md` and `README_EN.md` to describe the trigger as any new-format `function_call` with `arguments.sandbox_permissions == "require_escalated"`.
