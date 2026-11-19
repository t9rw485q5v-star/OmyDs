# OmyDs

**A lightweight, customizable terminal AI assistant that remembers what matters and helps get things done.**

[简体中文](README.md) · English

OmyDs (O my DeepSeek) starts with everyday terminal use: conversation, file operations, shell commands, and important memories carried across sessions. Shape its voice, choose a workspace, and explicitly control its operating permissions.

The long-term direction is a personal assistant connected to more devices and services. Today it is a terminal application. Remote access, home automation, scheduled tasks, and payments remain future directions.

## Features

- Natural-language access to file-reading, file-writing, and shell tools.
- Multiple saved sessions, conversation history, and a session menu.
- Local persistent memory and customizable roles through agent.md.
- Workspace automation, individual approval, and explicit host modes.
- Action descriptions showing purpose, expected impact, actual paths, and commands.
- Markdown output, role colors, slash-command suggestions, and command history.

## Quick start

### Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/).
- API credentials for a model supporting tool calling.
- Linux, the current target for full tool execution.
- bubblewrap (bwrap) for sandboxed commands.
- setpriv (usually provided by util-linux) for host mode.

Install system utilities through your distribution's package manager. Native command execution on macOS and Windows is not yet supported. With WSL, install and run inside the Linux environment.

### Configure and run

Download or clone the repository, then run from its root:

~~~bash
uv sync
cp config.example.toml config.toml
cp agent.example.md agent.md
~~~

Edit **config.toml** and set **key, base_url, and model** under **[api]**. Start the application:

~~~bash
uv run OmyDs
~~~

The module entry point is also available:

~~~bash
uv run python -m omyds
~~~

Keep existing configuration when upgrading; do not overwrite it with the examples. Running from a source checkout is currently recommended. These steps do not install a system-wide command.

DeepSeek is the primary API target. The endpoint and model are configurable, but tool-calling behavior and extension fields may differ across compatible providers. Other providers require validation; universal compatibility is not claimed.

## Usage

Enter a session and describe a task, for example:

> Create notes.txt in the current workspace with today's reading plan.

> Read notes.txt and summarize its items.

The default workspace is the project's **sandbox/** directory. To work elsewhere, select an existing directory:

~~~text
/set-project-root-in /absolute/path/to/project
~~~

Home-directory expansion (~) and relative paths are supported. Relative workspace paths are resolved from the directory where OmyDs was launched. The next model request includes the current workspace and permission mode.

| Command | Purpose |
| --- | --- |
| /help | Show command help |
| /history | Show the current conversation |
| /return | Save or discard changes and return to the menu |
| /retry | Continue an unfinished model request |
| /permissions | Show current permissions and workspace |
| /safe | Switch to automatic workspace mode |
| /permissions ask | Confirm writes and commands individually |
| /danger-full | Enable host mode for this session after confirmation |
| /set-project-root-in &lt;path&gt; | Change the workspace |
| /reset-project-root | Restore the default workspace |
| exit / quit | Exit |

Normal exit or return prompts to save changed conversations; this is not autosave. Failed requests retain tool records. /retry does not itself replay completed tools, although the model may propose a new duplicate action.

## Permissions and execution scope

| Mode | Workspace files | Shell commands | Outside files |
| --- | --- | --- | --- |
| workspace (default) | Automatic | Sandboxed by bwrap, without individual prompts | Individual approval for ordinary files; some paths restricted |
| ask | Automatic reads, approved writes | Sandboxed by bwrap, with approval | Individual approval for ordinary files; some paths restricted |
| danger-full | Automatic | Host execution as the current non-root user | OS permissions apply; no individual prompts |

A workspace is a real directory, not a copy. All its contents, including hidden files, are in scope. Changes and deletions are not automatically rolled back. File tools use path checks. Sandboxed commands mount the workspace and read-only system runtime directories, with external command networking disabled. Sandbox failures never silently fall back to host execution.

danger-full can access personal files and the network, including credentials and OmyDs itself. It does not automatically grant sudo/root, refuses activation from a root process, and uses setpriv to prevent privilege gains through program execution. This is not filesystem or network isolation.

Modes apply only to the current conversation. Entering another session restores the default mode and workspace. /safe restores the sandbox policy without undoing previous actions. Changing a directory does not change the permission mode.

Model-generated purpose and impact statements are explanations, not independent security audits. Neither prompt-injection resistance nor sandboxing is an absolute guarantee.

## Roles, memory, and data

| Content | Location | Loaded when |
| --- | --- | --- |
| Role and behavior | agent.md in the project root | Entering a session |
| Persistent memory | ~/.omyds/memory.md | Entering a session |
| Saved conversations | ~/.omyds/sessions/*.json | Selecting a saved session |
| Slash-command history | ~/.omyds_history | Used for history and input suggestions |
| API configuration | config.toml in the project root | Starting the application |

Role configuration follows this order: **agent.md → agent.example.md → chat.system_prompt in config.toml**.

Memory is extracted from markers in the same model reply without a separate filtering request. You can edit or remove entries and enter a session again. It does not guarantee perfect recall, and loading the full memory consumes input context.

Saved session files retain messages, while history sent to the model is trimmed to a budget. Automatic retrieval across old sessions is not currently available. Storing reminders or schedules in memory does not create executable background tasks.

Use **greet.toml** to customize the startup greeting. Setting remind = false disables the greeting text, not the logo.

**Local storage does not mean offline operation.** Conversations, loaded memories, system instructions, and tool-read content are sent to the configured model service as part of requests. Saved sessions may include tool results and model-returned reasoning fields. Do not publish private configurations, sessions, or memories. Adding a file to .gitignore does not untrack an already tracked file.

## Development and contributions

Keep responsibilities clear, code readable, and improvements grounded in actual use. Reproducible bug reports, documentation fixes, and focused contributions are welcome.

Run regression tests from the project root:

~~~bash
uv run python -m unittest discover -s tests -v
~~~

Some environments cannot start bwrap; distinguish skipped tests from passing tests. Report your system, mode, reproduction steps, and redacted errors. Do not include API keys.

The README describes the project, installation, and stable usage. Version-specific changes belong in the [CHANGELOG](CHANGELOG.md). Update both README files when usage or capability boundaries change, rather than for every patch.

## License

[MIT](LICENSE)

*O my DeepSeek. Starting in the terminal, remembering what matters.*
