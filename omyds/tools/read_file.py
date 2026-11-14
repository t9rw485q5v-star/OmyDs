from pathlib import Path
from ..security import validate_path, OutOfSandboxError

class ReadFileTool:
    def __init__(self):
        self.name = "read_file"
        self.description = "读取本地文件的内容。如果用户让你查看、阅读或分析文件，请调用此工具。"
        self.parameters = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件的相对或绝对路径"}
            },
            "required": ["path"]
        }

    def run(self, arguments: dict, force: bool = False) -> str:
        try:
            path_str = arguments.get("path")
            if force:
                safe_path = Path(path_str).expanduser().resolve()
            else:
                safe_path = validate_path(path_str)
                
            if not safe_path.is_file():
                return f"错误：{path_str} 不存在或不是一个文件。"
            
            with open(safe_path, "r", encoding="utf-8") as f:
                return f.read()
        except OutOfSandboxError:
            # 必须把越界异常抛给主程序，触发提权询问
            raise
        except PermissionError:
            # 隐藏底层系统的具体报错，防止路径泄漏
            return "错误：没有权限读取该文件（系统拦截或文件权限受限）。"
        except FileNotFoundError:
            return "错误：文件不存在，请检查路径是否正确。"
        except Exception as e:
            return f"读取失败：{str(e)}"