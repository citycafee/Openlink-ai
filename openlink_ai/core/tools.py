import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .completion import _open_stream

CMD_TIMEOUT = 60
MAX_TOOL_ROUNDS = 8
MODEL_OUTPUT_LIMIT = 8000
UI_OUTPUT_LIMIT = 12000
MAX_COMMAND_CHARS = 4000

SHELL_TOOL = {
    "type": "function",
    "function": {
        "name": "run_shell",
        "description": (
            "Run a shell command on the user's computer (PowerShell on Windows) "
            "inside their trusted workspace folder and return stdout, stderr and "
            "the exit code. Use it to inspect files, build, test, install "
            "packages, run git, generate scaffolding, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command line to execute.",
                },
                "cwd": {
                    "type": "string",
                    "description": (
                        "Optional working directory, relative to the workspace "
                        "root. Defaults to the workspace root."
                    ),
                },
            },
            "required": ["command"],
        },
    },
}

LIST_TOOL = {
    "type": "function",
    "function": {
        "name": "list_dir",
        "description": (
            "List what is inside a folder of the workspace: every entry with its "
            "name, its size and whether it is a folder. Use it to explore the "
            "project before reading or writing files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Folder path relative to the workspace root. Use an "
                        "empty string for the root itself."
                    ),
                },
            },
            "required": [],
        },
    },
}

READ_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "Read a text file from the workspace and return its full content. "
            "Always read a file before changing it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the workspace root.",
                },
            },
            "required": ["path"],
        },
    },
}

WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": (
            "Create or overwrite a text file in the workspace with the given "
            "content. Missing folders are created automatically. Send the whole "
            "file content, never a fragment."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the workspace root.",
                },
                "content": {
                    "type": "string",
                    "description": "The complete new content of the file.",
                },
            },
            "required": ["path", "content"],
        },
    },
}

READ_TOOLS = [LIST_TOOL, READ_TOOL]
WRITE_TOOLS = READ_TOOLS + [WRITE_TOOL]
ALL_FILE_TOOLS = WRITE_TOOLS


def clip(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return (
        text[:head]
        + f"\n... [{len(text) - limit} characters trimmed] ...\n"
        + text[-tail:]
    )


def shell_argv(exe: str, command: str) -> list[str]:
    low = exe.lower()
    if "powershell" in low or "pwsh" in low:
        return [
            exe,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command,
        ]
    return [exe, "-c", command]


def shell_exe() -> str:
    if sys.platform == "win32":
        for name in ("pwsh.exe", "powershell.exe"):
            found = shutil.which(name)
            if found:
                return found
        root = os.environ.get("SystemRoot") or r"C:\Windows"
        default = (
            Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        if default.exists():
            return str(default)
    return shutil.which("pwsh") or shutil.which("sh") or "sh"


def run_shell(command: str, cwd: str | None = None, timeout: int = CMD_TIMEOUT) -> dict:
    command = (command or "").strip()
    if not command:
        return {"ok": False, "command": "", "error": "Empty command."}
    if len(command) > MAX_COMMAND_CHARS:
        return {
            "ok": False,
            "command": command[:200],
            "error": f"Command is too long ({MAX_COMMAND_CHARS} characters max).",
        }
    if cwd and not Path(cwd).is_dir():
        return {
            "ok": False,
            "command": command,
            "error": f"Working folder not found: {cwd}",
        }

    exe = shell_exe()
    started = time.time()
    try:
        proc = subprocess.run(
            shell_argv(exe, command),
            cwd=cwd or None,
            capture_output=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "command": command,
            "cwd": cwd or "",
            "error": f"Timed out after {timeout}s and was stopped.",
            "duration_ms": int((time.time() - started) * 1000),
        }
    except OSError as e:
        return {"ok": False, "command": command, "error": f"Could not start the shell: {e}"}

    return {
        "ok": proc.returncode == 0,
        "command": command,
        "cwd": cwd or "",
        "stdout": clip(proc.stdout or "", UI_OUTPUT_LIMIT),
        "stderr": clip(proc.stderr or "", UI_OUTPUT_LIMIT),
        "code": proc.returncode,
        "duration_ms": int((time.time() - started) * 1000),
    }


def code_cli() -> list[str] | None:
    for name in ("code", "code.cmd", "code.cmd.exe"):
        found = shutil.which(name)
        if found:
            return [found]
    if sys.platform == "win32":
        bases = [
            os.environ.get("LOCALAPPDATA"),
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
        ]
        for base in bases:
            if not base:
                continue
            for rel in (
                Path("Programs") / "Microsoft VS Code" / "bin" / "code.cmd",
                Path("Microsoft VS Code") / "bin" / "code.cmd",
            ):
                candidate = Path(base) / rel
                if candidate.exists():
                    return [str(candidate)]
    return None


def open_in_vscode(target: str) -> dict:
    path = Path(target)
    if not path.exists():
        return {"ok": False, "error": f"Not found: {target}"}
    cli = code_cli()
    if not cli:
        return {
            "ok": False,
            "error": (
                "The VS Code command line tool was not found. Open VS Code and "
                "run 'Shell Command: Install code command in PATH'."
            ),
        }
    args = cli + [str(path)]
    exe = cli[0].lower()
    if exe.endswith(".cmd") or exe.endswith(".bat"):
        args = [os.environ.get("ComSpec") or "cmd.exe", "/c"] + args
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
        )
    try:
        subprocess.Popen(
            args,
            cwd=str(path) if path.is_dir() else str(path.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except OSError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "target": str(path)}


def _tool_request(config: dict, messages: list, tools: list) -> dict:
    kwargs = {
        "model": config["model"],
        "messages": messages,
        "temperature": config.get("temperature", 0.7),
        "stream": True,
        "tools": tools,
        "tool_choice": "auto",
    }
    if config.get("max_tokens"):
        kwargs["max_tokens"] = config["max_tokens"]
    return kwargs


def stream_agent(client, config: dict, messages: list, run_tool, tools=None):
    """Yield ('text', str) while the model answers, or ('tool', result_dict)
    when it asked to use a tool. Stops when a round has no tool calls.

    `run_tool(name, args)` executes one call and returns a result dict.
    `tools` is the list of schemas handed to the model (defaults to shell only).
    """
    tools = list(tools) if tools else [SHELL_TOOL]
    allowed = {t["function"]["name"] for t in tools}
    rounds = 0
    while True:
        rounds += 1
        if rounds > MAX_TOOL_ROUNDS:
            raise RuntimeError("Agent stopped after too many tool rounds.")
        stream = _open_stream(client, _tool_request(config, messages, tools), messages)
        parts = []
        calls = {}
        finish = None
        for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            choice = chunk.choices[0]
            if getattr(choice, "finish_reason", None):
                finish = choice.finish_reason
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            text = getattr(delta, "content", None)
            if text:
                parts.append(text)
                yield ("text", text)
            for tc in getattr(delta, "tool_calls", None) or []:
                index = getattr(tc, "index", 0) or 0
                slot = calls.setdefault(index, {"id": "", "name": "", "args": ""})
                if getattr(tc, "id", None):
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["args"] += fn.arguments

        content = "".join(parts)
        ordered = [calls[i] for i in sorted(calls)]

        if ordered:
            ids = []
            for n, slot in enumerate(ordered):
                ids.append(slot["id"] or f"call_{n}")
            messages.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": [
                        {
                            "id": ids[n],
                            "type": "function",
                            "function": {
                                "name": ordered[n]["name"],
                                "arguments": ordered[n]["args"] or "{}",
                            },
                        }
                        for n in range(len(ordered))
                    ],
                }
            )
            for n, slot in enumerate(ordered):
                try:
                    args = json.loads(slot["args"] or "{}")
                    if not isinstance(args, dict):
                        args = {}
                except json.JSONDecodeError:
                    args = {}
                if slot["name"] not in allowed:
                    result = {
                        "ok": False,
                        "tool": slot["name"],
                        "error": f"Unknown tool: {slot['name']}",
                    }
                else:
                    try:
                        result = run_tool(slot["name"], args)
                    except Exception as e:
                        result = {
                            "ok": False,
                            "tool": slot["name"],
                            "command": str(args.get("command", "")),
                            "error": str(e),
                        }
                    if not isinstance(result, dict):
                        result = {"ok": False, "tool": slot["name"], "error": "Tool failed."}
                    result.setdefault("tool", slot["name"])
                yield ("tool", result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": ids[n],
                        "content": clip(
                            json.dumps(result, ensure_ascii=False),
                            MODEL_OUTPUT_LIMIT,
                        ),
                    }
                )
            continue

        if finish == "length" and content:
            messages.append({"role": "assistant", "content": content})
            continue
        if finish in ("content_filter", "safety"):
            raise RuntimeError("The provider stopped the response (content filter).")
        return
