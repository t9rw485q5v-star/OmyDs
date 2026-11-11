import json
import re
from pathlib import Path

# 规定存在用户主目录下的 .omyds/sessions 里
SESSIONS_DIR = Path.home() / ".omyds" / "sessions"
MEMORY_FILE = Path.home() / ".omyds" / "memory.md"

def list_sessions() -> list[str]:
    """列出所有已保存的对话"""
    if not SESSIONS_DIR.exists():
        return []
    # 用列表推导式，把所有的 json 文件提取出来
    return [p.stem for p in SESSIONS_DIR.glob("*.json")]

def load_session(name: str) -> list:
    """读取特定会话的消息列表"""
    file_path = SESSIONS_DIR / f"{name}.json"
    if not file_path.exists():
        return []
    # 先打开文件，再交给 json.load
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_session(name: str, messages: list):
    """保存消息列表到文件"""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = SESSIONS_DIR / f"{name}.json"
    # 写入 JSON，ensure_ascii=False 保证中文正常显示，indent=2 让文件排版好看
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

# 长期记忆(v0.1.3)
def extract_and_save_memory(text: str) -> str:
    """从 AI 的回复中提取 [MEMORY: ...]，保存并返回清理后的文本"""
    pattern = r"\[MEMORY:\s*(.*?)\]"
    match = re.search(pattern, text, re.DOTALL)
    
    if match:
        mem_content = match.group(1).strip()
        # 写入文件
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(f"- {mem_content}\n")

        # 终端提示
        print(f" \033[32m[系统：已更新长期记忆 -> {mem_content}]\033[0m")

        # 把标记从给用户看的文本中删掉
        cleaned_text = re.sub(pattern, "", text).strip()
        return cleaned_text
    return text