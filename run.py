"""`openlink` command.

    openlink            run the terminal chat in this terminal (default)
    openlink chat       run the terminal chat in this terminal
    openlink web        start the server and open http://127.0.0.1:8377/ in
                        the browser
    openlink vscode     open Visual Studio Code with an "Openlink AI" chat
                        terminal (VS Code is started when it is not running)
    openlink vscode --no-open  run the terminal chat in this terminal
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8377
URL = f"http://{HOST}:{PORT}/"
TITLE = "Openlink AI"
EXTENSION_ID = "openlink-ai.openlink"
EXTENSION_VERSION = "0.0.2"
EXTENSIONS_DIR = Path.home() / ".vscode" / "extensions"
TRIGGER = (
    Path(
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("APPDATA")
        or str(Path.home())
    )
    / "openlink"
    / "vscode_autostart"
)
VSCODE_STARTUP_WAIT = 60.0
VSCODE_RETRY_WAIT = 30.0
IN_VSCODE_WAIT = 6.0


def port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.4):
            return True
    except OSError:
        return False


def wait_for_server(timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open():
            return True
        time.sleep(0.4)
    return False


def start_server() -> bool:
    """Spawn web_server.py in its own console window titled `TITLE`."""
    if port_open():
        return False
    script = PROJECT / "web_server.py"
    kwargs = {"cwd": str(PROJECT), "env": os.environ.copy()}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "-u", str(script)], **kwargs)
    return True


def run_web(open_browser: bool = True) -> int:
    spawned = start_server()
    if spawned:
        print(f"{TITLE}: starting the server ...")
        if not wait_for_server():
            print(f"{TITLE}: the server did not come up on {URL}")
            return 1
    else:
        print(f"{TITLE}: server already running")

    print(f"{TITLE} chat: {URL}")
    print("Chat terminal: openlink chat")
    if open_browser:
        try:
            webbrowser.open(URL)
        except Exception:
            print(f"Open it manually: {URL}")
    return 0


def run_chat() -> int:
    from openlink_ai.main import run

    run()
    return 0


def in_vscode() -> bool:
    return bool(
        os.environ.get("TERM_PROGRAM", "").lower() == "vscode"
        or os.environ.get("VSCODE_INJECTION")
        or os.environ.get("VSCODE_PID")
        or os.environ.get("VSCODE_LOG_LEVEL")
    )


def find_vscode() -> str | None:
    for name in ("code.cmd", "code.exe", "Code.exe"):
        found = shutil.which(name)
        if not found:
            continue
        if found.lower().endswith(".cmd"):
            exe = Path(found).resolve().parent.parent / "Code.exe"
            if exe.exists():
                return str(exe)
        return found

    bases = [
        os.environ.get("LOCALAPPDATA"),
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ]
    relatives = (
        Path("Programs") / "Microsoft VS Code" / "Code.exe",
        Path("Microsoft VS Code") / "Code.exe",
    )
    for base in filter(None, bases):
        for rel in relatives:
            candidate = Path(base) / rel
            if candidate.exists():
                return str(candidate)
    return None


def find_code_cli() -> str | None:
    """The CLI wrapper (`code.cmd`) - needed for --list/--install-extensions."""
    found = shutil.which("code.cmd")
    if found:
        return found
    if os.name != "nt":
        found = shutil.which("code")
        if found:
            return found
    exe = find_vscode()
    if exe:
        cli = Path(exe).parent / "bin" / "code.cmd"
        if cli.exists():
            return str(cli)
    return None


def write_trigger(folder: str) -> bool:
    data = {"command": "chat", "folder": folder, "ts": int(time.time())}
    try:
        TRIGGER.parent.mkdir(parents=True, exist_ok=True)
        TRIGGER.write_text(json.dumps(data), encoding="utf-8")
        return True
    except OSError:
        return False


def clear_trigger() -> None:
    try:
        TRIGGER.unlink()
    except OSError:
        pass


def wait_trigger(timeout: float) -> bool:
    """Wait until the VS Code extension consumes the trigger file."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not TRIGGER.exists():
            return True
        time.sleep(0.4)
    return False


def spawn_vscode(code: str, folder: str) -> bool:
    argv = [code, folder]
    kwargs: dict = {"cwd": folder}
    if sys.platform == "win32" and not argv[0].lower().endswith(".exe"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        subprocess.Popen(argv, **kwargs)
        return True
    except OSError:
        return False


def version_tuple(text: str) -> tuple[int, ...]:
    parts = []
    for piece in text.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def extension_needs_update() -> bool:
    """True when no installed copy of the extension is the required version."""
    best: tuple[int, ...] | None = None
    try:
        entries = list(EXTENSIONS_DIR.glob(f"{EXTENSION_ID}-*"))
    except OSError:
        entries = []
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            data = json.loads((entry / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        ver = version_tuple(str(data.get("version", "0")))
        if best is None or ver > best:
            best = ver
    return (best or (0,)) < version_tuple(EXTENSION_VERSION)


def install_extension() -> bool:
    cli = find_code_cli()
    vsix = PROJECT / "vscode-extension" / f"openlink-{EXTENSION_VERSION}.vsix"
    if not cli or not vsix.exists():
        return False
    print(f"{TITLE}: installing the VS Code extension ...")
    try:
        result = subprocess.run(
            [cli, "--install-extension", str(vsix)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        print(
            f"{TITLE}: the extension could not be installed"
            + (f": {detail[0]}" if detail else ".")
        )
        return False
    return not extension_needs_update()


def update_extension_if_needed() -> None:
    if extension_needs_update():
        install_extension()


def chat_here(reason: str | None = None) -> int:
    clear_trigger()
    if reason:
        print(reason)
    print(f"{TITLE}: running the chat in this terminal.")
    return run_chat()


def open_in_vscode() -> int:
    folder = os.getcwd()
    update_extension_if_needed()
    print(f"{TITLE}: opening Visual Studio Code ...")

    if not write_trigger(folder):
        return chat_here(f"{TITLE}: cannot write {TRIGGER}.")

    code = find_vscode()
    if not code or not spawn_vscode(code, folder):
        return chat_here(f"{TITLE}: Visual Studio Code was not found.")

    if wait_trigger(VSCODE_STARTUP_WAIT):
        print(f'{TITLE}: VS Code opened with the "{TITLE}" chat terminal.')
        return 0

    # VS Code can be slow or drop the first request - send it again.
    spawn_vscode(code, folder)
    if wait_trigger(VSCODE_RETRY_WAIT):
        print(f'{TITLE}: VS Code opened with the "{TITLE}" chat terminal.')
        return 0

    return chat_here(
        f'{TITLE}: VS Code did not open the chat terminal. Restart VS Code once '
        f'(or run "Developer: Reload Window") and retry.'
    )


def openlink(open_vscode: bool = True) -> int:
    if not open_vscode:
        return run_chat()

    if in_vscode():
        update_extension_if_needed()
        if write_trigger(os.getcwd()) and wait_trigger(IN_VSCODE_WAIT):
            print(f'{TITLE}: chat terminal opened in VS Code.')
            return 0
        return chat_here(
            f"{TITLE}: the Openlink VS Code extension did not respond "
            '(run "Developer: Reload Window" in VS Code to fix it).'
        )

    return open_in_vscode()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    open_vscode = True
    open_browser = True
    command = ""

    for a in args:
        if a in ("--no-open", "--no-browser", "--no-open-browser"):
            open_vscode = False
            open_browser = False
        elif a in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        elif not a.startswith("-") and not command:
            command = a.lower()

    if command in ("", "chat", "cli", "tui", "term", "terminal"):
        if not command:
            clear_trigger()
            print(
                f"{TITLE}: running the chat in this terminal "
                "(web UI: openlink web - VS Code: openlink vscode)"
            )
        return run_chat()
    if command in ("vscode", "vs", "code", "studio"):
        return openlink(open_vscode)
    if command in ("web", "start", "ui", "browser"):
        return run_web(open_browser)

    print(f"openlink: unknown command '{command}' (try: chat, web, vscode)")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
