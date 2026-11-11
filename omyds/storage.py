import json
from pathlib import Path

# 规定存在用户主目录下的 .omyds/sessions 里
SESSIONS_DIR = Path.home() / ".omyds" / "sessions"

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