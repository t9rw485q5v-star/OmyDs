from openai import OpenAI
from .config import load_config
from prompt_toolkit import prompt

def main():
    cfg = load_config()
    api = cfg["api"]
    system_prompt = cfg["chat"]["system_prompt"]

    client = OpenAI(api_key=api["key"], base_url=api["base_url"])

    messages = [
        {"role": "system", "content": system_prompt}
    ]

    print("OmyDs v0.1 — 输入 exit 退出")

    while True:
        try:
            user_input = prompt(" >> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            break

        messages.append({"role": "user", "content": user_input})

        try:
            reply = client.chat.completions.create(
                model=api["model"],
                messages=messages,
            )
        except Exception as e:
            print(f"[API 错误] {e}")
            messages.pop()
            continue

        content = reply.choices[0].message.content
        print(f"\nOmyDs > {content}")

        messages.append({"role": "assistant", "content": content})


if __name__ == "__main__":
    main()