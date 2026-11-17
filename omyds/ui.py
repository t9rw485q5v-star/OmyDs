from contextlib import contextmanager
from pathlib import Path
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion

COMMANDS = ["/help", "/history", "/return", "/retry",
            "/set-project-root-in ", "/reset-project-root"]


class CommandAutoSuggest(AutoSuggest):
    def get_suggestion(self, buffer, document):
        text = document.text
        if text.startswith("/"):
            for cmd in COMMANDS + list(reversed(buffer.history.get_strings())):
                if cmd.startswith(text) and cmd != text:
                    return Suggestion(cmd[len(text):])
        return None


class CommandLexer(Lexer):
    def lex_document(self, document):
        is_command = document.text.lstrip().startswith("/")
        return lambda index: [
            ("class:command" if is_command else "", document.lines[index])
        ]


class CommandOnlyHistory(FileHistory):
    def append_string(self, string):
        if string.startswith("/") and string != "/":
            super().append_string(string)


class TerminalUI:
    def __init__(self):
        from rich.console import Console
        self.console = Console()
        self.session = PromptSession(
            history=CommandOnlyHistory(str(Path.home() / ".omyds_history")),
            auto_suggest=CommandAutoSuggest(),
            lexer=CommandLexer(),
            style=Style.from_dict({"command": "ansiyellow"}))

    def prompt(self, text):
        return self.session.prompt(text).strip()

    def say(self, text, style=None):
        self.console.print(str(text), style=style, markup=False, highlight=False)

    def help(self):
        from rich.table import Table
        from rich.text import Text
        table = Table(
            title=Text("OmyDs 帮助", style="bold blue"),
            box=None, padding=(0, 2), show_header=True,
            header_style="bold", expand=False,
        )
        table.add_column("命令", style="yellow", overflow="fold")
        table.add_column("说明", overflow="fold")
        for command, description in [
            ("/help", "显示帮助"),
            ("/history", "查看当前会话历史"),
            ("/return", "保存或放弃更改后，返回会话菜单"),
            ("/retry", "继续上次未完成的请求"),
            ("/set-project-root-in <路径>", "切换到指定工作区"),
            ("/reset-project-root", "恢复默认 sandbox 工作区"),
            ("exit / quit", "退出程序"),
        ]:
            table.add_row(command, description)
        self.console.print()
        self.console.print(table)
        self.say("\n提示：直接用自然语言让 OmyDs 读文件、修改代码或执行命令。", style="dim")


    def answer(self, content):
        from rich.markdown import Markdown
        self.say("\nOmyDs >", style="blue")
        self.console.print(Markdown(content))

    @contextmanager
    def busy(self):
        with self.console.status("思考中…"):
            yield

    def confirm_tool(self, name, arguments, root, outside=False):
        self.say(f"\n工具: {name}", style="yellow")
        self.say(f"工作区: {root}", style="green")
        if name == "run_command":
            self.say(f"$ {arguments['command']}", style="yellow")
            self.say("执行范围: bwrap 隔离环境中的当前工作区")
        else:
            self.say(f"目标绝对路径: {arguments['path']}")
            if name == "write_file":
                self.say(f"写入模式: {arguments.get('mode', 'overwrite')}")
                content = arguments["content"]
                self.say(content[:4000])
                if len(content) > 4000:
                    self.say(f"（预览截断，共 {len(content)} 字符）")
        if outside:
            self.say("本次授权仅适用于上述文件和操作，不会记住权限。")
        return self.prompt("允许本次操作？[y/N] ").lower() == "y"

    def history(self, messages):
        for m in messages:
            role = m.get("role")
            if role == "system":
                continue
            label = {"user": "你", "assistant": "OmyDs", "tool": "工具结果"}.get(role, role)
            self.say(f"\n[{label}] {(m.get('content') or '')[:1000]}")
