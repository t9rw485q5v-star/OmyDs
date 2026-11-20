"""API messages: preserve provider fields and trim only complete user turns."""
import copy
import json
from dataclasses import dataclass


DEFAULT_MAX_CHARS = 64000
DEFAULT_HISTORY_TOOL_CHARS = 4000


def context_settings(chat):
    """Validate user configuration without silently replacing a mistaken value."""
    budget = chat.get("max_context_chars", DEFAULT_MAX_CHARS)
    tool_chars = chat.get("history_tool_chars", DEFAULT_HISTORY_TOOL_CHARS)
    if type(budget) is not int or budget < 1024:
        raise ValueError("chat.max_context_chars 必须是至少 1024 的整数（字符数，非 token）")
    if type(tool_chars) is not int or (tool_chars != 0 and tool_chars < 256):
        raise ValueError("chat.history_tool_chars 必须为 0（不缩短）或至少 256 的整数")
    return budget, tool_chars


@dataclass(frozen=True)
class ContextInfo:
    chars: int
    budget: int
    kept_turns: int
    dropped_turns: int
    shortened_results: int

    @property
    def over_budget(self):
        return self.chars > self.budget

    @property
    def notice_key(self):
        return self.dropped_turns, self.shortened_results, self.over_budget

    def description(self):
        text = (f"请求上下文约 {self.chars:,}/{self.budget:,} 字符 · 保留 {self.kept_turns} 轮"
                f" · 未发送 {self.dropped_turns} 轮 · 缩短 {self.shortened_results} 条旧工具结果。")
        if self.over_budget:
            text += " 当前轮次或系统提示超出预算，仍完整保留；可能超过模型上限。"
        return text


class ContextError(ValueError):
    pass


def assistant_message(message):
    if hasattr(message, "model_dump"):
        raw = message.model_dump(exclude_none=True)
    else:
        raw = dict(message)
    # Only request-compatible fields; preserve empty reasoning strings too.
    result = {"role": "assistant", "content": raw.get("content")}
    for key in ("reasoning_content", "tool_calls"):
        if key in raw:
            result[key] = copy.deepcopy(raw[key])
    calls = result.get("tool_calls") or []
    ids = set()
    for call in calls:
        function = call.get("function") or {}
        if (not isinstance(call.get("id"), str) or not call["id"]
                or call["id"] in ids or call.get("type") != "function"
                or not isinstance(function.get("name"), str)
                or not isinstance(function.get("arguments"), str)):
            raise ContextError("API 返回了不完整或重复的工具调用，本批次未执行。")
        ids.add(call["id"])
    return result


def validate_messages(messages):
    pending = set()
    for m in messages:
        if not isinstance(m, dict):
            raise ContextError("会话包含非字典消息，请检查会话文件。")
        role = m.get("role")
        if pending:
            if role != "tool" or m.get("tool_call_id") not in pending:
                raise ContextError("工具调用与结果不配对；没有发送请求或执行工具。")
            pending.remove(m["tool_call_id"])
        elif role == "tool":
            raise ContextError("存在没有对应调用的工具结果。")
        calls = m.get("tool_calls") or []
        if calls:
            if role != "assistant":
                raise ContextError("tool_calls 必须属于 assistant 消息。")
            ids = [c.get("id") for c in calls]
            if not all(ids) or len(set(ids)) != len(ids):
                raise ContextError("工具调用 ID 缺失或重复。")
            pending.update(ids)
    if pending:
        raise ContextError("存在没有结果的工具调用。")


def prepare_context(messages, max_chars=DEFAULT_MAX_CHARS,
                    history_tool_chars=DEFAULT_HISTORY_TOOL_CHARS, extra_system=""):
    """Prepare a request copy. Preserve tool pairs, reasoning and the active turn."""
    validate_messages(messages)
    messages = copy.deepcopy(messages)
    system = [m for m in messages if m.get("role") == "system"]
    if extra_system:
        if not system:
            system.append({"role": "system", "content": ""})
        system[0]["content"] = (system[0].get("content") or "") + extra_system
    turns = []
    for m in messages:
        if m.get("role") == "system":
            continue
        if m.get("role") == "user" or not turns:
            turns.append([])
        turns[-1].append(m)
    size = lambda items: len(json.dumps(items, ensure_ascii=False))
    shortened = set()
    # Only shorten old tool output when the complete request exceeds the budget.
    # Current-turn results and all reasoning_content stay byte-for-byte intact.
    if history_tool_chars and size(system + [m for t in turns for m in t]) > max_chars:
        for turn in turns[:-1]:
            for m in turn:
                content = m.get("content")
                if m.get("role") == "tool" and isinstance(content, str) and len(content) > history_tool_chars:
                    marker = "\n[旧工具结果中段已省略；完整记录仍在会话中]\n"
                    available = history_tool_chars - len(marker)
                    head = available * 3 // 4
                    tail = available - head
                    m["content"] = content[:head] + marker + content[-tail:]
                    shortened.add(id(m))
    selected = []
    kept = 0
    for turn in reversed(turns):
        candidate = turn + selected
        if selected and size(system + candidate) > max_chars:
            break
        selected = candidate
        kept += 1
    result = system + selected
    validate_messages(result)
    info = ContextInfo(size(result), max_chars, kept, len(turns) - kept,
                       sum(id(m) in shortened for m in selected))
    return result, info


def build_context(messages, max_chars=DEFAULT_MAX_CHARS):
    """Compatibility entry point; return only request messages."""
    return prepare_context(messages, max_chars)[0]
