import re
import sys
import threading
import time
import itertools
from openai import OpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from pathlib import Path
from .config import load_config, get_system_prompt
from . import storage
from .security import validate_path
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion


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
    """只对以 / 开头的命令进行历史补全，并包含默认预设"""
    def get_suggestion(self, buffer, document):
        text = document.text
        if not text.startswith("/"):
            return None
            
        # 预设的命令字典
        default_commands = ["/read ", "/help ","/history"]
        
        # 1. 先在预设里找
        for cmd in default_commands:
            if cmd.startswith(text) and cmd != text:
                return Suggestion(cmd[len(text):])
                
        # 2. 如果预设没有，再去历史记录里找
        for string in reversed(buffer.history.get_strings()):
            if string.startswith("/") and string.startswith(text) and string != text:
                return Suggestion(string[len(text):])
                
        return None


# === 只保存 / 命令的历史类(v0.1.4.12) ===
class CommandOnlyHistory(FileHistory):
    """只保存以 / 开头的命令，忽略普通聊天"""
    def append_string(self, string):
        if string.startswith("/") and string != "/":
            super().append_string(string)

def main():
    cfg = load_config()
    api = cfg["api"]
    system_prompt = get_system_prompt(cfg)

    # === 1. Longterm-memory(for v0.1.3) ===
    memory_file = Path.home() / ".omyds" / "memory.md"
    if memory_file.exists():
        with open(memory_file, "r", encoding="utf-8") as f:
            memory_content = f.read().strip()
            if memory_content:
                system_prompt += f"\n\n【用户长期记忆档案】\n{memory_content}"

    client = OpenAI(api_key=api["key"], base_url=api["base_url"])

    # === 2. 选择或新建会话 ===
    sessions = storage.list_sessions()
    print("--- OmyDs v0.1.2 ---")
    
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

    # 初始化 prompt_toolkit（换用我们自定义的类）
    history_file = Path.home() / ".omyds_history"
    session = PromptSession(
        history=CommandOnlyHistory(str(history_file)),
        auto_suggest=CommandAutoSuggest()
    )

    # === 3. 聊天主循环 ===
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
        
        # /help
        if user_input.lower() == "/help":
            print("\n\033[36m=== OmyDs 帮助 ===\033[0m")
            print("  /history              显示过往聊天的历史记录")
            print("  /read <路径>          读取文件（如: /read README.md）")
            print("  /read <路径> | <需求> 读取文件并要求 AI 处理（如: /read main.py | 帮我查错）")
            print("  exit / quit           退出聊天")
            print("  其他任意文字          直接与 AI 聊天\n")
            continue

        # 拦截 /history 指令
        if user_input.lower() == "/history":
            print("\n\033[36m=== 当前会话历史记录 ===\033[0m")
            for msg in messages:
                # 过滤掉最前面的 system prompt，里面全是设定和记忆，太长了
                if msg["role"] == "system":
                    continue
                
                role_name = "\033[34m你\033[0m" if msg["role"] == "user" else "\033[33mOmyDs\033[0m"
                
                # 用户发的内容里如果有 <file>，为了终端清爽，我们截断显示
                content = msg["content"]
                if len(content) > 200:
                    content = content[:200] + "\n...(内容过长已截断，仅展示前 200 字)"
                    
                print(f"\n[{role_name}]:\n{content}")
                
            print("\n\033[36m======================\033[0m\n")
            continue

        # === 解析用户输入中任意位置的 /read 指令 (v0.1.4.12)===
        # 匹配格式： /read 路径 [| 需求] 或者 /read 路径 （直到遇到换行或结尾）
        read_pattern = r"/read\s+([^|\n]+)(?:\|\s*([^\n]+))?"
        match = re.search(read_pattern, user_input)
        
        if match:
            file_path_str = match.group(1).strip()
            user_prompt = match.group(2).strip() if match.group(2) else ""
            
            # 把原本输入里的 /read... 去掉，剩下的就是用户的前言或后语
            text_without_read = re.sub(read_pattern, "", user_input).strip()
            
            try:
                safe_path = validate_path(file_path_str)
                if safe_path.is_file():
                    with open(safe_path, "r", encoding="utf-8") as f:
                        file_content = f.read()
                    
                    # 重新组装消息
                    injected_msg = ""
                    if text_without_read:
                        injected_msg += f"{text_without_read}\n\n"
                        
                    injected_msg += f'<file path="{file_path_str}" bytes="{len(file_content)}">\n{file_content}\n</file>'
                    
                    if user_prompt:
                        injected_msg += f"\n\n用户需求：{user_prompt}"
                    
                    print(f" \033[32m[系统：已成功读取 {file_path_str}]\033[0m")
                    user_input = injected_msg
                else:
                    print(f" \033[31m[系统：路径不是文件或不存在]\033[0m")
                    continue
            except PermissionError as e:
                print(f" \033[31m[系统拦截：{e}]\033[0m")
                continue

        # 把用户的话加入完整历史
        messages.append({"role": "user", "content": user_input})

        # 上下文截断
        total_chars = sum(len(m["content"]) for m in messages)
        MAX_CHARS = 8000
        
        if total_chars > MAX_CHARS:
            keep_chars = 0
            keep_from_index = len(messages)
            for i in range(len(messages) - 1, 0, -1):
                keep_chars += len(messages[i]["content"])
                if keep_chars > 6000:
                    keep_from_index = i
                    break
            
            api_messages = [messages[0]] + messages[keep_from_index:]
        else:
            api_messages = messages

        # 发起 API 请求
        spinner = Spinner()
        spinner.start()
        try:
            reply = client.chat.completions.create(
                model=api["model"],
                messages=api_messages, 
            )
            spinner.stop()
        except Exception as e:
            spinner.stop() 
            print(f"[API 错误] {e}")
            messages.pop()
            continue

        raw_content = reply.choices[0].message.content
        content = storage.extract_and_save_memory(raw_content)

        print(f"\n\033[34mOmyDs > {content}\033[0m")
        messages.append({"role": "assistant", "content": content})

    # === 4. 退出时的保存逻辑 ===
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