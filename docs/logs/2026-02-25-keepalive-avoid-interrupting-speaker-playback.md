## 2026-02-25 - Keepalive avoids interrupting speaker playback

### Requirement Background
- `mibe` uses periodic silent TTS keepalive to keep XiaoAi's light on during long-running tasks.
- When the speaker is being used for normal voice Q&A or playback, the keepalive TTS can arrive mid-playback and interrupt the current audio.
- The expected behavior is to preserve the keepalive feature without interrupting normal speaker usage.

### Solution Design
- Add playback-state detection to `XiaoAiNotifier` via a new `is_playing()` method.
- Before sending keepalive TTS, check current playback state and only send when the device is clearly idle.
- Use a conservative fallback:
  - playing -> skip keepalive
  - unknown status / API parse failure -> skip keepalive
  - idle -> send keepalive
- Keep normal business notifications unchanged (Codex/Kimi start/end/confirmation prompts still broadcast as before).

### Implementation Process
- Added `XiaoAiNotifier.is_playing()` to query `player_get_status`, parse `data.info`, and infer playback state from compatible status fields.
- Added `_keepalive_tick()` to isolate single keepalive-cycle logic and make behavior easier to test.
- Updated `_keepalive_loop()` to call `_keepalive_tick()` instead of unconditionally sending silent TTS.
- Added unit tests covering:
  - `is_playing()` returning `True` / `False` / `None`
  - keepalive tick behavior for playing / unknown / idle states
