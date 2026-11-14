from .read_file import ReadFileTool
from .write_file import WriteFileTool

# 注册工具
AVAILABLE_TOOLS = [
    ReadFileTool(),
    WriteFileTool()
]