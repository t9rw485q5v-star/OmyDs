import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
from .. import security


def host_execution_error():
    if sys.platform != "linux":
        return "本版 danger-full 仅支持 Linux。"
    if os.getuid() == 0 or os.geteuid() == 0:
        return "不允许以 root 启动 danger-full，请用普通用户运行 OmyDs。"
    if not shutil.which("setpriv", path="/usr/bin:/bin"):
        return "缺少 setpriv（util-linux）；不会退回到没有权限限制的执行方式。"
    return None


def command_argv(command, root, host=False):
    if host:
        error = host_execution_error()
        if error:
            raise PermissionError(error)
        return [
            shutil.which("setpriv", path="/usr/bin:/bin"),
            "--no-new-privs", "--inh-caps=-all", "--ambient-caps=-all",
            "--", "/bin/sh", "-c", command,
        ]
    if sys.platform != "linux":
        raise PermissionError("本版隔离命令仅支持 Linux。")
    security.check_policy(root)
    executable = shutil.which("bwrap", path="/usr/bin:/bin")
    if not executable:
        raise FileNotFoundError("未找到 bwrap；不会自动切换到宿主机执行。")
    # Reject workspaces under the runtime mounts: later writable binds must not hide /usr etc.
    argv = [executable]
    for path in ("/usr", "/bin", "/lib", "/lib64", "/etc/alternatives"):
        if Path(path).exists():
            argv.extend(["--ro-bind", path, path])
    argv.extend([
        "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--bind", str(root), str(root), "--chdir", str(root),
        "--unshare-all", "--new-session", "--clearenv",
        "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/tmp",
        "--setenv", "LANG", "C.UTF-8", "--die-with-parent",
        "/bin/sh", "-c", command,
    ])
    return argv


def run_process(argv, root, host=False, timeout=60):
    # Do not leak API tokens, agent environment variables, or interactive stdin to commands.
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin") if host else "/usr/bin:/bin",
        "HOME": str(Path.home()) if host else "/tmp",
        "LANG": "C.UTF-8",
    }
    with tempfile.TemporaryFile() as output:
        proc = subprocess.Popen(
            argv, cwd=str(root), env=env, stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
        )
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # Stop ordinary background children too; detached daemons are not contained in host mode.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        output.seek(0)
        data = output.read(16001)
    text = data[:16000].decode("utf-8", errors="replace")
    suffix = "\n（输出已截断）" if len(data) > 16000 else ""
    prefix = f"命令超时（{timeout} 秒），已终止进程组。" if timed_out else f"退出码: {proc.returncode}"
    return prefix + "\n" + (text or "（无输出）") + suffix


class RunCommandTool:
    def __init__(self):
        self.name = "run_command"
        self.description = "在当前工作区执行 shell 命令；隔离/宿主机模式由客户端权限状态决定，工具不可自行提权。"
        self.parameters = {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "要执行的完整 shell 命令"}},
            "required": ["command"],
        }

    def run(self, arguments, *, host=False):
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            return "错误：命令不能为空。"
        root = security.ALLOWED_ROOT
        if not root.is_dir():
            return "错误：工作区不存在。"
        try:
            return run_process(command_argv(command, root, host), root, host)
        except (KeyboardInterrupt, EOFError):
            raise
        except Exception as exc:
            return f"命令未成功执行：{exc}（不会自动解除隔离或提权）"
