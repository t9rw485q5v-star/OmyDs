"""One result per call; permissions come only from the local conversation."""
import copy
import inspect
import json
from . import security
from .permissions import Mode
from .context import DEFAULT_MAX_CHARS, DEFAULT_HISTORY_TOOL_CHARS


class ToolCompatibilityError(RuntimeError):
    """A local installation mismatch, not a model/tool argument error."""


def validate_tool_interfaces(tools):
    """Check client-owned command flags before starting a model conversation."""
    for tool in tools:
        if tool.name != "run_command":
            continue
        try:
            inspect.signature(tool.run).bind({}, host=False, network=False)
        except (TypeError, ValueError) as exc:
            source = inspect.getfile(type(tool))
            raise ToolCompatibilityError(
                "run_command 接口不匹配：需要 run(arguments, *, host=False, network=False)。\n"
                f"实际加载: {source}\n"
                "请完整覆盖 omyds/tools/run_command.py 与 omyds/tool_executor.py，"
                "退出旧进程后，从项目根目录重新运行 uv run OmyDs。"
                "不会忽略联网设置，也不会自动切换 danger-full。"
            ) from exc


class ToolExecutor:
    def __init__(self, tools, ui, mode=Mode.WORKSPACE):
        self.tools = {tool.name: tool for tool in tools}
        validate_tool_interfaces(self.tools.values())
        self.ui = ui
        self.mode = mode
        self.web_enabled = False
        self.max_context_chars = DEFAULT_MAX_CHARS
        self.history_tool_chars = DEFAULT_HISTORY_TOOL_CHARS
        self.context_notice = None
        self.cancelled = False

    @property
    def schemas(self):
        result = []
        for tool in self.tools.values():
            parameters = copy.deepcopy(tool.parameters)
            parameters.setdefault("properties", {}).update({
                "purpose": {"type": "string", "description": "用简明中文说明本步骤具体要完成什么目标"},
                "impact": {"type": "string", "description": "说明将读取/创建/覆盖/删除哪些内容，是否联网；不确定时明确说不确定"},
            })
            parameters["required"] = list(dict.fromkeys(parameters.get("required", []) + ["purpose", "impact"]))
            parameters["additionalProperties"] = False
            result.append({"type": "function", "function": {
                "name": tool.name, "description": tool.description, "parameters": parameters,
            }})
        return result

    def execute(self, call):
        try:
            name = call["function"]["name"]
            arguments = json.loads(call["function"]["arguments"])
            if not isinstance(arguments, dict):
                raise ValueError("工具参数必须为 JSON 对象")
            tool = self.tools.get(name)
            if tool is None:
                return f"客户端错误：未知工具 {name}"
            spec = next(s["function"]["parameters"] for s in self.schemas
                        if s["function"]["name"] == name)
            for key in spec["required"]:
                if key not in arguments:
                    raise ValueError(f"缺少参数 {key}；请先说明目的和影响，尚未执行")
            for key, value in arguments.items():
                if key not in spec["properties"]:
                    raise ValueError(f"不支持参数 {key}；权限只能由用户通过客户端指令切换")
                field = spec["properties"][key]
                if field.get("type") == "string" and not isinstance(value, str):
                    raise ValueError(f"{key} 必须是字符串")
                if "enum" in field and value not in field["enum"]:
                    raise ValueError(f"{key} 不在允许值中")
            for key in ("purpose", "impact"):
                if not arguments[key].strip():
                    raise ValueError(f"{key} 不能为空，尚未执行")

            host = self.mode == Mode.DANGER_FULL
            outside = False
            if name in {"read_file", "write_file"}:
                arguments["path"] = str(security.resolve_path(arguments["path"]))
                outside = not security.resolve_path(arguments["path"]).is_relative_to(security.ALLOWED_ROOT)
                try:
                    security.validate_path(arguments["path"], host=host)
                except security.OutOfSandboxError:
                    pass  # Only this boundary is overridable by a single-file confirmation.
            needs_confirmation = not host and (
                outside or (self.mode == Mode.ASK and name in {"run_command", "write_file"})
            )
            # Display declared intent separately from facts determined by this client.
            self.ui.describe_tool(name, arguments, security.ALLOWED_ROOT, self.mode, outside,
                                  web_enabled=self.web_enabled)
            if needs_confirmation and not self.ui.confirm_tool(
                name, arguments, security.ALLOWED_ROOT, outside=outside
            ):
                return self.denied()
            tool_args = {k: v for k, v in arguments.items() if k not in {"purpose", "impact"}}
            if name == "run_command" and not host:
                return str(tool.run(tool_args, network=self.web_enabled))
            if host:
                return str(tool.run(tool_args, host=True))
            if outside:
                return str(tool.run(tool_args, force=True))
            return str(tool.run(tool_args))
        except (KeyboardInterrupt, EOFError):
            self.cancelled = True
            return "用户中断了授权或工具执行；执行状态可能不确定，请先检查，不要直接重做。"
        except Exception as exc:
            return f"工具执行错误：{type(exc).__name__}: {exc}"

    @staticmethod
    def denied():
        return ("用户拒绝了本次操作，未执行。不要重复请求或改用其他工具绕过拒绝；"
                "请说明替代方案，或提供代码供用户自行执行，等待新的明确指示。")
