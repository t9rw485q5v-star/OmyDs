import copy
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from omyds import security, storage
from omyds.app import conversation, run_app
from omyds.chat import run_turn
from omyds.context import assistant_message, build_context, validate_messages, ContextError
from omyds.tool_executor import ToolExecutor
from omyds.permissions import Mode
from omyds.tools import AVAILABLE_TOOLS
from omyds.tools.write_file import WriteFileTool
from omyds.tools.run_command import RunCommandTool


def call(name="read_file", arguments=None, id="t1"):
    return {"id": id, "type": "function", "function": {
        "name": name, "arguments": json.dumps({**(arguments or {"path": "a.txt"}), "purpose": "测试读取", "impact": "读取指定测试文件"})}}


def reply(calls=None, content=None, reasoning=""):
    return SimpleNamespace(choices=[SimpleNamespace(message={
        "role": "assistant", "content": content, "reasoning_content": reasoning,
        **({"tool_calls": calls} if calls else {})
    })])


class UI:
    def __init__(self, inputs=(), approval=True):
        self.inputs = iter(inputs)
        self.approval = approval
        self.confirmations = []
        self.output = []
    def prompt(self, _):
        return next(self.inputs)
    def say(self, text, style=None):
        self.output.append(text)
    answer = say
    def busy(self):
        return nullcontext()
    def history(self, messages):
        pass
    def show_logo(self):
        pass
    def set_mode(self, mode, web_enabled=False):
        self.mode = mode
        self.web_enabled = web_enabled
    def show_permissions(self, mode, root, detailed=False, web_enabled=False):
        self.mode = mode
    def describe_tool(self, *args, **kwargs):
        pass
    def help(self):
        pass
    def confirm_danger(self, root):
        return self.approval
    def confirm_tool(self, *args, **kwargs):
        self.confirmations.append((copy.deepcopy(args), kwargs))
        return self.approval


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.patches = [
            patch.object(security, "ALLOWED_ROOT", self.workspace),
            patch.object(storage, "SESSIONS_DIR", self.root / "sessions"),
            patch.object(storage, "MEMORY_FILE", self.root / "memory.md")
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_context_keeps_whole_active_turn(self):
        messages = [{"role": "system", "content": "s"},
                    {"role": "user", "content": "old" * 500},
                    {"role": "assistant", "content": "old answer"},
                    {"role": "user", "content": "now"},
                    {"role": "assistant", "content": None, "tool_calls": [call()]},
                    {"role": "tool", "tool_call_id": "t1", "content": "x" * 5000}]
        result = build_context(messages, 100)
        self.assertEqual(result[1]["content"], "now")
        self.assertEqual(len(result), 4)
        validate_messages(result)

    def test_orphan_and_incomplete_rejected(self):
        for messages in (
            [{"role": "tool", "tool_call_id": "t1", "content": "x"}],
            [{"role": "assistant", "tool_calls": [call()]}]
        ):
            with self.assertRaises(ContextError):
                build_context(messages)

    def test_thinking_multiple_tools_then_next_turn(self):
        client = Mock()
        client.chat.completions.create.side_effect = [
            reply([call(id="t1"), call(id="t2")], reasoning="reason-one"),
            reply(content="done", reasoning="reason-two"),
            reply(content="next", reasoning="reason-three")]
        ui = UI()
        tool = Mock(name="fake")
        tool.name = "read_file"
        tool.description = "read"
        tool.parameters = {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}
        tool.run.return_value = "result"
        ex = ToolExecutor([tool], ui)
        messages = [{"role": "system", "content": "s"}]
        self.assertTrue(run_turn(client, {"model": "test"}, messages, ex, ui, "go"))
        self.assertTrue(run_turn(client, {"model": "test"}, messages, ex, ui, "again"))
        sent = client.chat.completions.create.call_args_list[-1].kwargs["messages"]
        self.assertEqual([m["reasoning_content"] for m in sent if m["role"] == "assistant"],
                         ["reason-one", "reason-two"])
        self.assertEqual(tool.run.call_count, 2)
        validate_messages(sent)

    def test_empty_reasoning_is_preserved(self):
        client = Mock()
        client.chat.completions.create.side_effect = [
            reply([call("unknown")], reasoning=""), reply(content="done")]
        messages = []
        run_turn(client, {"model": "test"}, messages, ToolExecutor([], UI()), UI(), "go")
        sent = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(next(m for m in sent if m["role"] == "assistant")["reasoning_content"], "")

    def test_api_failure_retry_does_not_repeat_write(self):
        client = Mock()
        client.chat.completions.create.side_effect = [
            reply([call("write_file", {"path": "a.txt", "content": "x", "mode": "append"})]),
            RuntimeError("simulated 400"),
            reply(content="done")]
        messages = []
        ui = UI()
        executor = ToolExecutor(AVAILABLE_TOOLS, ui)
        self.assertFalse(run_turn(client, {"model": "test"}, messages, executor, ui, "go"))
        self.assertEqual(messages[-1]["role"], "tool")
        self.assertTrue(run_turn(client, {"model": "test"}, messages, executor, ui))
        self.assertEqual((self.workspace / "a.txt").read_text(), "x")

    def test_outside_permission_is_one_time_and_path_stable(self):
        path = self.root / "outside.txt"
        path.write_text("outside")
        ui = UI()
        ex = ToolExecutor(AVAILABLE_TOOLS, ui)
        for _ in range(2):
            self.assertEqual(ex.execute(call(arguments={"path": "../outside.txt"})), "outside")
        self.assertEqual(len(ui.confirmations), 2)
        self.assertEqual(ui.confirmations[0][0][1]["path"], str(path))

    def test_denial_never_writes(self):
        ui = UI(approval=False)
        ex = ToolExecutor(AVAILABLE_TOOLS, ui)
        result = ex.execute(call("write_file", {"path": "../outside.txt", "content": "x"}))
        self.assertIn("拒绝", result)
        self.assertFalse((self.root / "outside.txt").exists())

    def test_internal_write_no_prompt_and_temp_collision_safe(self):
        (self.workspace / "a.tmp").write_text("keep")
        ui = UI()
        ex = ToolExecutor(AVAILABLE_TOOLS, ui)
        ex.execute(call("write_file", {"path": "a.txt", "content": "new"}))
        self.assertEqual(ui.confirmations, [])
        self.assertEqual((self.workspace / "a.txt").read_text(), "new")
        self.assertEqual((self.workspace / "a.tmp").read_text(), "keep")

    def test_authorized_retry_failure_becomes_tool_result(self):
        tool = Mock()
        tool.name = "read_file"
        tool.parameters = {"properties": {"path": {"type": "string"}}}
        tool.run.side_effect = RuntimeError("retry failed")
        result = ToolExecutor([tool], UI()).execute(call(arguments={"path": "../outside.txt"}))
        self.assertIn("retry failed", result)

    def test_bad_json_and_non_object(self):
        ex = ToolExecutor(AVAILABLE_TOOLS, UI())
        for value in ("{", "[]", "null"):
            item = call()
            item["function"]["arguments"] = value
            self.assertIn("工具执行错误", ex.execute(item))

    def test_interrupt_completes_tool_results(self):
        class InterruptUI(UI):
            def confirm_tool(self, *args, **kwargs):
                raise KeyboardInterrupt()
        ui = InterruptUI()
        client = Mock()
        client.chat.completions.create.return_value = reply([
            call("run_command", {"command": "echo hi"}, id="t1"),
            call("write_file", {"path": "a.txt", "content": "x"}, id="t2")])
        messages = []
        self.assertFalse(run_turn(client, {"model": "test"}, messages,
                                  ToolExecutor(AVAILABLE_TOOLS, ui, Mode.ASK), ui, "go"))
        validate_messages(messages)
        self.assertFalse((self.workspace / "a.txt").exists())
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_return_save_reload_and_exit(self):
        client = Mock()
        client.chat.completions.create.return_value = reply(content="hello")
        ui = UI(["0", "hi", "/return", "y", "saved", "1", "/history", "exit"])
        with patch("omyds.app.get_system_prompt", return_value="system"), \
             patch("omyds.app.get_greeting", return_value=""):
            run_app({"api": {"model": "test"}}, client, ui)
        messages = storage.load_session("saved")
        self.assertEqual([m["role"] for m in messages], ["user", "assistant"])
        self.assertIn("reasoning_content", messages[-1])

    def test_cancel_return_keeps_conversation(self):
        ui = UI(["hello", "/return", "c", "exit", "n"])
        client = Mock()
        client.chat.completions.create.return_value = reply(content="hello")
        messages = []
        self.assertEqual(conversation(ui, client, {"model": "test"}, messages, None), "exit")
        self.assertEqual(len(messages), 2)

    def test_mount_and_force_protection(self):
        for path in ("/", "/etc", str(security.BASE_DIR), str(self.root / "missing")):
            with self.assertRaises((PermissionError, ValueError)):
                security.set_workdir(path)
        with self.assertRaises(PermissionError):
            security.validate_path("/etc/passwd", allow_outside=True)
        self.assertIn("权限", WriteFileTool().run({"path": "/etc/test", "content": "x"}, force=True))

    def test_session_name_and_reasoning_roundtrip(self):
        with self.assertRaises(ValueError):
            storage.save_session("../escape", [])
        messages = [{"role": "assistant", "content": "x", "reasoning_content": "r"}]
        storage.save_session("test", messages)
        self.assertEqual(storage.load_session("test"), messages)

    def test_bwrap_exit_status_and_environment(self):
        with patch("omyds.tools.run_command.run_process") as run, \
             patch("omyds.tools.run_command.shutil.which", return_value="/usr/bin/bwrap"):
            run.return_value = "退出码: 1\n（无输出）"
            result = RunCommandTool().run({"command": "false"})
            argv = run.call_args.args[0]
        self.assertIn("退出码: 1", result)
        self.assertIn("--clearenv", argv)
        self.assertIn("--unshare-all", argv)

    def test_malformed_api_calls_not_executed(self):
        with self.assertRaises(ContextError):
            assistant_message({"role": "assistant", "tool_calls": [call(), call()]})
        item = call()
        item["function"]["arguments"] = None
        with self.assertRaises(ContextError):
            assistant_message({"role": "assistant", "tool_calls": [item]})

    def test_tool_round_limit(self):
        client = Mock()
        client.chat.completions.create.return_value = reply([call("unknown")])
        messages = []
        self.assertFalse(run_turn(client, {"model": "test"}, messages,
                                  ToolExecutor([], UI()), UI(), "go", max_steps=2))
        self.assertEqual(client.chat.completions.create.call_count, 2)
        validate_messages(messages)


if __name__ == "__main__":
    unittest.main()
