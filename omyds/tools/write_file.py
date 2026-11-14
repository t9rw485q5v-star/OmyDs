from pathlib import Path
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

    def run(self, arguments: dict, force: bool = False) -> str:
        try:
            path_str = arguments.get("path")
            content = arguments.get("content")
            mode = arguments.get("mode", "overwrite")
            
            # 路径校验
            if force:
                safe_path = Path(path_str).expanduser().resolve()
            else:
                safe_path = validate_path(path_str)

            # 执行写入
            if mode == "append":
                with open(safe_path, "a", encoding="utf-8") as f:
                    f.write(content)
                return "追加写入成功。"
            else:
                # 覆盖写入：使用临时文件 + 原子替换，防止写一半断电导致文件损坏
                tmp_path = safe_path.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(content)
                tmp_path.replace(safe_path)
                return "覆盖写入成功。"
                
        except OutOfSandboxError:
            # 抛出这个异常，让主程序弹窗询问用户
            raise
        except PermissionError:
            return "错误：没有权限修改该文件。"
        except FileNotFoundError:
            return "错误：目标文件的父目录不存在。"
        except Exception as e:
            return f"写入失败：{str(e)}"