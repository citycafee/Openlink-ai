import io

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.table import Table
from rich.text import Text

console = Console()

# OpenCode "opencode" theme (dark) palette
PRIMARY = "#fab283"
SECONDARY = "#5c9cf5"
ACCENT = "#9d7cd8"
TEXT = "#e0e0e0"
MUTED = "#6a6a6a"
BG = "#212121"
BG_SECONDARY = "#252525"
BG_DARKER = "#121212"
BORDER = "#4b4c5c"
ERROR = "#e06c75"
SUCCESS = "#7fd88f"
INFO = "#56b6c2"
WARNING = "#f5a742"

_status: dict = {"text": "", "kind": ""}


def set_status(message: str = "", kind: str = "info"):
    _status["text"] = message
    _status["kind"] = kind


def _markdown_lines(text: str, width: int) -> list[Text]:
    buf = io.StringIO()
    inner = Console(
        file=buf,
        width=max(24, width),
        force_terminal=True,
        record=True,
        legacy_windows=False,
        color_system="truecolor",
    )
    inner.print(Markdown(text))
    return Text.from_ansi(inner.export_text(styles=True)).split("\n")


def message_block(text: str, bar_color: str = PRIMARY) -> Text:
    """Markdown message behind a thick left bar, like opencode's chat."""
    width = console.width
    inner_width = max(24, width - 4)
    body = _markdown_lines(text, inner_width) if text else [Text("")]
    out = Text()
    for i, line in enumerate(body):
        if i:
            out.append("\n")
        out.append(" ┃ ", style=f"bold {bar_color}")
        out.append_text(line)
    return out


def show_info(message: str):
    set_status(message, "info")
    console.print(f"[dim]·[/] [dim]{escape(message)}[/]")


def show_success(message: str):
    set_status(message, "info")
    console.print(f"[green]✓[/] {escape(message)}")


def show_error(message: str):
    set_status(message, "error")
    console.print(f"[red]✗[/] [red]{escape(message)}[/]")


def show_user(text: str):
    console.print()
    console.print(message_block(text, SECONDARY))


def show_assistant(text: str):
    console.print(message_block(text, PRIMARY))


def _elapsed(seconds: float) -> str:
    if seconds < 1:
        return f"{int(seconds * 1000)}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{seconds / 60:.1f}m"


def show_meta(label: str, seconds: float):
    if not label:
        return
    console.print(Text(f" {label} ({_elapsed(seconds)})", style=MUTED))


def show_composer_rule():
    console.print(Text("─" * console.width, style=BORDER))


def toolbar_fragments(model: str = "") -> list[tuple[str, str]]:
    """Bottom status bar: help chip · status segment · model chip."""
    width = console.width
    help_text = " /help commands "
    model_text = f" {model} " if model else ""

    kind = _status["kind"]
    msg = _status["text"]
    if kind == "error":
        fill_style = f"bg:{ERROR} {BG}"
    elif kind == "warn":
        fill_style = f"bg:{WARNING} {BG}"
    elif msg:
        fill_style = f"bg:{INFO} {BG}"
    else:
        fill_style = f"bg:{BG_SECONDARY} {TEXT}"

    fill_width = width - len(help_text) - len(model_text)
    if fill_width <= 0:
        fragments = [(f"bg:{MUTED} {BG_DARKER} bold", help_text)]
        if model_text:
            fragments.append((f"bg:{SECONDARY} {BG}", model_text))
        return fragments

    if msg:
        room = max(1, fill_width - 2)
        shown = msg if len(msg) <= room else msg[: max(1, room - 3)] + "..."
        pad = max(0, fill_width - len(shown) - 2)
        fill_text = f" {shown}{' ' * pad} "
    else:
        fill_text = " " * fill_width

    fragments = [
        (f"bg:{MUTED} {BG_DARKER} bold", help_text),
        (fill_style, fill_text),
    ]
    if model_text:
        fragments.append((f"bg:{SECONDARY} {BG}", model_text))
    return fragments


def _styled_dialog(title: str, table: Table):
    table.box = box.ROUNDED
    table.border_style = "dim"
    table.title = f"[bold cyan]{title}[/]"
    table.title_style = "bold cyan"
    console.print(table)


def show_help():
    table = Table(show_header=True, header_style="dim", box=box.SIMPLE)
    table.add_column("Command", style="cyan")
    table.add_column("Description", style="dim")
    table.add_row("/help", "Show this help message")
    table.add_row("/reset", "Clear conversation history")
    table.add_row("/providers", "List available AI providers")
    table.add_row("/provider <name>", "Switch AI provider (e.g. nararouter, groq)")
    table.add_row("/models", "List models for current provider")
    table.add_row("/model <name>", "Change AI model")
    table.add_row("/config", "Show current configuration")
    table.add_row("/set key <api_key>", "Set API key for current provider")
    table.add_row("/set system <prompt>", "Set system prompt")
    table.add_row("/set temperature <n>", "Set response temperature (0-2)")
    table.add_row("/exit, /quit", "Exit the application")
    _styled_dialog("Commands", table)


def show_providers(config: dict):
    from ..config import PROVIDERS

    table = Table(show_header=True, header_style="dim", box=box.SIMPLE)
    table.add_column("Name", style="cyan")
    table.add_column("Provider")
    table.add_column("Model")
    table.add_column("Key")
    table.add_column("Active", justify="center")
    for name, preset in PROVIDERS.items():
        has_key = bool(config.get("api_keys", {}).get(name)) or (
            name == config.get("provider") and bool(config.get("api_key"))
        )
        if preset.get("local"):
            key_status = "[green]local[/]"
        else:
            key_status = "[green]set[/]" if has_key else "[red]missing[/]"
        active = "[bold green]·[/]" if name == config.get("provider") else ""
        table.add_row(name, preset["label"], preset["model"], key_status, active)
    _styled_dialog("Providers", table)
    console.print(
        "[dim]switch: [/]/provider <name>[/]   [dim]key: [/]/set key <api_key>"
    )


def show_models(config: dict):
    from ..config import PROVIDERS

    provider = PROVIDERS.get(config.get("provider", ""), {})
    models = provider.get("models", [])
    if not models:
        show_info("No preset models for this provider. Use /model <name>.")
        return
    table = Table(show_header=True, header_style="dim", box=box.SIMPLE)
    table.add_column("Model ID", style="cyan")
    table.add_column("Active", justify="center")
    for m in models:
        active = "[bold green]·[/]" if m == config.get("model") else ""
        table.add_row(m, active)
    _styled_dialog(f"Models — {provider.get('label', config.get('provider'))}", table)
    console.print("[dim]switch: [/]/model <name>")


def show_config(config: dict):
    from ..config import PROVIDERS

    provider = config.get("provider", "?")
    provider_label = PROVIDERS.get(provider, {}).get("label", provider)
    api_keys = config.get("api_keys", {})
    key = api_keys.get(provider, "")
    masked_key = key[:8] + "..." if len(key) > 8 else ("set" if key else "not set")

    table = Table(show_header=False, box=box.SIMPLE, border_style="dim")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    table.add_row("Provider", provider_label)
    table.add_row("API Key", masked_key)
    table.add_row("Base URL", config["base_url"])
    table.add_row("Model", config["model"])
    table.add_row("Temperature", str(config["temperature"]))
    table.add_row("Max Tokens", str(config["max_tokens"]))
    table.add_row(
        "System Prompt",
        config["system_prompt"][:60]
        + ("..." if len(config["system_prompt"]) > 60 else ""),
    )
    _styled_dialog("Config", table)
