from pathlib import Path

MAX_FILE_CHARS = 200000
MAX_TOTAL_CHARS = 400000

LANG_BY_EXT = {
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".vue": "vue",
    ".svelte": "svelte",
    ".json": "json",
    ".md": "markdown",
    ".py": "python",
    ".rb": "ruby",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".ps1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".sql": "sql",
    ".xml": "xml",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".csv": "csv",
    ".txt": "text",
    ".log": "text",
    ".swift": "swift",
    ".kt": "kotlin",
    ".dart": "dart",
    ".lua": "lua",
    ".r": "r",
    ".pl": "perl",
    ".dockerfile": "dockerfile",
}


def _safe_name(name) -> str:
    text = str(name or "file").replace("\\", "/").split("/")[-1].strip()
    return text[:200] or "file"


def _language(name: str) -> str:
    return LANG_BY_EXT.get(Path(name).suffix.lower(), "")


def format_attachments(message: str, files) -> str:
    if not files:
        return message
    if not isinstance(files, list):
        raise ValueError("files must be a list")

    cleaned = []
    total = 0
    for item in files:
        if not isinstance(item, dict):
            continue
        name = _safe_name(item.get("name"))
        content = item.get("content")
        if not isinstance(content, str) or not content:
            continue
        if "\x00" in content:
            raise ValueError(
                f"'{name}' looks like a binary file. Upload text or code files only."
            )
        if len(content) > MAX_FILE_CHARS:
            raise ValueError(
                f"'{name}' is {len(content)} characters, over the {MAX_FILE_CHARS} "
                "character limit. Split it or send only the relevant part."
            )
        total += len(content)
        if total > MAX_TOTAL_CHARS:
            raise ValueError(
                f"Attached files total over {MAX_TOTAL_CHARS} characters. "
                "Send fewer or smaller files."
            )
        cleaned.append((name, content))

    if not cleaned:
        return message

    parts = [(message or "").strip(), "", "Attached files:"]
    for name, content in cleaned:
        parts.append(f"\nFile: {name}")
        parts.append(f"```{_language(name)}\n{content}\n```")
    return "\n".join(parts).strip()
