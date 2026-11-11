import sys
from openai import OpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from pathlib import Path
from .config import load_config
from . import storage

def main():
    cfg = load_config()
    api = cfg["api"]
    system_prompt = cfg["chat"]["system_prompt"]

    # === 1. 长期记忆接口 (v0.1.3 预留) ===
    # 如果你想写点什么让 OmyDs 永远记住，就写在 ~/.omyds/memory.md 里
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
                # 选择了老会话，注意这里用 sessions[idx - 1] 确保名字完全一致（包括空格）
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

    while True:
        try:
            user_input = session.prompt("\n >> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            # 如果是 Ctrl+C 强退，为了防丢数据，可以在这里跳出循环
            # 但为简单起见，我们直接 break，后面统一处理保存逻辑
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            break

        messages.append({"role": "user", "content": user_input})

        try:
            reply = client.chat.completions.create(
                model=api["model"],
                messages=messages,
            )
        except Exception as e:
            print(f"[API 错误] {e}")
            messages.pop() # 回滚
            continue

        content = reply.choices[0].message.content
        print(f"\nOmyDs > {content}")
        messages.append({"role": "assistant", "content": content})

    # === 3. 退出时的保存逻辑 ===
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