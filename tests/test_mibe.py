#!/usr/bin/env python3
"""Tests for mibe module."""

from pathlib import Path
from unittest import mock

import pytest

import mibe


class TestParseSimpleToml:
    """Tests for _parse_simple_toml function."""

    def test_parse_empty(self):
        assert mibe._parse_simple_toml("") == {}

    def test_parse_comments(self):
        content = """# This is a comment
[section]
# Another comment
key = "value"
"""
        result = mibe._parse_simple_toml(content)
        assert result == {"section": {"key": "value"}}

    def test_parse_multiple_sections(self):
        content = """
[messages]
codex_started = "started"
codex_complete = "done"

[settings]
kimi_completion_silence = 2.0
"""
        result = mibe._parse_simple_toml(content)
        assert result["messages"]["codex_started"] == "started"
        assert result["messages"]["codex_complete"] == "done"
        assert result["settings"]["kimi_completion_silence"] == "2.0"


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_nonexistent_config(self):
        # Should not raise, returns empty dict
        result = mibe.load_config("/nonexistent/path.toml")
        assert result == {}

    def test_load_config_updates_messages(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text("""
[messages]
codex_started = "custom start"
codex_complete = "custom complete"
""")
        # Reset MESSAGES to default before test
        mibe.MESSAGES = mibe.DEFAULT_MESSAGES.copy()

        mibe.load_config(str(config_file))

        assert mibe.MESSAGES["codex_started"] == "custom start"
        assert mibe.MESSAGES["codex_complete"] == "custom complete"

    def test_load_config_updates_settings(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text("""
[settings]
kimi_completion_silence = 5.0
""")
        original_value = mibe.SETTINGS["kimi_completion_silence"]

        try:
            mibe.load_config(str(config_file))
            assert mibe.SETTINGS["kimi_completion_silence"] == 5.0
        finally:
            # Restore original value
            mibe.SETTINGS["kimi_completion_silence"] = original_value


class TestListSessionFiles:
    """Tests for list_session_files function."""

    def test_list_nonexistent_dir(self):
        result = mibe.list_session_files(Path("/nonexistent"))
        assert result == []

    def test_list_jsonl_files(self, tmp_path):
        # Create some jsonl files
        (tmp_path / "session1.jsonl").write_text("")
        (tmp_path / "session2.jsonl").write_text("")
        (tmp_path / "other.txt").write_text("")

        result = mibe.list_session_files(tmp_path)

        assert len(result) == 2
        assert all(p.suffix == ".jsonl" for p in result)


class TestGetEventType:
    """Tests for _get_event_type function."""

    def test_simple_event(self):
        msg = {"type": "TurnBegin"}
        assert mibe._get_event_type(msg) == "TurnBegin"

    def test_nested_subagent_event(self):
        msg = {"type": "SubagentEvent", "payload": {"event": {"type": "TurnEnd"}}}
        assert mibe._get_event_type(msg) == "TurnEnd"

    def test_no_type(self):
        msg = {"data": "something"}
        assert mibe._get_event_type(msg) is None


class TestKimiSessionState:
    """Tests for KimiSessionState class."""

    def test_initial_state(self):
        state = mibe.KimiSessionState()
        assert state.active is False
        assert state.last_activity == 0.0
        assert state.completion_timer is None


class TestInitOffsets:
    """Tests for init_offsets function."""

    def test_replay_none(self, tmp_path):
        # Create a file with content
        test_file = tmp_path / "test.jsonl"
        test_file.write_text("line1\nline2\n")

        offsets = mibe.init_offsets(tmp_path, "none", "*.jsonl")

        assert offsets[test_file] == test_file.stat().st_size

    def test_replay_all(self, tmp_path):
        test_file = tmp_path / "test.jsonl"
        test_file.write_text("line1\nline2\n")

        offsets = mibe.init_offsets(tmp_path, "all", "*.jsonl")

        assert offsets[test_file] == 0


class TestProcessCodexEvent:
    """Tests for process_codex_event function."""

    @pytest.mark.asyncio
    async def test_ignore_non_event_msg(self, tmp_path):
        event = {"type": "other", "payload": {"type": "task_started"}}
        path = tmp_path / "codex.jsonl"

        mock_notifier = mock.AsyncMock()
        await mibe.process_codex_event(event, path, mock_notifier)

        mock_notifier.speak.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_started(self, tmp_path):
        event = {
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": 123},
        }
        path = tmp_path / "codex.jsonl"

        mock_notifier = mock.AsyncMock()
        mock_notifier.start_keepalive = mock.Mock()
        await mibe.process_codex_event(event, path, mock_notifier)

        mock_notifier.speak.assert_called_once()
        mock_notifier.save_and_mute.assert_called_once()
        mock_notifier.start_keepalive.assert_called_once()

    @pytest.mark.asyncio
    async def test_task_complete(self, tmp_path):
        event = {
            "type": "event_msg",
            "payload": {"type": "task_complete", "turn_id": 123},
        }
        path = tmp_path / "codex.jsonl"

        mock_notifier = mock.AsyncMock()
        await mibe.process_codex_event(event, path, mock_notifier)

        mock_notifier.stop_keepalive.assert_called_once()
        mock_notifier.restore_volume.assert_called_once()
        mock_notifier.speak.assert_called_once()

    @pytest.mark.asyncio
    async def test_codex_request_user_input_single_question_speaks_with_template(
        self, tmp_path
    ):
        path = tmp_path / "codex.jsonl"
        event = {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "request_user_input",
                "arguments": '{"questions":[{"question":"你希望修复做到哪一层？"}]}',
                "call_id": "call_1",
            },
        }

        mock_notifier = mock.AsyncMock()
        mock_notifier.start_keepalive = mock.Mock()

        await mibe.process_codex_event(event, path, mock_notifier)

        mock_notifier.stop_keepalive.assert_called_once()
        mock_notifier.restore_volume.assert_called_once()
        mock_notifier.speak.assert_called_once()
        speak_text = mock_notifier.speak.call_args.args[0]
        assert mibe.MESSAGES["codex_input_required"] in speak_text
        assert "你希望修复做到哪一层" in speak_text
        mock_notifier.save_and_mute.assert_not_called()
        mock_notifier.start_keepalive.assert_not_called()

    @pytest.mark.asyncio
    async def test_codex_request_user_input_multi_question_uses_count_and_first(
        self, tmp_path
    ):
        path = tmp_path / "codex.jsonl"
        event = {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "request_user_input",
                "arguments": (
                    '{"questions":['
                    '{"question":"第一个问题是什么？"},'
                    '{"question":"第二个问题是什么？"}'
                    "]}"
                ),
                "call_id": "call_2",
            },
        }

        mock_notifier = mock.AsyncMock()
        await mibe.process_codex_event(event, path, mock_notifier)

        speak_text = mock_notifier.speak.call_args.args[0]
        assert "2个问题" in speak_text
        assert "第一个问题是什么" in speak_text
        assert "第二个问题是什么" not in speak_text

    @pytest.mark.asyncio
    async def test_codex_request_user_input_uses_fallback_on_bad_arguments(
        self, tmp_path
    ):
        path = tmp_path / "codex.jsonl"
        event = {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "request_user_input",
                "arguments": "{not-json",
                "call_id": "call_3",
            },
        }

        mock_notifier = mock.AsyncMock()
        await mibe.process_codex_event(event, path, mock_notifier)

        speak_text = mock_notifier.speak.call_args.args[0]
        assert mibe.MESSAGES["codex_input_fallback_question"] in speak_text

    @pytest.mark.asyncio
    async def test_codex_request_user_input_truncates_long_question(self, tmp_path):
        path = tmp_path / "codex.jsonl"
        long_question = "A" * 120
        event = {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "request_user_input",
                "arguments": ('{"questions":[{"question":"' + long_question + '"}]}'),
                "call_id": "call_4",
            },
        }

        mock_notifier = mock.AsyncMock()
        original_max = mibe.SETTINGS["codex_input_question_max_chars"]
        try:
            mibe.SETTINGS["codex_input_question_max_chars"] = 20
            await mibe.process_codex_event(event, path, mock_notifier)
        finally:
            mibe.SETTINGS["codex_input_question_max_chars"] = original_max

        speak_text = mock_notifier.speak.call_args.args[0]
        assert "后续请看终端" in speak_text

    @pytest.mark.asyncio
    async def test_codex_other_function_call_ignored(self, tmp_path):
        path = tmp_path / "codex.jsonl"
        event = {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "some_other_tool",
                "arguments": "{}",
            },
        }

        mock_notifier = mock.AsyncMock()
        await mibe.process_codex_event(event, path, mock_notifier)

        mock_notifier.speak.assert_not_called()


class TestProcessKimiEvent:
    """Tests for process_kimi_event function."""

    @pytest.mark.asyncio
    async def test_turn_begin(self, tmp_path):
        path = tmp_path / "test.jsonl"
        event = {"message": {"type": "TurnBegin"}}

        mock_notifier = mock.AsyncMock()
        mock_notifier.start_keepalive = mock.Mock()

        # Clear any existing state
        mibe.KIMI_SESSION_STATES.clear()

        await mibe.process_kimi_event(event, path, mock_notifier)

        mock_notifier.speak.assert_called_once()
        mock_notifier.save_and_mute.assert_called_once()
        mock_notifier.start_keepalive.assert_called_once()

        # Cleanup
        mibe.KIMI_SESSION_STATES.clear()

    @pytest.mark.asyncio
    async def test_turn_end(self, tmp_path):
        path = tmp_path / "test.jsonl"

        # Pre-set active state
        mibe.KIMI_SESSION_STATES[path] = mibe.KimiSessionState()
        mibe.KIMI_SESSION_STATES[path].active = True

        event = {"message": {"type": "TurnEnd"}}

        mock_notifier = mock.AsyncMock()
        await mibe.process_kimi_event(event, path, mock_notifier)

        mock_notifier.stop_keepalive.assert_called_once()
        mock_notifier.restore_volume.assert_called_once()
        mock_notifier.speak.assert_called_once()

        # Cleanup
        mibe.KIMI_SESSION_STATES.clear()


class TestXiaoAiNotifier:
    """Tests for XiaoAiNotifier class."""

    @pytest.mark.asyncio
    async def test_init(self):
        notifier = mibe.XiaoAiNotifier(verbose=True)
        assert notifier.verbose is True
        assert notifier._session is None


class TestReadNewLines:
    """Tests for read_new_lines function."""

    @pytest.mark.asyncio
    async def test_read_new_content(self, tmp_path):
        test_file = tmp_path / "test.jsonl"
        test_file.write_text('{"type": "test"}\n')

        offsets = {}
        mock_notifier = mock.AsyncMock()

        async def processor(event, path, notifier):
            pass

        await mibe.read_new_lines(test_file, offsets, mock_notifier, processor)

        assert offsets[test_file] == test_file.stat().st_size


class TestBuildParser:
    """Tests for build_parser function."""

    def test_has_subcommands(self):
        parser = mibe.build_parser()

        # Should have login and monitor subcommands
        subparsers = parser._subparsers
        assert subparsers is not None

    def test_parse_login(self):
        parser = mibe.build_parser()
        args = parser.parse_args(["login"])
        assert args.command == "login"

    def test_parse_monitor(self):
        parser = mibe.build_parser()
        args = parser.parse_args(["monitor"])
        assert args.command == "monitor"
        assert args.replay_existing == "none"

    def test_parse_monitor_with_options(self):
        parser = mibe.build_parser()
        args = parser.parse_args(
            [
                "monitor",
                "--replay-existing",
                "all",
                "--verbose",
                "--codex-only",
                "-c",
                "/path/to/config.toml",
            ]
        )
        assert args.command == "monitor"
        assert args.replay_existing == "all"
        assert args.verbose is True
        assert args.codex_only is True
        assert args.config == "/path/to/config.toml"
