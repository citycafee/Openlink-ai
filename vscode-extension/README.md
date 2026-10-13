# Openlink AI for VS Code

Openlink AI, inside VS Code — like opencode.

## CLI

Running `openlink` from any shell opens VS Code with an `Openlink AI` chat
terminal (the extension starts automatically). Inside a VS Code terminal,
`openlink` starts the chat in that terminal.

## Commands

| Command | Default key | What it does |
| --- | --- | --- |
| Openlink: Open Openlink Chat | `Ctrl+Alt+O` | Opens the Openlink terminal chat (`run.py chat`) in an integrated terminal, reusing an existing one if present. |
| Openlink: Open Openlink Web UI | `Ctrl+Alt+W` | Starts `web_server.py` if it is not already running, waits for port 8377, then opens http://127.0.0.1:8377/ in your browser. Also available as a globe button in the editor title bar. |
| Openlink: Add Filepath to Openlink Chat | `Ctrl+Alt+Shift+O` | Inserts the active file's path into the Openlink chat terminal. |

All commands are available from the Command Palette (`Ctrl+Shift+P`).

## Settings

| Setting | Default | Description |
| --- | --- | --- |
| `openlink.pythonPath` | `python` | Python executable used to launch Openlink. |
| `openlink.projectPath` | *(auto)* | Folder containing `run.py` / `web_server.py`. Auto-detects from the open workspace; falls back to the known install location. |

## Status bar

The `Openlink` item in the status bar shows whether the web server is up. Click it to open the Web UI.

## Install

```
npm run package
code --install-extension openlink-0.0.2.vsix
```

Reload the VS Code window after installing.
