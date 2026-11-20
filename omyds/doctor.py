"""Local installation diagnostics: no model calls, subprocesses or network."""
import inspect
from importlib.metadata import PackageNotFoundError, version
import shutil
import sys
import ssl
import tomllib
from pathlib import Path

from . import tool_executor
from .tools import AVAILABLE_TOOLS, run_command


def main():
    try:
        installed = version("omyds")
    except PackageNotFoundError:
        installed = "未安装包元数据"
    print(f"OmyDs: {installed}")
    project_file = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if project_file.is_file():
        with project_file.open("rb") as source:
            project = tomllib.load(source).get("project", {})
        if project.get("name", "").lower() == "omyds":
            declared = project.get("version", "未知")
            print(f"项目声明版本: {declared}")
            if declared != installed:
                print("[提示] 安装元数据与项目版本不一致；请在项目根目录运行 uv sync --reinstall-package omyds")
    print(f"Python: {sys.executable}")
    print(f"调用方: {tool_executor.__file__}")
    print(f"命令工具: {run_command.__file__}")
    print(f"run: {inspect.signature(run_command.RunCommandTool.run)}")
    print(f"command_argv: {inspect.signature(run_command.command_argv)}")
    print(f"bwrap: {shutil.which('bwrap', path='/usr/bin:/bin') or '未找到'}")
    print(f"Python 默认 CA 路径: {ssl.get_default_verify_paths()}")
    print(f"沙箱 CA bundle: {run_command.system_ca_bundle() or '未找到，沿用默认 CA 目录'}")
    try:
        tool_executor.validate_tool_interfaces(AVAILABLE_TOOLS)
        inspect.signature(run_command.command_argv).bind("true", ".", network=False)
    except (tool_executor.ToolCompatibilityError, TypeError, ValueError) as exc:
        print(f"[失败] {exc}")
        return 2
    print("[通过] 命令接口一致。此检查不执行命令，也不证明沙箱或网络可用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
