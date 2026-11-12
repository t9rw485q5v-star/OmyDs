import sys
from openai import OpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from pathlib import Path
from .config import load_config, get_system_prompt
from . import storage

def main():
    cfg = load_config()

    api = cfg["api"]
    system_prompt = get_system_prompt(cfg)


    # === 1. Longterm-memory(for v0.1.3) ===
    # 如果你想写点什么让 OmyDs 永远记住，写在 ~/.omyds/memory.md 里
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
        
        # 如果用户输入了数字
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(sessions):
                # 选择了老会话，确保名字完全一致
                session_name = sessions[idx - 1]
                messages = storage.load_session(session_name)
                print(f"已加载会话：{session_name}")
            else:
                # 输入了 0 或者超出的数字，当作新建
                is_new_session = True
        else:
            # 瞎敲或者直接回车，当作新建
            is_new_session = True
    else:
        print("(无历史对话，直接新建)")
        is_new_session = True
        
    if is_new_session:
        session_name = None
        messages = [{"role": "system", "content": system_prompt}]
            
    print(f"\n已进入对话。输入 exit 或 quit 退出。")

    # 初始化 prompt_toolkit (带有历史记录，防止按↑出不来)
    history_file = Path.home() / ".omyds_history"
    session = PromptSession(history=FileHistory(str(history_file)))

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

        # 把用户的话加入完整历史
        messages.append({"role": "user", "content": user_input})

        # === v0.1.2.11 补丁：上下文截断 ===
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
            
            # 生成临时列表
            api_messages = [messages[0]] + messages[keep_from_index:]
            ##print(" \033[33m[系统提示：历史对话过长，本次请求已自动截断旧消息，但本地记录依然完整]\033[0m")
        else:
            api_messages = messages

        # 发起 API 请求
        try:
            reply = client.chat.completions.create(
                model=api["model"],
                messages=api_messages, 
            )
        except Exception as e:
            print(f"[API 错误] {e}")
            messages.pop() # 回滚用户刚说的话，防止脏数据
            continue

        raw_content = reply.choices[0].message.content

        # === 让 storage 去检查并保存记忆，返回清理后的文本 ===
        content = storage.extract_and_save_memory(raw_content)

        print(f"\nOmyDs > {content}")
        
        # 把 AI 的话也加入完整历史
        messages.append({"role": "assistant", "content": content})

    # === 4. 退出时的保存逻辑 ===
    print("\n[退出]")
    
    # 如果除了 system 消息之外，没有任何对话，就不保存了
    if len(messages) <= 1:
        print("未产生对话，不保存。")
        return

    # 如果是老会话，就问是否覆盖；如果是新会话，问是否保存并起名
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