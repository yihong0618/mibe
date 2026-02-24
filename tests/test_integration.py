#!/usr/bin/env python3
"""Integration tests for mibe module."""

import json
from pathlib import Path
from unittest import mock

import pytest

import mibe


class TestEndToEnd:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_full_codex_flow(self, tmp_path):
        """Test full Codex session flow."""
        path = tmp_path / "codex.jsonl"
        # Create a mock notifier
        mock_notifier = mock.AsyncMock()
        mock_notifier.start_keepalive = mock.Mock()

        # Simulate task_started event
        start_event = {
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": 1},
        }
        await mibe.process_codex_event(start_event, path, mock_notifier)

        # Verify start behavior
        mock_notifier.speak.assert_called_with(mibe.MESSAGES["codex_started"])
        mock_notifier.save_and_mute.assert_called_once()
        mock_notifier.start_keepalive.assert_called_once()

        # Reset mock for complete event
        mock_notifier.reset_mock()

        # Simulate task_complete event
        complete_event = {
            "type": "event_msg",
            "payload": {"type": "task_complete", "turn_id": 1},
        }
        await mibe.process_codex_event(complete_event, path, mock_notifier)

        # Verify complete behavior
        mock_notifier.stop_keepalive.assert_called_once()
        mock_notifier.restore_volume.assert_called_once()
        mock_notifier.speak.assert_called_with(mibe.MESSAGES["codex_complete"])

    @pytest.mark.asyncio
    async def test_full_kimi_flow(self, tmp_path):
        """Test full Kimi session flow."""
        path = tmp_path / "session" / "wire.jsonl"
        path.parent.mkdir(parents=True)

        # Clear state
        mibe.KIMI_SESSION_STATES.clear()

        # Create a mock notifier
        mock_notifier = mock.AsyncMock()
        mock_notifier.start_keepalive = mock.Mock()

        # Simulate TurnBegin
        begin_event = {"message": {"type": "TurnBegin"}}
        await mibe.process_kimi_event(begin_event, path, mock_notifier)

        # Verify start behavior
        mock_notifier.speak.assert_called_with(mibe.MESSAGES["kimi_started"])
        mock_notifier.save_and_mute.assert_called_once()
        mock_notifier.start_keepalive.assert_called_once()

        # Reset mock
        mock_notifier.reset_mock()

        # Simulate TurnEnd
        end_event = {"message": {"type": "TurnEnd"}}
        await mibe.process_kimi_event(end_event, path, mock_notifier)

        # Verify end behavior
        mock_notifier.stop_keepalive.assert_called_once()
        mock_notifier.restore_volume.assert_called_once()
        mock_notifier.speak.assert_called_with(mibe.MESSAGES["kimi_complete"])

        # Cleanup
        mibe.KIMI_SESSION_STATES.clear()


class TestConfigIntegration:
    """Integration tests for configuration loading."""

    def test_config_message_override(self, tmp_path):
        """Test that config properly overrides default messages."""
        config_file = tmp_path / "test_config.toml"
        config_file.write_text("""
[messages]
codex_started = "开始工作"
codex_complete = "工作完成"
codex_aborted = "工作中断"
kimi_started = "Kimi 启动"
kimi_complete = "Kimi 完成"
""")

        # Save original messages
        original_messages = mibe.MESSAGES.copy()

        try:
            # Reset to defaults and load config
            mibe.MESSAGES = mibe.DEFAULT_MESSAGES.copy()
            mibe.load_config(str(config_file))

            # Verify overrides
            assert mibe.MESSAGES["codex_started"] == "开始工作"
            assert mibe.MESSAGES["codex_complete"] == "工作完成"
            assert mibe.MESSAGES["kimi_started"] == "Kimi 启动"
        finally:
            # Restore original messages
            mibe.MESSAGES = original_messages


class TestFileMonitoring:
    """Integration tests for file monitoring."""

    def test_init_offsets_replay_strategies(self, tmp_path):
        """Test different replay strategies."""
        # Create test files
        file1 = tmp_path / "session1.jsonl"
        file2 = tmp_path / "session2.jsonl"
        file1.write_text('{"type": "test"}\n')
        file2.write_text('{"type": "test"}\n{"type": "test2"}\n')

        # Test replay=none - should start at end of file
        offsets_none = mibe.init_offsets(tmp_path, "none")
        assert offsets_none[file1] == file1.stat().st_size
        assert offsets_none[file2] == file2.stat().st_size

        # Test replay=all - should start at beginning
        offsets_all = mibe.init_offsets(tmp_path, "all")
        assert offsets_all[file1] == 0
        assert offsets_all[file2] == 0

        # Test replay=latest - only latest file should start at 0
        offsets_latest = mibe.init_offsets(tmp_path, "latest")
        # Latest file should have offset 0, others at end
        latest_file = max([file1, file2], key=lambda p: p.stat().st_mtime_ns)
        assert offsets_latest[latest_file] == 0
        other_file = file1 if latest_file == file2 else file2
        assert offsets_latest[other_file] == other_file.stat().st_size

    @pytest.mark.asyncio
    async def test_read_new_lines_processes_codex_request_user_input(self, tmp_path):
        """Test file reader triggers Codex request_user_input TTS."""
        path = tmp_path / "session.jsonl"
        event = {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "request_user_input",
                "arguments": json.dumps(
                    {"questions": [{"question": "请确认是否继续部署？"}]}
                ),
                "call_id": "call_integration",
            },
        }
        path.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")

        offsets: dict[Path, int] = {}
        mock_notifier = mock.AsyncMock()

        await mibe.read_new_lines(
            path, offsets, mock_notifier, mibe.process_codex_event
        )

        mock_notifier.speak.assert_called_once()
        speak_text = mock_notifier.speak.call_args.args[0]
        assert "请确认是否继续部署" in speak_text
