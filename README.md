# Openlink AI

A local-first AI assistant that runs in your **terminal**, **web browser**, and **VS Code** — powered by your choice of AI provider (free models included).

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![License](https://img.shields.io/badge/License-Apache%202.0-green)

## Features

- **Terminal chat** — streaming responses with a rich, interactive prompt
- **Web UI** — local chat interface served at `http://127.0.0.1:8377/`
- **VS Code integration** — chat terminal inside VS Code with a companion extension
- **Multiple providers** — OpenRouter, Groq, SiliconFlow, Ollama (local), and custom OpenAI-compatible APIs
- **Free models built in** — Nemotron, Gemma, Qwen, and more via free tiers
- **Slash commands** — `/provider`, `/model`, `/set key`, `/reset`, `/config`, `/help`

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the terminal chat
python run.py chat

# 3. Or start the web UI
python run.py web
```

On first run you'll be asked for an API key (e.g. a free key from [OpenRouter](https://openrouter.ai/keys)).

## Commands

| Command | Description |
|---|---|
| `python run.py` | Open chat in VS Code (falls back to terminal) |
| `python run.py chat` | Run the chat in the current terminal |
| `python run.py web` | Start the web server and open the browser |
| `python run.py vscode` | Launch VS Code with the Openlink chat terminal |

## In-chat Commands

| Command | Description |
|---|---|
| `/help` | Show available commands |
| `/providers` | List AI providers |
| `/provider <name>` | Switch provider |
| `/model <name>` | Switch model |
| `/set key <key>` | Save an API key |
| `/set system <prompt>` | Change the system prompt |
| `/set temperature <n>` | Adjust creativity |
| `/reset` | Clear conversation history |
| `/exit` | Quit |

## VS Code Extension

The `vscode-extension/` folder contains a companion extension:

| Shortcut | Action |
|---|---|
| `Ctrl+Alt+O` | Open Openlink chat |
| `Ctrl+Alt+W` | Open the web UI |
| `Ctrl+Alt+Shift+O` | Send current file path to chat |

Install it with:

```bash
code --install-extension vscode-extension/openlink-0.0.2.vsix
```

## Project Structure

```
openlink-ai/
├── run.py                  # CLI entry point (chat / web / vscode)
├── web_server.py           # Local web server for the browser UI
├── openlink_ai/            # Core Python package
│   ├── main.py             # Terminal chat loop & slash commands
│   ├── config.py           # Providers, API keys, settings
│   ├── core/               # AI client, streaming, tools, attachments
│   └── ui/                 # Terminal UI (Rich-based)
├── web/                    # Web chat interface (HTML/JS)
└── vscode-extension/       # VS Code companion extension
```

## Configuration

Settings and API keys are stored in `~/.openlink_ai/config.json` (outside the project folder).

## License

Licensed under the [Apache License 2.0](LICENSE).
