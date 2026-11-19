import os
import tempfile
from ..security import validate_path, OutOfSandboxError

class WriteFileTool:
    def __init__(self):
        self.name = "write_file"
        self.description = "将内容写入到本地文件。需要追加内容请用 append 模式，需要覆盖整个文件请用 overwrite 模式。"
        self.parameters = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件的路径"},
                "content": {"type": "string", "description": "要写入的完整内容"},
                "mode": {
                    "type": "string", 
                    "enum": ["overwrite", "append"],
                    "description": "写入模式。overwrite 为覆盖原文件，append 为在文件末尾追加。默认 overwrite。"
                }
            },
            "required": ["path", "content"]
        }

    def run(self, arguments: dict, force: bool = False, *, host: bool = False) -> str:
        try:
            path_str = arguments.get("path")
            content = arguments.get("content")
            mode = arguments.get("mode", "overwrite")
            
            safe_path = validate_path(path_str, allow_outside=force, host=host)
            if mode not in {"append", "overwrite"}:
                raise ValueError("mode 必须是 append 或 overwrite")
            if not isinstance(content, str):
                raise ValueError("content 必须是字符串")
            if mode == "append":
                with open(safe_path, "a", encoding="utf-8") as f:
                    f.write(content)
                return "追加写入成功。"
            temp_name = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=safe_path.parent,
                    prefix=".omyds-write-", delete=False
                ) as f:
                    temp_name = f.name
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                if safe_path.exists():
                    os.chmod(temp_name, safe_path.stat().st_mode & 0o777)
                os.replace(temp_name, safe_path)
                return "覆盖写入成功。"
            finally:
                if temp_name and os.path.exists(temp_name):
                    os.unlink(temp_name)

        except OutOfSandboxError:
            # 抛出这个异常，让主程序弹窗询问用户
            raise
        except PermissionError:
            return "错误：没有权限修改该文件。"
        except FileNotFoundError:
            return "错误：目标文件的父目录不存在。"
        except Exception as e:
            return f"写入失败：{str(e)}"