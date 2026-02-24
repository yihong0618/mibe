## 2026-02-25 - Codex TTS truncation uses CJK/English-compatible tokens

### Requirement Background
- The previous `max_words` truncation implementation split text only by whitespace.
- This works for English prompts but fails for long Chinese text without spaces, which would not be truncated as expected.
- The expected behavior is to make the truncation limit work for both English and Chinese content.

### Solution Design
- Keep the setting name `codex_input_question_max_words` and default value `160`.
- Change truncation tokenization to a CJK/English-compatible strategy:
  - count each Han character as one token
  - count each contiguous non-whitespace non-Han chunk as one token (English words, flags, paths, etc.)
- Preserve the original text form as much as possible by truncating on token boundaries using regex match positions.
- Keep the existing suffix behavior (`，后续请看终端`) unchanged.

### Implementation Process
- Updated `_sanitize_codex_question_text()` in `mibe.py` to use regex-based token matching instead of whitespace split.
- Added a shared regex constant for CJK/English-compatible token detection.
- Added/updated tests in `tests/test_mibe.py` for:
  - English multi-word truncation
  - Chinese no-space truncation
- Updated `config.toml.example`, `README.md`, and `README_EN.md` to clarify that `codex_input_question_max_words` uses a CJK/English-compatible token count.
