"""API messages: preserve provider fields and trim only complete user turns."""
import copy
import json


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


def build_context(messages, max_chars=32000):
    """Soft character budget, not a token limit. Never split the active turn."""
    validate_messages(messages)
    system = [m for m in messages if m.get("role") == "system"]
    turns = []
    for m in messages:
        if m.get("role") == "system":
            continue
        if m.get("role") == "user" or not turns:
            turns.append([])
        turns[-1].append(m)
    size = lambda items: len(json.dumps(items, ensure_ascii=False))
    selected = []
    for turn in reversed(turns):
        candidate = turn + selected
        if selected and size(system + candidate) > max_chars:
            break
        selected = candidate
    result = system + selected
    validate_messages(result)
    return copy.deepcopy(result)
