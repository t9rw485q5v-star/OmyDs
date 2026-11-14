import re
import sys
import threading
import time
import itertools
import json
from openai import OpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from pathlib import Path
from .config import load_config, get_system_prompt
from . import storage
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from .security import OutOfSandboxError
from omyds.tools import AVAILABLE_TOOLS

class Spinner:
    def __init__(self, message="思考中 "):
        self.spinner = itertools.cycle(['|', '/', '-', '\\'])
        self.stop_running = threading.Event()
        self.thread = threading.Thread(target=self._spin)
        self.message = message

    def _spin(self):
        while not self.stop_running.is_set():
            sys.stdout.write(f"\r\033[36m{self.message} {next(self.spinner)}\033[0m")
            sys.stdout.flush()
            time.sleep(0.1)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_running.set()
        self.thread.join()
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

class CommandAutoSuggest(AutoSuggest):
    def get_suggestion(self, buffer, document):
        text = document.text
        if not text.startswith("/"):
            return None
        default_commands = ["/help ", "/history"]
        for cmd in default_commands:
            if cmd.startswith(text) and cmd != text:
                return Suggestion(cmd[len(text):])
        for string in reversed(buffer.history.get_strings()):
            if string.startswith("/") and string.startswith(text) and string != text:
                return Suggestion(string[len(text):])
        return None

class CommandOnlyHistory(FileHistory):
    def append_string(self, string):
        if string.startswith("/") and string != "/":
            super().append_string(string)

def main():
    cfg = load_config()
    api = cfg["api"]
    system_prompt = get_system_prompt(cfg)

    memory_file = Path.home() / ".omyds" / "memory.md"
    if memory_file.exists():
        with open(memory_file, "r", encoding="utf-8") as f:
            memory_content = f.read().strip()
            if memory_content:
                system_prompt += f"\n\n【用户长期记忆档案】\n{memory_content}"

    client = OpenAI(api_key=api["key"], base_url=api["base_url"])

    sessions = storage.list_sessions()
    print("--- OmyDs v0.1.6 ---")
    
    if sessions:
        print("已有的对话：")
        for i, s in enumerate(sessions):
            print(f"  {i + 1}. {s}")
        print("  0. 新建对话")
        
        choice = input("\n请输入序号（默认 0）：").strip()
        
        session_name = None
        is_new_session = False
        
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(sessions):
                session_name = sessions[idx - 1]
                messages = storage.load_session(session_name)
                print(f"已加载会话：{session_name}")
            else:
                is_new_session = True
        else:
            is_new_session = True
    else:
        print("(无历史对话，直接新建)")
        is_new_session = True
        
    if is_new_session:
        session_name = None
        messages = [{"role": "system", "content": system_prompt}]
            
    print(f"\n\033[36m=== 欢迎来到 OmyDs~ ===\033[0m\n已进入对话。输入 exit 或 quit 退出。(使用 /help 指令寻求帮助)")

    history_file = Path.home() / ".omyds_history"
    session = PromptSession(
        history=CommandOnlyHistory(str(history_file)),
        auto_suggest=CommandAutoSuggest()
    )

    # 记录已授权的路径，避免同一操作反复询问
    authorized_paths = set()

    api_tools = []
    for tool in AVAILABLE_TOOLS:
        api_tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters
            }
        })

    while True:
        try:
            user_input = session.prompt("\n >> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            break
        
        if user_input.lower() == "/help":
            print("\n\033[36m=== OmyDs 帮助 ===\033[0m")
            print("  /history              显示过往聊天的历史记录")
            print("  exit / quit           退出聊天")
            print("  \033[33m提示: 直接用自然语言让 AI 读文件或改代码即可。\033[0m\n")
            continue

        if user_input.lower() == "/history":
            print("\n\033[36m=== 当前会话历史记录 ===\033[0m")
            for msg in messages:
                if isinstance(msg, dict):
                    if msg.get("role") == "system": continue
                    content = msg.get("content")
                    role = msg.get("role")
                else:
                    if getattr(msg, "role", "") == "system": continue
                    content = getattr(msg, "content", None)
                    role = getattr(msg, "role", "")

                if content:
                    role_name = "\033[34m你\033[0m" if role == "user" else "\033[33mOmyDs\033[0m"
                    if len(content) > 200:
                        content = content[:200] + "\n...(内容过长已截断)"
                    print(f"\n[{role_name}]:\n{content}")
            print("\n\033[36m======================\033[0m\n")
            continue

        # 保存用户输入前的消息长度，用于遇到 400 错误时回滚
        msg_len_before_input = len(messages)
        messages.append({"role": "user", "content": user_input})

        # === 内层循环：处理 Agent 思考和工具调用 ===
        api_error_occurred = False
        while True:
            # 上下文截断
            total_chars = 0
            for m in messages:
                if isinstance(m, dict):
                    total_chars += len(m.get("content") or "")
                else:
                    total_chars += len(getattr(m, "content", "") or "")
            
            MAX_CHARS = 8000
            if total_chars > MAX_CHARS:
                keep_chars = 0
                keep_from_index = len(messages)
                for i in range(len(messages) - 1, 0, -1):
                    m = messages[i]
                    m_chars = len(m.get("content") or "") if isinstance(m, dict) else len(getattr(m, "content", "") or "")
                    keep_chars += m_chars
                    if keep_chars > 6000:
                        keep_from_index = i
                        break
                api_messages = [messages[0]] + messages[keep_from_index:]
            else:
                api_messages = messages

            spinner = Spinner()
            spinner.start()
            try:
                reply = client.chat.completions.create(
                    model=api["model"],
                    messages=api_messages,
                    tools=api_tools,
                )
                spinner.stop()
            except Exception as e:
                spinner.stop() 
                print(f"[API 错误] {e}")
                api_error_occurred = True
                break  # 跳出内层循环

            message = reply.choices[0].message
            
            if message.tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        } for tc in message.tool_calls
                    ]
                })
                
                # 执行所有工具
                for tool_call in message.tool_calls:
                    function_name = tool_call.function.name
                    try:
                        arguments = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                        
                    print(f" \033[35m[Agent 正在调用工具: {function_name}]\033[0m")
                    
                    result = "错误：未找到此工具"
                    for tool in AVAILABLE_TOOLS:
                        if tool.name == function_name:
                            try:
                                if function_name == "write_file":
                                    content_to_write = arguments.get("content", "")
                                    path_str = arguments.get("path", "")
                                    preview = "\n".join(content_to_write.splitlines()[:5])
                                    print(f"\n--- Agent 请求写入文件: {path_str} ---")
                                    print(f"{preview}\n...")
                                    
                                    ans = session.prompt("是否允许写入？[y/N] ").strip().lower()
                                    if ans != 'y':
                                        result = "写入失败：用户拒绝了写入操作。"
                                    else:
                                        result = tool.run(arguments)
                                else:
                                    result = tool.run(arguments)
                                    
                            except OutOfSandboxError as e:
                                target_path = arguments.get("path", "")
                                if target_path in authorized_paths:
                                    result = tool.run(arguments, force=True)
                                else:
                                    print(f"\n[安全警告] 尝试访问沙箱外部的文件：\n{e}")
                                    ans = session.prompt("是否允许本次读取/写入？[y/N] ").strip().lower()
                                    if ans == 'y':
                                        authorized_paths.add(target_path)
                                        result = tool.run(arguments, force=True) 
                                    else:
                                        result = "读取/写入被用户拒绝。"
                            except PermissionError as e:
                                result = f"安全拦截：权限不足 {e}"
                            except Exception as e:
                                result = f"执行错误：{e}"
                            break
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result)
                    })
                
                continue 
            else:
                raw_content = message.content
                content = storage.extract_and_save_memory(raw_content)
                print(f"\n\033[34mOmyDs > {content}\033[0m")
                messages.append({"role": "assistant", "content": content})
                break

        # 如果因为 API 报错（如上下文脏了导致 400），需要回滚，否则这轮记录会一直卡死
        if api_error_occurred:
            # 把这次对话（包括用户的输入和可能半截的工具结果）全部截断掉
            messages = messages[:msg_len_before_input]
            print(" \033[31m[系统：检测到 API 错误，已清理当前轮次损坏的上下文。请重试。]\033[0m")

    # === 退出时的保存逻辑 ===
    print("\n[退出]")
    
    if len(messages) <= 1:
        print("未产生对话，不保存。")
        return

    if not is_new_session:
        save_choice = input(f"是否覆盖保存到旧会话 '{session_name}'？[y/N] ").strip().lower()
        if save_choice == 'y':
            storage.save_session(session_name, messages)
            print("已覆盖保存。")
        else:
            print("已放弃本次更改。")
    else:
        save_choice = input("是否保存本次对话？[y/N] ").strip().lower()
        if save_choice == 'y':
            new_name = input("给这次对话起个名字：").strip()
            if new_name:
                storage.save_session(new_name, messages)
                print("已保存。")
        else:
            print("已放弃保存。")

if __name__ == "__main__":
    main()