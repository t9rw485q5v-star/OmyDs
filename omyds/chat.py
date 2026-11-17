"""Agent loop independent of terminal UI and session selection."""
from .context import assistant_message, build_context, ContextError
from . import storage


def run_turn(client, api, messages, executor, ui, user_input=None,
             max_steps=16, max_chars=32000):
    if user_input is not None:
        messages.append({"role": "user", "content": user_input})
    executor.cancelled = False
    for _ in range(max_steps):
        try:
            request_messages = build_context(messages, max_chars)
            kwargs = {}
            if api.get("thinking") in ("enabled", "disabled"):
                kwargs["extra_body"] = {"thinking": {"type": api["thinking"]}}
            with ui.busy():
                reply = client.chat.completions.create(
                    model=api["model"], messages=request_messages,
                    tools=executor.schemas, **kwargs)
            message = assistant_message(reply.choices[0].message)
        except (KeyboardInterrupt, EOFError):
            ui.say("已中断请求；现有工具记录保留，可用 /retry 继续。")
            return False
        except Exception as exc:
            ui.say(f"[请求失败] {type(exc).__name__}: {exc}")
            ui.say("保留了当前对话及工具结果；/retry 仅继续请求，不重跑已有工具。")
            if isinstance(exc, ContextError):
                ui.say("旧会话可能已有损坏；请先用新建会话验证，不自动删除原始记录。")
            return False
        messages.append(message)
        calls = message.get("tool_calls") or []
        if calls:
            for call in calls:
                result = ("用户已中断，本工具未执行。" if executor.cancelled
                          else executor.execute(call))
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            if executor.cancelled:
                ui.say("已停止本轮，未执行的工具已补上取消结果。")
                return False
            continue
        content = message.get("content") or ""
        try:
            content = storage.extract_and_save_memory(content)
        except Exception as exc:
            ui.say(f"[记忆保存失败] {exc}")
        message["content"] = content
        ui.answer(content or "（模型没有返回正文。）")
        return True
    ui.say(f"已达到本轮 {max_steps} 次请求上限，工具记录保留；可用 /retry 继续。")
    return False
