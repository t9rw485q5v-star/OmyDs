"""One result per call, including denial and failures during an approved retry."""
import json
from . import security


class ToolExecutor:
    def __init__(self, tools, ui):
        self.tools = {tool.name: tool for tool in tools}
        self.ui = ui
        self.cancelled = False

    @property
    def schemas(self):
        return [{"type": "function", "function": {
            "name": t.name, "description": t.description, "parameters": t.parameters
        }} for t in self.tools.values()]

    def execute(self, call):
        try:
            name = call["function"]["name"]
            arguments = json.loads(call["function"]["arguments"])
            if not isinstance(arguments, dict):
                raise ValueError("工具参数必须为 JSON 对象")
            tool = self.tools.get(name)
            if tool is None:
                return f"客户端错误：未知工具 {name}"
            for key in tool.parameters.get("required", []):
                if key not in arguments:
                    raise ValueError(f"缺少参数 {key}")
            for key, value in arguments.items():
                spec = tool.parameters.get("properties", {}).get(key, {})
                if spec.get("type") == "string" and not isinstance(value, str):
                    raise ValueError(f"{key} 必须是字符串")
                if "enum" in spec and value not in spec["enum"]:
                    raise ValueError(f"{key} 不在允许值中")
            self.ui.say(f"[工具] {name}")
            if name == "run_command":
                if not self.ui.confirm_tool(name, arguments, security.ALLOWED_ROOT):
                    return self.denied()
                return str(tool.run(arguments))
            if name in {"read_file", "write_file"}:
                # Canonicalize once before displaying/authorizing; retries use the same path.
                arguments["path"] = str(security.resolve_path(arguments["path"]))
                try:
                    security.validate_path(arguments["path"])
                except security.OutOfSandboxError:
                    if not self.ui.confirm_tool(name, arguments, security.ALLOWED_ROOT, outside=True):
                        return self.denied()
                    return str(tool.run(arguments, force=True))
            return str(tool.run(arguments))
        except (KeyboardInterrupt, EOFError):
            self.cancelled = True
            return "用户中断了授权或工具执行；执行状态可能不确定，请先检查，不要直接重做。"
        except Exception as exc:
            return f"工具执行错误：{type(exc).__name__}: {exc}"

    @staticmethod
    def denied():
        return ("用户拒绝了本次操作，未执行。不要重复请求或改用其他工具绕过拒绝；"
                "请说明替代方案，或提供代码供用户自行执行，等待新的明确指示。")
