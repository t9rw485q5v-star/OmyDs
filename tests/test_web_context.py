"""Network boundaries and conversation continuity; no external API calls."""
import copy
import http.server
from pathlib import Path
import shlex
import shutil
import threading
import unittest
from unittest.mock import Mock, patch

from omyds import security, storage
from omyds.app import conversation, run_app
from omyds.chat import run_turn
from omyds.context import context_settings, prepare_context, validate_messages
from omyds.permissions import Mode
from omyds.tool_executor import ToolExecutor
from omyds.tools import AVAILABLE_TOOLS
from omyds.tools.run_command import RunCommandTool, command_argv, run_process
from test_regressions import UI, call, reply


class WebContextTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        for obj, key, value in (
            (security, "ALLOWED_ROOT", self.workspace),
            (storage, "MEMORY_FILE", self.root / "memory.md"),
            (storage, "SESSIONS_DIR", self.root / "sessions"),
        ):
            p = patch.object(obj, key, value)
            p.start()
            self.addCleanup(p.stop)

    def client(self):
        client = Mock()
        client.chat.completions.create.return_value = reply(content="ok")
        return client

    def test_switches_keep_history_and_report_current_state(self):
        new = self.root / "new"
        new.mkdir()
        ui = UI(["记住本轮任务：整理书架", "/web on", "联网继续", "/permissions ask",
                 "继续确认模式", "/danger-full", "继续宿主机", "/web off", "/safe",
                 f"/set-project-root-in {new}", "继续沙箱", "/web off", "继续离线", "exit", "n"])
        client = self.client()
        messages = [{"role": "system", "content": "base"}]
        with patch("omyds.app.host_execution_error", return_value=None):
            conversation(ui, client, {"model": "test"}, messages, None)
        requests = [c.kwargs["messages"] for c in client.chat.completions.create.call_args_list]
        for index, request in enumerate(requests):
            self.assertEqual(sum(m["role"] == "user" for m in request), index + 1)
            self.assertEqual(next(m["content"] for m in request if m["role"] == "user"),
                             "记住本轮任务：整理书架")
            validate_messages(request)
        states = [r[0]["content"] for r in requests]
        for i in (0, 5):
            self.assertIn('"command_network": "disabled"', states[i])
        for i in (1, 2, 3, 4):
            self.assertIn('"command_network": "host network"', states[i])
        self.assertIn('"permission_mode": "ask"', states[2])
        self.assertIn('"permission_mode": "danger-full"', states[3])
        self.assertIn('"permission_mode": "workspace"', states[4])
        self.assertIn(str(new), states[4])
        self.assertEqual(messages[0]["content"], "base")
        self.assertTrue(any("如需断网" in s for s in ui.output))

    def test_new_session_resets_network_even_when_history_reloaded(self):
        ui = UI(["0", "/web on", "one", "/return", "y", "saved", "1", "two", "exit", "n"])
        client = self.client()
        with patch("omyds.app.get_system_prompt", return_value="s"), \
             patch("omyds.app.get_greeting", return_value=""):
            run_app({"api": {"model": "test"}}, client, ui)
        requests = [c.kwargs["messages"] for c in client.chat.completions.create.call_args_list]
        self.assertIn('"command_network": "host network"', requests[0][0]["content"])
        self.assertIn('"command_network": "disabled"', requests[1][0]["content"])
        self.assertEqual([m["content"] for m in requests[1] if m["role"] == "user"], ["one", "two"])

    def test_web_status_and_invalid_argument_do_not_toggle(self):
        client = self.client()
        ui = UI(["/web", "/web status", "/web invalid", "go", "exit", "n"])
        conversation(ui, client, {"model": "test"}, [], None)
        self.assertIn('"command_network": "disabled"',
                      client.chat.completions.create.call_args.kwargs["messages"][0]["content"])

    def test_retry_after_web_switch_keeps_tool_result_and_does_not_repeat_write(self):
        client = Mock()
        client.chat.completions.create.side_effect = [
            reply([call("write_file", {"path": "once.txt", "content": "once", "mode": "append"})]),
            RuntimeError("temporary API error"), reply(content="done")]
        ui = UI(["go", "/web on", "/retry", "exit", "n"])
        messages = []
        conversation(ui, client, {"model": "test"}, messages, None)
        self.assertEqual((self.workspace / "once.txt").read_text(), "once")
        last = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertIn('"command_network": "host network"', last[0]["content"])
        self.assertEqual(sum(m["role"] == "tool" for m in last), 1)
        self.assertEqual(sum(m["role"] == "user" for m in last), 1)
        validate_messages(last)

    def test_model_cannot_enable_network(self):
        tool = RunCommandTool()
        for parameter in ("network", "web_enabled", "host"):
            with self.subTest(parameter=parameter), patch.object(tool, "run") as run:
                result = ToolExecutor([tool], UI()).execute(call("run_command", {
                    "command": "true", parameter: True}))
                self.assertIn("不支持参数", result)
                run.assert_not_called()

    def test_executor_network_flag_and_ask_confirmation(self):
        tool = RunCommandTool()
        ui = UI(approval=False)
        ex = ToolExecutor([tool], ui, Mode.ASK)
        ex.web_enabled = True
        with patch.object(tool, "run", return_value="ok") as run:
            self.assertIn("拒绝", ex.execute(call("run_command", {"command": "true"})))
            run.assert_not_called()
            ui.approval = True
            ex.execute(call("run_command", {"command": "true"}))
            self.assertTrue(run.call_args.kwargs["network"])
            ex.web_enabled = False
            ex.execute(call("run_command", {"command": "true"}))
            self.assertFalse(run.call_args.kwargs["network"])

    def test_online_argv_keeps_filesystem_isolation_and_minimal_env(self):
        with patch("omyds.tools.run_command.shutil.which", return_value="/usr/bin/bwrap"):
            offline = command_argv("true", self.workspace)
            online = command_argv("true", self.workspace, network=True)
        self.assertNotIn("--share-net", offline)
        self.assertGreater(online.index("--share-net"), online.index("--unshare-all"))
        self.assertIn("--clearenv", online)
        binds = [(online[i + 1], online[i + 2]) for i, x in enumerate(online) if x == "--bind"]
        self.assertEqual(binds, [(str(self.workspace), str(self.workspace))])
        self.assertNotIn("/etc", online)
        self.assertNotIn("/etc/ssl/private", online)
        self.assertNotIn("/etc/resolv.conf", offline)

    def test_online_bwrap_failure_has_no_host_fallback(self):
        with patch("omyds.tools.run_command.shutil.which", return_value=None), \
             patch("omyds.tools.run_command.run_process") as run:
            result = RunCommandTool().run({"command": "true"}, network=True)
        run.assert_not_called()
        self.assertIn("不会自动", result)

    def test_real_online_sandbox_reads_local_http_but_not_outside_files(self):
        if not shutil.which("bwrap") or not Path("/usr/bin/python3").exists():
            self.skipTest("需要 bwrap 和 /usr/bin/python3")
        probe = run_process(command_argv("true", self.workspace, network=True), self.workspace)
        if "退出码: 0" not in probe:
            self.skipTest("当前环境不能运行联网沙箱：" + probe[:180])

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"LOCAL_TEST_ONLY")
            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        outside = self.root / "outside.txt"
        outside.write_text("TEST_ONLY")
        script = (
            "from pathlib import Path; import urllib.request, ssl, socket; "
            f"assert not Path({str(outside)!r}).exists(); "
            "assert not Path('/etc/ssl/private').exists(); "
            "assert socket.getaddrinfo('localhost', 80); "
            "Path('inside.txt').write_text('ok'); "
            f"print(urllib.request.urlopen('http://127.0.0.1:{server.server_port}', timeout=3).read().decode())"
        )
        try:
            result = run_process(command_argv("/usr/bin/python3 -c " + shlex.quote(script),
                                              self.workspace, network=True), self.workspace)
            self.assertIn("退出码: 0", result)
            self.assertIn("LOCAL_TEST_ONLY", result)
            self.assertEqual((self.workspace / "inside.txt").read_text(), "ok")
            self.assertEqual(outside.read_text(), "TEST_ONLY")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def history_with_large_tool(self):
        return [{"role": "system", "content": "base"},
                {"role": "user", "content": "目标：整理书架"},
                {"role": "assistant", "content": None, "reasoning_content": "reasoning",
                 "tool_calls": [call()]},
                {"role": "tool", "tool_call_id": "t1", "content": "HEAD" + "x" * 20000 + "TAIL"},
                {"role": "assistant", "content": "已检查"},
                {"role": "user", "content": "继续"}]

    def test_old_tool_compaction_preserves_goal_and_original_history(self):
        messages = self.history_with_large_tool()
        before = copy.deepcopy(messages)
        result, info = prepare_context(messages, max_chars=4000, history_tool_chars=1000)
        self.assertEqual(info.dropped_turns, 0)
        self.assertEqual(info.shortened_results, 1)
        self.assertLessEqual(info.chars, 4000)
        tool = next(m for m in result if m["role"] == "tool")
        self.assertTrue(tool["content"].startswith("HEAD"))
        self.assertTrue(tool["content"].endswith("TAIL"))
        self.assertIn("已省略", tool["content"])
        self.assertEqual(result[2]["reasoning_content"], "reasoning")
        self.assertEqual(messages, before)
        validate_messages(result)

    def test_no_compaction_when_budget_sufficient_or_disabled(self):
        messages = self.history_with_large_tool()
        result, info = prepare_context(messages, max_chars=64000)
        self.assertEqual(result, messages)
        self.assertEqual(info.shortened_results, 0)
        result, info = prepare_context(messages, max_chars=4000, history_tool_chars=0)
        self.assertEqual(info.shortened_results, 0)
        self.assertEqual(info.dropped_turns, 1)

    def test_active_tool_pair_and_reasoning_are_never_shortened(self):
        messages = self.history_with_large_tool()[:-2]
        result, info = prepare_context(messages, max_chars=1024, history_tool_chars=256)
        self.assertEqual(result, messages)
        self.assertTrue(info.over_budget)
        self.assertEqual(info.shortened_results, 0)
        validate_messages(result)

    def test_raising_budget_restores_omitted_turns_without_reloading(self):
        messages = self.history_with_large_tool()
        _, small = prepare_context(messages, max_chars=1024, history_tool_chars=0)
        large_request, large = prepare_context(messages, max_chars=64000)
        self.assertEqual(small.dropped_turns, 1)
        self.assertEqual(large.dropped_turns, 0)
        self.assertEqual(large_request, messages)

    def test_runtime_system_state_counts_toward_budget(self):
        _, info = prepare_context([{"role": "user", "content": "hi"}], 1024,
                                  extra_system="s" * 2000)
        self.assertTrue(info.over_budget)
        self.assertGreater(info.chars, 2000)

    def test_trimming_warns_once_for_unchanged_state_and_keeps_original(self):
        messages = self.history_with_large_tool()
        ui = UI()
        ex = ToolExecutor([], ui)
        ex.max_context_chars = 4000
        ex.history_tool_chars = 1000
        client = self.client()
        before = copy.deepcopy(messages)
        self.assertTrue(run_turn(client, {"model": "test"}, messages, ex, ui))
        self.assertTrue(run_turn(client, {"model": "test"}, messages, ex, ui))
        notices = [s for s in ui.output if s.startswith("[上下文]")]
        self.assertEqual(len(notices), 1)
        self.assertIn("缩短 1 条", notices[0])
        self.assertEqual(messages[:len(before)], before)

    def test_context_command_changes_budget_without_sending_api_request(self):
        messages = [{"role": "user", "content": "old"},
                    {"role": "assistant", "content": "x" * 5000}]
        ui = UI(["/context", "/context 1", "/context abc", "/context 2048", "new", "exit", "n"])
        client = self.client()
        conversation(ui, client, {"model": "test"}, messages, None,
                     {"max_context_chars": 9000})
        self.assertEqual(client.chat.completions.create.call_count, 1)
        request = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual([m["content"] for m in request if m["role"] == "user"], ["new"])
        self.assertEqual(messages[0]["content"], "old")
        self.assertTrue(any("/9,000 字符" in s for s in ui.output))
        self.assertTrue(any("未发送 1 轮" in s for s in ui.output))

    def test_invalid_config_is_rejected(self):
        for key, values in (("max_context_chars", (True, 0, -1, "64000", 1.5)),
                            ("history_tool_chars", (False, -1, 1, "4000"))):
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    context_settings({key: value})
        self.assertEqual(context_settings({"history_tool_chars": 0}), (64000, 0))


if __name__ == "__main__":
    unittest.main()
