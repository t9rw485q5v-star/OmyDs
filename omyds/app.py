"""Application lifecycle: menu -> conversation -> save -> menu/exit."""
from . import storage, security
from .chat import run_turn, request_context
from .context import context_settings
from importlib.metadata import version, PackageNotFoundError
from .config import load_config, get_system_prompt, get_greeting
from .tool_executor import ToolExecutor, ToolCompatibilityError, validate_tool_interfaces
from .tools import AVAILABLE_TOOLS
from .ui import TerminalUI
from .permissions import Mode
from .tools.run_command import host_execution_error


def select_session(ui):
    while True:
        sessions = storage.list_sessions()
        try:
            label = " v" + version("OmyDs")
        except PackageNotFoundError:
            label = ""
        ui.say(f"\n--- OmyDs{label} ---")
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


def conversation(ui, client, api, messages, name, chat_config=None):
    executor = ToolExecutor(AVAILABLE_TOOLS, ui)
    executor.max_context_chars, executor.history_tool_chars = context_settings(chat_config or {})
    dirty = False
    pending = False
    ui.set_mode(executor.mode)
    ui.say("\n=== 欢迎来到 OmyDs~ ===", style="blue")
    ui.say("已进入对话。/help 查看帮助，/return 返回菜单，exit 退出。")
    ui.show_permissions(executor.mode, security.ALLOWED_ROOT)
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
        elif command == "/web":
            setting = argument.strip().lower()
            if setting not in {"", "status", "on", "off"}:
                ui.say("用法：/web on|off|status")
                continue
            if executor.mode == Mode.DANGER_FULL:
                ui.say("danger-full 使用宿主机网络；如需断网，请先 /safe，再 /web off。")
                ui.say(f"沙箱联网设置: {'on' if executor.web_enabled else 'off'}（切回 /safe 后生效）")
                continue
            if setting in {"on", "off"}:
                was_enabled = executor.web_enabled
                executor.web_enabled = setting == "on"
                if executor.web_enabled and not was_enabled:
                    ui.say("已允许命令联网（含本机和局域网）；可发送工作区数据，文件边界不变。", style="yellow")
            ui.set_mode(executor.mode, executor.web_enabled)
            ui.show_permissions(executor.mode, security.ALLOWED_ROOT, web_enabled=executor.web_enabled)
        elif command == "/context":
            setting = argument.strip()
            try:
                if setting:
                    budget, _ = context_settings({"max_context_chars": int(setting)})
                    executor.max_context_chars = budget
                    executor.context_notice = None
                    ui.say("已更新本会话预算；永久设置请修改 config.toml 的 [chat].max_context_chars。")
                _, info = request_context(messages, executor)
                ui.say(info.description())
                ui.say("这是消息字符预算，不是 token 上限；原始历史保留，下一轮会随新内容重新计算。", style="dim")
            except ValueError as exc:
                ui.say(f"无法设置或查看上下文：{exc}。用法：/context [至少 1024 的整数]")
        elif command in {"/permissions", "/safe", "/danger-full"}:
            requested = ("workspace" if command == "/safe" else
                         "danger-full" if command == "/danger-full" else argument.strip())
            if not requested:
                ui.show_permissions(executor.mode, security.ALLOWED_ROOT, detailed=True, web_enabled=executor.web_enabled)
                continue
            try:
                new_mode = Mode(requested)
            except ValueError:
                ui.say("用法：/permissions ask|workspace|danger-full")
                continue
            if new_mode == executor.mode:
                ui.show_permissions(executor.mode, security.ALLOWED_ROOT, detailed=True, web_enabled=executor.web_enabled)
                continue
            if new_mode == Mode.DANGER_FULL:
                error = host_execution_error()
                if error:
                    ui.say(error, style="red")
                    continue
                try:
                    if not ui.confirm_danger(security.ALLOWED_ROOT):
                        ui.say("未切换权限模式。")
                        continue
                except (KeyboardInterrupt, EOFError):
                    ui.say("已取消切换。")
                    continue
            executor.mode = new_mode
            ui.set_mode(new_mode, executor.web_enabled)
            ui.show_permissions(new_mode, security.ALLOWED_ROOT, web_enabled=executor.web_enabled)
        elif command in {"/set-project-root-in", "/reset-project-root"}:
            try:
                root = (security.reset_workdir() if command == "/reset-project-root"
                        else security.set_workdir(argument.strip()))
                ui.show_permissions(executor.mode, security.ALLOWED_ROOT, web_enabled=executor.web_enabled)
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
    ui.show_logo()
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
        if conversation(ui, client, cfg["api"], messages, name, cfg.get("chat", {})) == "exit":
            return


def main():
    try:
        validate_tool_interfaces(AVAILABLE_TOOLS)
    except ToolCompatibilityError as exc:
        print(f"[启动失败] {exc}")
        raise SystemExit(2) from exc
    from openai import OpenAI
    cfg = load_config()
    client = OpenAI(api_key=cfg["api"]["key"], base_url=cfg["api"]["base_url"],
                    timeout=60, max_retries=0)
    try:
        run_app(cfg, client, TerminalUI())
    except (EOFError, KeyboardInterrupt):
        print("\n已退出。")
