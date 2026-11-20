from contextlib import contextmanager
from pathlib import Path
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from .permissions import Mode, MODE_LABELS, network_label

COMMANDS = ["/help", "/history", "/return", "/retry", "/permissions ",
            "/safe", "/danger-full", "/web on", "/web off", "/web status", "/context ",
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
        return lambda index: [("class:command" if is_command else "", document.lines[index])]


class CommandOnlyHistory(FileHistory):
    def append_string(self, string):
        if string.startswith("/") and string != "/":
            super().append_string(string)


def plain(value):
    """Do not let model/file output inject terminal escape sequences into approval UI."""
    return "".join(c if c in "\n\t" or (c.isprintable() and c not in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
                   else f"\\u{ord(c):04x}" for c in str(value))


class TerminalUI:
    def __init__(self):
        from rich.console import Console
        self.console = Console()
        self.mode = Mode.WORKSPACE
        self.web_enabled = False
        self.session = PromptSession(
            history=CommandOnlyHistory(str(Path.home() / ".omyds_history")),
            auto_suggest=CommandAutoSuggest(), lexer=CommandLexer(),
            style=Style.from_dict({"command": "ansiyellow", "workspace": "ansigreen",
                                  "ask": "ansiyellow", "danger": "bold ansired"}))

    def show_logo(self):
        from rich.text import Text
        from .logo import LOGO
        # Only the built-in artwork is allowed to supply ANSI color styling.
        self.console.print(Text.from_ansi(LOGO))

    def set_mode(self, mode, web_enabled=False):
        self.mode = mode
        self.web_enabled = web_enabled

    def prompt(self, text):
        if text == "\n >> ":
            style = "danger" if self.mode == Mode.DANGER_FULL else self.mode.value
            label = "safe" if self.mode == Mode.WORKSPACE else self.mode.value
            network = "web" if self.mode == Mode.DANGER_FULL or self.web_enabled else "offline"
            text = FormattedText([("", "\n"), (f"class:{style}", f"[{label} · {network}]"), ("", " >> ")])
        return self.session.prompt(text).strip()

    def say(self, text, style=None):
        self.console.print(plain(text), style=style, markup=False, highlight=False)

    def help(self):
        from rich.table import Table
        from rich.text import Text
        table = Table(title=Text("OmyDs 帮助", style="bold blue"), box=None,
                      padding=(0, 2), show_header=True, header_style="bold", expand=False)
        table.add_column("命令", style="yellow", overflow="fold")
        table.add_column("说明", overflow="fold")
        for command, description in [
            ("/help", "显示帮助"),
            ("/history", "查看会话历史"),
            ("/return", "返回会话菜单"),
            ("/retry", "继续未完成的请求"),
            ("/permissions", "查看权限与工作区"),
            ("/permissions ask", "写入、命令逐次确认"),
            ("/safe", "工作区自动模式"),
            ("/web on|off|status", "沙箱联网开关 / 查看状态"),
            ("/context [字符数]", "查看上下文 / 调整本会话预算"),
            ("/danger-full", "宿主机模式（需确认）"),
            ("/set-project-root-in <路径>", "切换工作区"),
            ("/reset-project-root", "恢复默认工作区"),
            ("exit / quit", "退出程序"),
        ]:
            table.add_row(command, description)
        self.console.print()
        self.console.print(table)
        self.say("\n切换权限、网络和目录均保留会话；/safe 保留沙箱联网设置。", style="dim")

    def answer(self, content):
        from rich.markdown import Markdown
        self.say("\nOmyDs >", style="blue")
        self.console.print(Markdown(plain(content)))

    @contextmanager
    def busy(self):
        with self.console.status("思考中…"):
            yield

    def show_permissions(self, mode, root, detailed=False, web_enabled=False):
        self.say(f"模式: {MODE_LABELS[mode]} · 联网: {network_label(mode, web_enabled)}",
                 style="bold red" if mode == Mode.DANGER_FULL else "green")
        self.say(f"工作区: {root}", style="green")
        if not detailed:
            return
        if mode == Mode.DANGER_FULL:
            self.say("工作区仅决定初始目录，不限制访问范围。/safe 切回隔离；不会自动使用 sudo。")
        else:
            self.say("工作区是真实可写目录（含隐藏文件），不是副本；工具可以删除其中的数据。")
            self.say("命令挂载工作区与只读运行文件；越界文件工具访问需单次确认。")
            self.say("/web on 允许命令联网（含本机和局域网），可发送可读取的数据；/web off 关闭。")

    def confirm_danger(self, root):
        self.say("\n启用 DANGER-FULL", style="bold red")
        self.say(f"当前目录: {root}", style="green")
        self.say("解除工作区限制：可读写个人文件（含凭据）、修改 OmyDs、联网，不再逐次确认。")
        self.say("仅当前会话，不授予 sudo。/safe 切回；已执行的修改不会撤销。")
        return self.prompt("为本会话启用？[y/N] ").lower() == "y"

    def describe_tool(self, name, arguments, root, mode, outside, web_enabled=False):
        from rich.panel import Panel
        from rich.text import Text
        body = Text()
        rows = [
            ("工具", name),
            ("目的", arguments["purpose"]),
            ("预计影响", arguments["impact"]),

        ]
        if name == "run_command":
            rows += [("目录", str(root)), ("联网权限", network_label(mode, web_enabled)),
                     ("命令", arguments["command"])]
        else:
            rows += [("路径", arguments.get("path", ""))]
            if outside:
                rows += [("范围", "工作区外")]
            if name == "write_file":
                rows += [("操作", "追加到文件末尾" if arguments.get("mode") == "append" else "覆盖整个文件"),
                         ("长度", f"{len(arguments['content'])} 字符")]
            elif name == "read_file":
                rows += [("操作", "读取内容并回传给模型服务")]
        for label, value in rows:
            body.append(f"{label}: ", style="bold")
            body.append(plain(value), style="yellow" if label == "命令" else None)
            body.append("\n")
        self.console.print(Panel(body, title=f"{name} · {mode.value}", subtitle="目的与预计影响由模型说明", border_style="yellow", expand=False))
        if name == "write_file":
            content = arguments["content"]
            needs_confirmation = mode != Mode.DANGER_FULL and (outside or mode == Mode.ASK)
            if needs_confirmation:
                self.say("写入预览:", style="yellow")
                self.say(content[:2000])
                if len(content) > 2000:
                    self.say("（已截断；输入 v 查看完整内容）", style="dim")

    def confirm_tool(self, name, arguments, root, outside=False):
        while True:
            options = "[y/N，v查看全文]" if name == "write_file" else "[y/N]"
            choice = self.prompt(f"允许本次操作？{options} ").lower()
            if choice == "v" and name == "write_file":
                self.say(arguments["content"])
                continue
            return choice == "y"

    def history(self, messages):
        from rich.markdown import Markdown
        self.say("\n=== 当前会话历史 ===", style="bold blue")
        for m in messages:
            role = m.get("role")
            if role == "system":
                continue
            label, style = {
                "user": ("你 >", "green"), "assistant": ("OmyDs >", "blue"),
                "tool": ("工具结果 >", "yellow"),
            }.get(role, (str(role), "dim"))
            self.say(f"\n{label}", style=style)
            content = plain(m.get("content") or "")
            if role == "assistant":
                for call in m.get("tool_calls") or []:
                    self.say(f"  调用工具: {call['function']['name']}", style="yellow")
                if content:
                    self.console.print(Markdown(content))
            else:
                # Never show hidden reasoning_content; keep conversational text complete.
                if role == "tool" and len(content) > 4000:
                    content = content[:4000] + "\n（工具结果显示已截断）"
                self.say(content)
        self.say("\n=== 历史结束 ===", style="dim")
