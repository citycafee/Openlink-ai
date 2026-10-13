import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW("Openlink AI")
    except Exception:
        pass

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory

from . import __version__
from .config import (
    PROVIDERS,
    load_config,
    set_api_key,
    set_provider,
    update_config,
)
from .core.ai_client import AIClient
from .ui import console as ui


def handle_command(command: str, config: dict, client: AIClient) -> str | None:
    parts = command.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("/exit", "/quit"):
        return "__EXIT__"
    if cmd == "/help":
        ui.show_help()
    elif cmd == "/reset":
        client.reset()
        ui.show_success("Conversation history cleared.")
    elif cmd == "/config":
        ui.show_config(client.config)
    elif cmd == "/providers":
        ui.show_providers(client.config)
    elif cmd == "/models":
        ui.show_models(client.config)
    elif cmd == "/provider":
        config = handle_provider(arg, client)
    elif cmd == "/model" and arg:
        config = update_config(model=arg)
        client.apply_config(config)
        ui.show_success(f"Model set to: {arg}")
    elif cmd == "/set":
        config = handle_set(arg, client)
    else:
        ui.show_error(f"Unknown command: {cmd} (try /help)")
    if config is not None:
        client.apply_config(config)
    return None


def handle_provider(arg: str, client: AIClient) -> dict | None:
    if not arg:
        ui.show_providers(client.config)
        return None
    name = arg.strip().lower()
    if name not in PROVIDERS:
        ui.show_error(f"Unknown provider: {name} (see /providers)")
        return None
    try:
        config = set_provider(name)
    except ValueError as e:
        ui.show_error(str(e))
        return None
    ui.show_success(
        f"Provider: {PROVIDERS[name]['label']} | Model: {config['model']}"
    )
    if not config["api_key"] and not PROVIDERS[name].get("local"):
        ui.show_info(f"Set a key for it: /set key <{name}_api_key>")
    return config


def handle_set(arg: str, client: AIClient) -> dict | None:
    parts = arg.split(maxsplit=1)
    if len(parts) < 2:
        ui.show_error(
            "Usage: /set key <api_key> | /set system <prompt> | /set temperature <n>"
        )
        return None
    key, value = parts
    if key == "key":
        config = set_api_key(value.strip())
        provider = config["provider"]
        ui.show_success(f"API key saved for {PROVIDERS[provider]['label']}.")
        return config
    if key in ("system", "prompt"):
        config = update_config(system_prompt=value)
        client.reset()
        ui.show_success("System prompt updated.")
        return config
    if key == "temperature":
        try:
            config = update_config(temperature=float(value))
            ui.show_success(f"Temperature set to {value}")
            return config
        except ValueError:
            ui.show_error("Temperature must be a number.")
            return None
    ui.show_error(f"Unknown setting: {key}")
    return None


def stream_reply(client: AIClient, user_input: str) -> float:
    from rich.live import Live

    started = time.perf_counter()
    ui.console.print()
    with Live(
        ui.message_block("", ui.PRIMARY), console=ui.console, refresh_per_second=12
    ) as live:
        buffer = ""
        for chunk in client.chat_stream(user_input):
            buffer += chunk
            live.update(ui.message_block(buffer, ui.PRIMARY))
    return time.perf_counter() - started


def run():
    config = load_config()
    provider = PROVIDERS.get(config["provider"], {})

    if not config["api_key"] and not provider.get("local"):
        ui.show_info(f"No API key for {provider.get('label', config['provider'])}.")
        try:
            key = ui.console.input("[bold]Enter your API key[/]: ").strip()
            if key and not key.startswith("/"):
                config = set_api_key(key)
                ui.show_success("API key saved.")
            elif key.startswith("/"):
                ui.show_info("You can set a key later with: /set key <api_key>")
            else:
                ui.show_info("You can set it later with: /set key <api_key>")
        except (KeyboardInterrupt, EOFError):
            pass

    client = AIClient(config)

    try:
        from prompt_toolkit.formatted_text import ANSI

        session = PromptSession(history=InMemoryHistory())
        prompt_text = ANSI(" \x1b[1;38;2;250;178;131m>\x1b[0m ")

        def make_toolbar():
            return ui.toolbar_fragments(client.config.get("model", ""))

        def read_input() -> str:
            ui.show_composer_rule()
            return session.prompt(prompt_text, bottom_toolbar=make_toolbar)
    except Exception:
        session = None

        def read_input() -> str:
            ui.show_composer_rule()
            return input(" \x1b[1;38;2;250;178;131m>\x1b[0m ")

    ui.set_status(f"OpenLink AI {__version__} · /help commands · /exit to quit")
    ui.console.print()

    while True:
        try:
            user_input = read_input().strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            result = handle_command(user_input, config, client)
            if result == "__EXIT__":
                break
            continue

        if not client.configured:
            ui.show_error("Set an API key first: /set key <api_key>")
            continue

        ui.set_status()
        ui.show_user(user_input)
        try:
            elapsed = stream_reply(client, user_input)
            ui.show_meta(client.config.get("model", ""), elapsed)
        except Exception as e:
            ui.show_error(f"AI request failed: {e}")

    ui.show_info("Goodbye!")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
