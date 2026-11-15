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
    return [p.stem for p in SESSIONS_DIR.glob("*.json")]

def load_session(name: str) -> list:
    """读取特定会话的消息列表"""
    file_path = SESSIONS_DIR / f"{name}.json"
    if not file_path.exists():
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_session(name: str, messages: list):
    """保存消息列表到文件（只保存纯对话，过滤掉系统提示词以实现热更新）"""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = SESSIONS_DIR / f"{name}.json"
    
    # === 核心改动：过滤掉 system 角色 (v0.1.7) ===
    clean_messages = [m for m in messages if m.get("role") != "system"]
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(clean_messages, f, ensure_ascii=False, indent=2)

# 长期记忆(v0.1.3)
def extract_and_save_memory(text: str) -> str:
    # 匹配 [] 或者 【】 包裹的 MEMORY:
    pattern = r"[\[【]\s*MEMORY:\s*(.*?)\s*[\]】]"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    
    if match:
        mem_content = match.group(1).strip()

        # 如果提取出的是“无”、“没有”这种无效词，过滤掉
        if mem_content in ["无", "没有", "none", "None", "无。", "暂无"]:
            mem_content = ""

        # 只有内容不为空，才进行写入
        if mem_content:
            MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            # === 去重逻辑(v0.1.3.12) ===
            existing_memories = ""
            if MEMORY_FILE.exists():
                with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                    existing_memories = f.read()
            
            # 如果新的记忆内容已经在文件里了，就不写了
            if mem_content not in existing_memories:
                with open(MEMORY_FILE, "a", encoding="utf-8") as f:
                    f.write(f"- {mem_content}\n")
                print(f" \033[32m[系统：已更新长期记忆 -> {mem_content}]\033[0m")
            # ====================
            
        # 无论是否写入，都要把标记从用户看到的文本里删掉
        cleaned_text = re.sub(pattern, "", text).strip()
        return cleaned_text
        
    return text