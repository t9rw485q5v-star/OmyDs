import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from omyds import security, storage
from omyds.app import conversation, run_app
from omyds.chat import run_turn
from omyds.permissions import Mode
from omyds.tool_executor import ToolExecutor
from omyds.tools import AVAILABLE_TOOLS
from omyds.tools.run_command import RunCommandTool, command_argv, host_execution_error, run_process
from test_regressions import UI, call, reply


class PermissionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "project"
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

    def test_workspace_commands_no_confirmation_but_still_sandbox(self):
        ui = UI()
        tool = RunCommandTool()
        with patch.object(tool, "run", return_value="ok") as run:
            result = ToolExecutor([tool], ui).execute(call("run_command", {"command": "ls"}))
        self.assertEqual(result, "ok")
        self.assertEqual(ui.confirmations, [])
        self.assertNotIn("host", run.call_args.kwargs)

    def test_ask_denial_stops_command_and_write(self):
        ui = UI(approval=False)
        ex = ToolExecutor(AVAILABLE_TOOLS, ui, Mode.ASK)
        for item in [call("run_command", {"command": "echo x"}),
                     call("write_file", {"path": "x.txt", "content": "x"})]:
            self.assertIn("拒绝", ex.execute(item))
        self.assertFalse((self.workspace / "x.txt").exists())
        self.assertEqual(len(ui.confirmations), 2)

    def test_model_cannot_set_host_flag(self):
        ui = UI()
        tool = RunCommandTool()
        with patch.object(tool, "run") as run:
            ex = ToolExecutor([tool], ui)
            result = ex.execute(call("run_command", {"command": "id", "host": True}))
            run.assert_not_called()
        self.assertIn("不支持参数 host", result)

    def test_missing_purpose_or_impact_never_executes(self):
        tool = RunCommandTool()
        for key in ("purpose", "impact"):
            item = call("run_command", {"command": "id"})
            args = json.loads(item["function"]["arguments"])
            del args[key]
            item["function"]["arguments"] = json.dumps(args)
            with patch.object(tool, "run") as run:
                result = ToolExecutor([tool], UI()).execute(item)
                run.assert_not_called()
            self.assertIn(f"缺少参数 {key}", result)

    def test_schemas_do_not_mutate_base_tools(self):
        before = copy.deepcopy(AVAILABLE_TOOLS[0].parameters)
        schema = ToolExecutor(AVAILABLE_TOOLS, UI()).schemas[0]["function"]["parameters"]
        self.assertIn("impact", schema["required"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(AVAILABLE_TOOLS[0].parameters, before)

    def test_danger_outside_files_and_return_to_safe(self):
        path = self.root / "outside.txt"
        ui = UI()
        ex = ToolExecutor(AVAILABLE_TOOLS, ui, Mode.DANGER_FULL)
        self.assertIn("成功", ex.execute(call("write_file", {"path": str(path), "content": "hello"})))
        self.assertEqual(ex.execute(call(arguments={"path": str(path)})), "hello")
        self.assertEqual(ui.confirmations, [])
        ex.mode = Mode.WORKSPACE
        ui.approval = False
        self.assertIn("拒绝", ex.execute(call(arguments={"path": str(path)})))

    def test_danger_host_parameter_is_client_owned(self):
        tool = RunCommandTool()
        with patch.object(tool, "run", return_value="ok") as run:
            ToolExecutor([tool], UI(), Mode.DANGER_FULL).execute(call("run_command", {"command": "id"}))
        self.assertTrue(run.call_args.kwargs["host"])
        self.assertNotIn("purpose", run.call_args.args[0])

    def test_live_context_updates_on_retry_without_altering_history(self):
        client = Mock()
        client.chat.completions.create.side_effect = [RuntimeError("network"), reply(content="ok")]
        ui = UI()
        ex = ToolExecutor(AVAILABLE_TOOLS, ui)
        messages = [{"role": "system", "content": "base"}]
        self.assertFalse(run_turn(client, {"model": "test"}, messages, ex, ui, "go"))
        new = self.root / "new"
        new.mkdir()
        security.set_workdir(str(new))
        ex.mode = Mode.DANGER_FULL
        self.assertTrue(run_turn(client, {"model": "test"}, messages, ex, ui))
        first, second = [c.kwargs["messages"][0]["content"]
                         for c in client.chat.completions.create.call_args_list]
        self.assertIn(str(self.workspace), first)
        self.assertIn(str(new), second)
        self.assertIn('"permission_mode": "danger-full"', second)
        self.assertNotIn(str(self.workspace), second)
        self.assertEqual(messages[0]["content"], "base")

    def test_danger_confirmation_and_safe_transition(self):
        ui = UI(["/danger-full", "one", "/safe", "two", "exit", "n"])
        client = Mock()
        client.chat.completions.create.side_effect = [reply(content="one"), reply(content="two")]
        with patch("omyds.app.host_execution_error", return_value=None):
            conversation(ui, client, {"model": "test"}, [], None)
        states = [c.kwargs["messages"][0]["content"] for c in client.chat.completions.create.call_args_list]
        self.assertIn('"permission_mode": "danger-full"', states[0])
        self.assertIn('"permission_mode": "workspace"', states[1])

    def test_danger_denial_stays_workspace(self):
        ui = UI(["/danger-full", "go", "exit", "n"], approval=False)
        client = Mock()
        client.chat.completions.create.return_value = reply(content="ok")
        with patch("omyds.app.host_execution_error", return_value=None):
            conversation(ui, client, {"model": "test"}, [], None)
        state = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn('"permission_mode": "workspace"', state)

    def test_menu_does_not_keep_danger_permission(self):
        ui = UI(["0", "/danger-full", "one", "/return", "n", "0", "two", "exit", "n"])
        client = Mock()
        client.chat.completions.create.side_effect = [reply(content="one"), reply(content="two")]
        with patch("omyds.app.host_execution_error", return_value=None), \
             patch("omyds.app.get_system_prompt", return_value="s"), \
             patch("omyds.app.get_greeting", return_value=""):
            run_app({"api": {"model": "test"}}, client, ui)
        states = [c.kwargs["messages"][0]["content"] for c in client.chat.completions.create.call_args_list]
        self.assertIn('"permission_mode": "danger-full"', states[0])
        self.assertIn('"permission_mode": "workspace"', states[1])

    def test_directory_change_reaches_next_model_request(self):
        new = self.root / "new space"
        new.mkdir()
        ui = UI([f"/set-project-root-in {new}", "pwd", "exit", "n"])
        client = Mock()
        client.chat.completions.create.return_value = reply(content="ok")
        conversation(ui, client, {"model": "test"}, [], None)
        state = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn(str(new), state)

    def test_relative_mount_uses_launch_directory(self):
        with patch("omyds.security.Path.cwd", return_value=self.root):
            self.assertEqual(security.set_workdir("project"), str(self.workspace))

    def test_workspace_dotfiles_are_consistent(self):
        ex = ToolExecutor(AVAILABLE_TOOLS, UI())
        self.assertIn("成功", ex.execute(call("write_file", {"path": ".env", "content": "TEST=1"})))
        self.assertEqual(ex.execute(call(arguments={"path": ".env"})), "TEST=1")

    def test_symlink_escape_asks_permission(self):
        (self.root / "external").write_text("private")
        (self.workspace / "link").symlink_to(self.root / "external")
        ui = UI(approval=False)
        self.assertIn("拒绝", ToolExecutor(AVAILABLE_TOOLS, ui).execute(call(arguments={"path": "link"})))
        self.assertEqual(len(ui.confirmations), 1)

    def test_bwrap_failure_never_falls_back_to_host(self):
        with patch("omyds.tools.run_command.shutil.which", return_value=None), \
             patch("omyds.tools.run_command.run_process") as run:
            result = RunCommandTool().run({"command": "pwd"})
            run.assert_not_called()
        self.assertIn("不会自动", result)

    def test_host_requires_nonroot_and_setpriv(self):
        with patch("omyds.tools.run_command.os.geteuid", return_value=0):
            self.assertIn("root", host_execution_error())
        with patch("omyds.tools.run_command.os.getuid", return_value=1000), \
             patch("omyds.tools.run_command.os.geteuid", return_value=1000), \
             patch("omyds.tools.run_command.shutil.which", return_value=None):
            self.assertIn("setpriv", host_execution_error())

    def test_host_no_new_privileges_real_process(self):
        error = host_execution_error()
        if error:
            self.skipTest(error)
        command = "pwd; awk '/^NoNewPrivs:/ { print }' /proc/self/status"
        result = run_process(command_argv(command, self.workspace, host=True), self.workspace, host=True)
        self.assertIn("退出码: 0", result)
        self.assertIn(str(self.workspace), result)
        self.assertRegex(result, r"NoNewPrivs:\s+1")

    def test_host_does_not_inherit_secret_environment(self):
        error = host_execution_error()
        if error:
            self.skipTest(error)
        with patch.dict(os.environ, {"OMYDS_TEST_SECRET": "should-not-leak"}):
            result = RunCommandTool().run({"command": "printf '%s' \"$OMYDS_TEST_SECRET\""}, host=True)
        self.assertNotIn("should-not-leak", result)
        self.assertIn("退出码: 0", result)

    def test_process_timeout(self):
        result = run_process(["/bin/sh", "-c", "sleep 10"], self.workspace, timeout=0.05)
        self.assertIn("命令超时", result)

    def test_bwrap_real_isolation_when_available(self):
        outside = self.root / "unmounted.txt"
        outside.write_text("outside")
        argv = command_argv("printf isolated", self.workspace)
        probe = run_process(argv, self.workspace)
        if "退出码: 0" not in probe:
            self.skipTest("本环境无法启动 bwrap: " + probe.replace("\n", " ")[:180])
        # Work on disposable files only. No shell execution of destructive host commands.
        command = f'test ! -e "{outside}" && printf ok > inside.txt && cat inside.txt'
        result = run_process(command_argv(command, self.workspace), self.workspace)
        self.assertIn("退出码: 0", result)
        self.assertEqual((self.workspace / "inside.txt").read_text(), "ok")
        self.assertEqual(outside.read_text(), "outside")
