import subprocess
import sys
from .. import security

class RunCommandTool:
    def __init__(self):
        self.name = "run_command"
        self.description = "在受限的沙箱环境内执行终端命令。"
        self.parameters = {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"}
            },
            "required": ["command"]
        }

    def run(self, arguments: dict) -> str:
        cmd = arguments.get("command")
        if not cmd:
            return "错误：命令为空。"
            
        # 安全过滤：禁止在终端命令里携带敏感文件名
        for forbidden in security.FORBIDDEN_NAMES:
            if forbidden in cmd:
                return f"执行失败：命令包含敏感词 '{forbidden}'，已被系统拦截。"

        if sys.platform != "linux":
            return "错误：当前系统暂不支持物理沙箱隔离。"

        # 实时获取当前挂载的目录
        current_root = security.ALLOWED_ROOT
        current_root.mkdir(parents=True, exist_ok=True)
        
        bwrap_cmd = [
            "bwrap",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", "/etc/alternatives", "/etc/alternatives",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--bind", str(current_root), str(current_root),
            "--chdir", str(current_root),
            "--unshare-all",
            "--die-with-parent",
            "sh", "-c", cmd
        ]

        try:
            result = subprocess.run(
                bwrap_cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            output = result.stdout + result.stderr
            if not output.strip():
                return "命令执行成功，无输出。"
            return output[:2000]
        except FileNotFoundError:
            return "错误：未找到 bwrap。"
        except subprocess.TimeoutExpired:
            return "错误：命令执行超时（10秒）。"
        except Exception as e:
            return f"执行错误：{e}"