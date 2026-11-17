"""Application lifecycle: menu -> conversation -> save -> menu/exit."""
from . import storage, security
from .chat import run_turn
from .config import load_config, get_system_prompt, get_greeting
from .logo import LOGO
from .tool_executor import ToolExecutor
from .tools import AVAILABLE_TOOLS
from .ui import TerminalUI


def select_session(ui):
    while True:
        sessions = storage.list_sessions()
        ui.say("\n--- OmyDs v0.1.9.11 ---")
        for index, name in enumerate(sessions, 1):
            ui.say(f"  {index}. {name}")
        ui.say("  0. 新建对话\n  q. 退出")
        choice = ui.prompt("请选择（默认 0）：")
        if choice.lower() in {"q", "exit", "quit"}:
            return False, None
        if choice in {"", "0"}:
            return True, None
        if choice.isdigit() and 1 <= int(choice) <= len(sessions):
            return True, sessions[int(choice) - 1]
        ui.say("请输入有效序号。")


def save_before_leave(ui, name, messages, dirty):
    if not dirty:
        return True
    while True:
        choice = ui.prompt("保存本次更改？[y/N/c取消返回] ").lower()
        if choice == "c":
            return False
        if choice in {"", "n"}:
            return True
        if choice != "y":
            continue
        target = name or ui.prompt("会话名称：")
        if not target:
            ui.say("名称不能为空。")
            continue
        if name is None and target in storage.list_sessions():
            if ui.prompt("同名会话已存在，覆盖？[y/N] ").lower() != "y":
                continue
        try:
            storage.save_session(target, messages)
        except (OSError, ValueError) as exc:
            ui.say(f"保存失败：{exc}；对话仍保留。")
            continue
        ui.say("已保存。")
        return True


def conversation(ui, client, api, messages, name):
    executor = ToolExecutor(AVAILABLE_TOOLS, ui)
    dirty = False
    pending = False
    ui.say("\n=== 欢迎来到 OmyDs~ ===", style="blue")
    ui.say("已进入对话。/help 查看帮助，/return 返回菜单，exit 退出。")
    ui.say(f"当前工作区: {security.ALLOWED_ROOT}", style="green")
    while True:
        try:
            text = ui.prompt("\n >> ")
        except (KeyboardInterrupt, EOFError):
            text = "exit"
        if not text:
            continue
        command, _, argument = text.partition(" ")
        command = command.lower()
        if command in {"/return", "exit", "quit"}:
            if save_before_leave(ui, name, messages, dirty):
                return "menu" if command == "/return" else "exit"
            continue
        if command == "/help":
            ui.help()
        elif command == "/history":
            ui.history(messages)
        elif command in {"/set-project-root-in", "/reset-project-root"}:
            try:
                root = (security.reset_workdir() if command == "/reset-project-root"
                        else security.set_workdir(argument.strip()))
                ui.say(f"工作区: {root}", style="green")
            except (OSError, ValueError) as exc:
                ui.say(f"切换失败：{exc}")
        elif command == "/retry":
            if not pending:
                ui.say("没有本次运行中待继续的请求。")
                continue
            pending = not run_turn(client, api, messages, executor, ui)
            dirty = True
        elif text.startswith("/"):
            ui.say("未知指令，请用 /help 查看。")
        else:
            pending = not run_turn(client, api, messages, executor, ui, text)
            dirty = True


def run_app(cfg, client, ui):
    ui.say(LOGO)
    greeting = get_greeting()
    if greeting:
        ui.say(greeting)
    while True:
        proceed, name = select_session(ui)
        if not proceed:
            return
        security.reset_workdir()
        prompt = get_system_prompt(cfg)
        if storage.MEMORY_FILE.exists():
            memory = storage.MEMORY_FILE.read_text(encoding="utf-8").strip()
            if memory:
                prompt += f"\n\n【用户长期记忆档案】\n{memory}"
        try:
            old = storage.load_session(name) if name else []
        except (OSError, ValueError) as exc:
            ui.say(f"无法加载会话：{exc}")
            continue
        messages = [{"role": "system", "content": prompt}]
        messages.extend(m for m in old if m.get("role") != "system")
        if conversation(ui, client, cfg["api"], messages, name) == "exit":
            return


def main():
    from openai import OpenAI
    cfg = load_config()
    client = OpenAI(api_key=cfg["api"]["key"], base_url=cfg["api"]["base_url"],
                    timeout=60, max_retries=0)
    try:
        run_app(cfg, client, TerminalUI())
    except (EOFError, KeyboardInterrupt):
        print("\n已退出。")
