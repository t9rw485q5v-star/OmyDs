"""Regressions for mixed tool versions and the full executor-to-shell path."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from omyds import security
from omyds.app import main
from omyds.doctor import main as doctor
from omyds.permissions import Mode
from omyds.tool_executor import ToolExecutor, ToolCompatibilityError
from omyds.tools.run_command import RunCommandTool
from test_regressions import UI, call


class LegacyCommandTool(RunCommandTool):
    """The signature quoted in report 0.2.0a."""
    def run(self, arguments, *, host=False):
        return "legacy should not be executed"


class CommandContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        p = patch.object(security, "ALLOWED_ROOT", self.root)
        p.start()
        self.addCleanup(p.stop)

    def test_reported_old_signature_is_reproduced_and_caught_before_chat(self):
        legacy = LegacyCommandTool()
        with self.assertRaisesRegex(TypeError, "network"):
            legacy.run({"command": "pwd"}, network=False)
        with self.assertRaisesRegex(ToolCompatibilityError, "实际加载"):
            ToolExecutor([legacy], UI())

    def test_mixed_installation_stops_startup_before_config_or_api(self):
        with patch("omyds.app.AVAILABLE_TOOLS", [LegacyCommandTool()]), \
             patch("omyds.app.load_config") as config, \
             redirect_stdout(io.StringIO()) as output, \
             self.assertRaises(SystemExit) as error:
            main()
        self.assertEqual(error.exception.code, 2)
        config.assert_not_called()
        self.assertIn("退出旧进程", output.getvalue())

    def test_real_tool_dispatch_for_safe_and_ask_with_network_on_and_off(self):
        # Only the OS process boundary is stubbed. Do not mock tool.run:
        # doing so would conceal precisely the reported incompatible signature.
        for mode in (Mode.WORKSPACE, Mode.ASK):
            for network in (False, True):
                with self.subTest(mode=mode, network=network), \
                     patch("omyds.tools.run_command.shutil.which", return_value="/usr/bin/bwrap"), \
                     patch("omyds.tools.run_command.run_process", return_value="退出码: 0\nOK") as process:
                    ui = UI()
                    executor = ToolExecutor([RunCommandTool()], ui, mode)
                    executor.web_enabled = network
                    result = executor.execute(call("run_command", {"command": "pwd"}))
                    self.assertEqual(result, "退出码: 0\nOK")
                    argv, root, host = process.call_args.args
                    self.assertFalse(host)
                    self.assertEqual(root, self.root)
                    self.assertEqual(argv[-3:], ["/bin/sh", "-c", "pwd"])
                    self.assertEqual("--share-net" in argv, network)
                    if network:
                        self.assertGreater(argv.index("--share-net"), argv.index("--unshare-all"))
                    self.assertEqual(len(ui.confirmations), int(mode == Mode.ASK))

    def test_real_dispatch_never_ignores_sandbox_failure(self):
        with patch("omyds.tools.run_command.shutil.which", return_value=None), \
             patch("omyds.tools.run_command.run_process") as process:
            executor = ToolExecutor([RunCommandTool()], UI())
            executor.web_enabled = True
            result = executor.execute(call("run_command", {"command": "pwd"}))
        process.assert_not_called()
        self.assertIn("未找到 bwrap", result)
        self.assertIn("不会自动", result)

    def test_real_online_executor_runs_basic_commands(self):
        if not shutil.which("bwrap", path="/usr/bin:/bin"):
            self.skipTest("未安装 bwrap")
        executor = ToolExecutor([RunCommandTool()], UI())
        executor.web_enabled = True
        probe = executor.execute(call("run_command", {"command": "true"}))
        if "退出码: 0" not in probe:
            self.skipTest("环境不能启动联网沙箱：" + probe[:180])
        (self.root / "sample.txt").write_text("BOOKS_TEST\n")
        for command, expected in (("pwd", str(self.root)), ("ls", "sample.txt"),
                                  ("grep BOOKS_TEST sample.txt", "BOOKS_TEST"),
                                  ("date +%Y", None), ("mkdir child", None)):
            with self.subTest(command=command):
                result = executor.execute(call("run_command", {"command": command}))
                self.assertIn("退出码: 0", result)
                if expected:
                    self.assertIn(expected, result)
        self.assertTrue((self.root / "child").is_dir())

    def test_real_offline_executor_runs_basic_command_when_supported(self):
        if not shutil.which("bwrap", path="/usr/bin:/bin"):
            self.skipTest("未安装 bwrap")
        executor = ToolExecutor([RunCommandTool()], UI())
        probe = executor.execute(call("run_command", {"command": "true"}))
        if "退出码: 0" not in probe:
            self.skipTest("环境不能创建隔离网络：" + probe[:180])
        result = executor.execute(call("run_command", {"command": "pwd"}))
        self.assertIn("退出码: 0", result)
        self.assertIn(str(self.root), result)

    def test_doctor_reports_loaded_paths_without_running_commands(self):
        with patch("omyds.tools.run_command.run_process") as process, \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(doctor(), 0)
        process.assert_not_called()
        self.assertIn("tool_executor.py", output.getvalue())
        self.assertIn("run_command.py", output.getvalue())
        self.assertIn("network=False", output.getvalue())


if __name__ == "__main__":
    unittest.main()
