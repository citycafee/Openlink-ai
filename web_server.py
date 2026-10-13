import json
import os
import re
import socket
import string
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW("Openlink AI")
    except Exception:
        pass

from openlink_ai.config import PROVIDERS, load_config, provider_preset, update_config

WEB_DIR = Path(__file__).parent / "web"
HOST = os.environ.get("OPENLINK_HOST", "0.0.0.0")
PORT = 8377
MAX_READ_BYTES = 1_000_000
MAX_WRITE_BYTES = 2_000_000


def resolve_path(path: str) -> Path | None:
    try:
        p = Path(os.path.expandvars(os.path.expanduser(str(path).strip())))
        return p.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def inside(root: Path, target: Path) -> bool:
    r = os.path.normcase(str(root)).rstrip("\\/")
    t = os.path.normcase(str(target))
    return t == r or t.startswith(r + os.sep)


def drive_list() -> list[str]:
    if sys.platform != "win32":
        return []
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]


def list_dir(path: Path, dirs_only: bool = False) -> list[dict]:
    try:
        children = list(path.iterdir())
    except OSError as e:
        raise ValueError(str(e) or "Cannot read this folder.")
    entries = []
    for child in children:
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        if dirs_only and not is_dir:
            continue
        size, mtime = 0, 0
        if not is_dir:
            try:
                st = child.stat()
                size, mtime = st.st_size, int(st.st_mtime)
            except OSError:
                pass
        entries.append(
            {"name": child.name, "dir": is_dir, "size": size, "mtime": mtime}
        )
    entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
    return entries


def is_absolute(raw: str) -> bool:
    s = str(raw or "")
    return bool(re.match(r"^[A-Za-z]:[\\/]", s)) or s.startswith(("/", "\\\\"))


def read_text_file(target: Path) -> dict:
    """Read an editable text file. Returns {ok, text, size} or {ok, error, status}."""
    if not target.is_file():
        return {"ok": False, "error": "File not found.", "status": 404}
    try:
        data = target.read_bytes()
    except OSError as e:
        return {"ok": False, "error": str(e), "status": 500}
    if len(data) > MAX_READ_BYTES:
        return {
            "ok": False,
            "error": f"File is {len(data)} bytes — the editor limit is {MAX_READ_BYTES}.",
            "status": 413,
        }
    if b"\x00" in data:
        return {"ok": False, "error": "Binary files cannot be edited.", "status": 415}
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
    return {"ok": True, "text": text, "size": len(data)}


def write_text_file(target: Path, content: str) -> dict:
    """Write an editable text file. Returns {ok, size} or {ok, error, status}."""
    data = content.encode("utf-8")
    if len(data) > MAX_WRITE_BYTES:
        return {
            "ok": False,
            "error": "File is too large to save (2 MB limit).",
            "status": 413,
        }
    if target == target.parent:
        return {"ok": False, "error": "Invalid file path.", "status": 400}
    if target.is_dir():
        return {
            "ok": False,
            "error": "That path is a folder, not a file.",
            "status": 400,
        }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as e:
        return {"ok": False, "error": str(e), "status": 500}
    return {"ok": True, "size": len(data)}


MODE_GUIDANCE = {
    "build": (
        "Mode: BUILD. Work like an agent: use the tools you are given to make the "
        "changes for real — list the folder, read the files, then write the fixed "
        "or new files back — and run commands when the shell tool is available. "
        "Finish the whole task instead of only describing it. Only print a full "
        "file in the chat when the user asks to see it."
    ),
    "plan": (
        "Mode: PLAN. Read-only: you may list and read files to understand the "
        "project, but never write, create, delete or run anything. Propose a short "
        "numbered step-by-step plan and ask for approval before changing anything."
    ),
    "ask": (
        "Mode: ASK. Answer the question directly and concisely. Do not create or "
        "edit files and do not output whole files unless they are required to "
        "explain the answer."
    ),
}

MODE_LABEL = {"build": "Build", "plan": "Plan", "ask": "Ask"}


def is_private_ip(host: str) -> bool:
    parts = host.split(".")
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return False
    a, b = int(parts[0]), int(parts[1])
    return a == 10 or (a == 192 and b == 168) or (a == 172 and 16 <= b <= 31)


def estimate_tokens(text) -> int:
    """Rough token count (~4 characters per token)."""
    return (len(str(text)) + 3) // 4


def looks_too_large(err: str) -> bool:
    low = str(err).lower()
    return any(
        s in low
        for s in (
            "413",
            "rate_limit",
            "rate limit",
            "request too large",
            "tokens per minute",
            "tpm",
            "reduce your message size",
        )
    )


def too_large_message(model: str, tokens: int, budget: int, detail: str = "") -> str:
    msg = (
        f"This request is too large for {model} (~{tokens} tokens, this "
        f"provider allows about {budget} per request). Attach smaller files, "
        "clear this chat (New chat), or switch to another provider in Settings."
    )
    detail = " ".join(str(detail or "").split())
    if detail:
        if len(detail) > 300:
            detail = detail[:297] + "..."
        msg += f" — Provider reply: {detail}"
    return msg


def lan_urls() -> list[str]:
    urls = set()
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        for info in infos:
            urls.add(info[4][0])
    except OSError:
        pass
    return sorted(urls)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _local_origin(self) -> bool:
        origin = self.headers.get("Origin") or ""
        if not origin:
            return True
        try:
            parsed = urlparse(origin)
            port = parsed.port
        except ValueError:
            return False
        if port != PORT:
            return False
        host = (parsed.hostname or "").lower()
        if host in ("127.0.0.1", "localhost", "::1"):
            return True
        return is_private_ip(host)

    def _body(self) -> dict | None:
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def config_folders(config: dict) -> list[str]:
        folders = [str(f).strip() for f in (config.get("workspace_folders") or [])]
        folders = [f for f in folders if f]
        if not folders:
            root = str(config.get("workspace_root") or "").strip()
            if root:
                folders = [root]
        return folders

    def workspace_state(self) -> dict:
        config = load_config()
        trusted = []
        for t in config.get("trusted_paths") or []:
            resolved = resolve_path(str(t))
            if resolved is not None:
                trusted.append(resolved)
        folders = []
        seen: list[Path] = []
        for raw in self.config_folders(config):
            p = resolve_path(raw)
            if p is None or any(same_path(p, s) for s in seen):
                continue
            seen.append(p)
            folders.append(
                {
                    "path": str(p),
                    "exists": p.is_dir(),
                    "trusted": any(same_path(p, t) for t in trusted),
                }
            )
        first = folders[0] if folders else None
        return {
            "path": first["path"] if first else "",
            "configured": bool(folders),
            "exists": bool(first and first["exists"]),
            "trusted": bool(folders)
            and all(f["exists"] and f["trusted"] for f in folders),
            "folders": folders,
        }

    def trusted_roots(self, state: dict | None = None) -> list[Path]:
        state = state or self.workspace_state()
        return [
            Path(f["path"]) for f in state["folders"] if f["trusted"] and f["exists"]
        ]

    def pick_root(self, want=""):
        """Resolve the workspace folder to operate on.

        `want` is an optional absolute folder path; it must be one of the
        trusted workspace folders. With no `want`, the first folder is used.
        """
        state = self.workspace_state()
        roots = self.trusted_roots(state)
        if not roots:
            return None, state
        want = str(want or "").strip()
        if not want:
            return roots[0], state
        target = resolve_path(want)
        if target is None:
            raise ValueError("Invalid folder path.")
        for root in roots:
            if same_path(root, target):
                return root, state
        raise ValueError("That folder is not in your workspace.")

    def safe_target(self, root: Path, rel: str):
        rel = str(rel or "").replace("\\", "/").strip().lstrip("/")
        try:
            target = (root / rel).resolve()
        except (OSError, RuntimeError, ValueError) as e:
            raise ValueError(str(e) or "Invalid path.")
        if not inside(root, target):
            raise ValueError("Path is outside the trusted folder.")
        return target, rel

    def handle_workspace(self, payload: dict):
        route = self.path
        try:
            if route == "/api/workspace/select":
                raw = str(payload.get("path") or "").strip()
                if not raw:
                    self._send_json({"error": "Folder path is required."}, 400)
                    return
                target = resolve_path(raw)
                if target is None:
                    self._send_json({"error": "Invalid folder path."}, 400)
                    return
                if not target.is_dir():
                    self._send_json(
                        {"error": f"Folder not found: {target}"}, 404
                    )
                    return
                config = load_config()
                trusted = [
                    resolve_path(str(t))
                    for t in config.get("trusted_paths") or []
                ]
                already = any(
                    t is not None and same_path(target, t) for t in trusted
                )
                if not payload.get("trust") and not already:
                    self._send_json({"needs_trust": True, "path": str(target)})
                    return
                kept = [t for t in trusted if t is not None]
                if not any(same_path(target, t) for t in kept):
                    kept.append(target)
                unique, seen = [], []
                for t in kept:
                    if not any(same_path(t, s) for s in seen):
                        seen.append(t)
                        unique.append(str(t))
                update_config(
                    workspace_root=str(target),
                    workspace_folders=[str(target)],
                    trusted_paths=unique,
                )
                self._send_json(self.workspace_state())
                return

            if route == "/api/workspace/add":
                raw = str(payload.get("path") or "").strip()
                if not raw:
                    self._send_json({"error": "Folder path is required."}, 400)
                    return
                target = resolve_path(raw)
                if target is None:
                    self._send_json({"error": "Invalid folder path."}, 400)
                    return
                if not target.is_dir():
                    self._send_json({"error": f"Folder not found: {target}"}, 404)
                    return
                config = load_config()
                trusted = [
                    resolve_path(str(t))
                    for t in config.get("trusted_paths") or []
                ]
                folders = [
                    resolve_path(f) for f in self.config_folders(config)
                ]
                folders = [f for f in folders if f is not None]
                if any(same_path(target, f) for f in folders):
                    self._send_json({"already": True, **self.workspace_state()})
                    return
                already = any(
                    t is not None and same_path(target, t) for t in trusted
                )
                if not payload.get("trust") and not already:
                    self._send_json({"needs_trust": True, "path": str(target)})
                    return
                if len(folders) >= 10:
                    self._send_json(
                        {"error": "A workspace can hold up to 10 folders."}, 409
                    )
                    return
                folders.append(target)
                kept = [t for t in trusted if t is not None]
                if not any(same_path(target, t) for t in kept):
                    kept.append(target)
                unique, seen = [], []
                for t in kept:
                    if not any(same_path(t, s) for s in seen):
                        seen.append(t)
                        unique.append(str(t))
                update_config(
                    workspace_root=str(folders[0]),
                    workspace_folders=[str(f) for f in folders],
                    trusted_paths=unique,
                )
                self._send_json(self.workspace_state())
                return

            if route == "/api/workspace/clear":
                config = load_config()
                untrust = payload.get("untrust", True)
                folders = [
                    f
                    for f in (
                        resolve_path(f) for f in self.config_folders(config)
                    )
                    if f is not None
                ]
                raw = str(payload.get("path") or "").strip()
                clear_all = not raw
                if raw:
                    target = resolve_path(raw)
                    if target is None:
                        self._send_json({"error": "Invalid folder path."}, 400)
                        return
                    drop = [f for f in folders if same_path(f, target)]
                    folders = [f for f in folders if not same_path(f, target)]
                else:
                    drop = list(folders)
                    folders = []
                kept = []
                for t in config.get("trusted_paths") or []:
                    rp = resolve_path(str(t))
                    if rp is None:
                        continue
                    if untrust and (
                        clear_all or any(same_path(rp, d) for d in drop)
                    ):
                        continue
                    kept.append(str(rp))
                update_config(
                    workspace_root=str(folders[0]) if folders else "",
                    workspace_folders=[str(f) for f in folders],
                    trusted_paths=kept,
                )
                self._send_json(self.workspace_state())
                return

            if route == "/api/workspace/browse":
                raw = str(payload.get("path") or "").strip()
                target = None
                entries = []
                parent = ""
                if raw:
                    target = resolve_path(raw)
                    if target is None or not target.is_dir():
                        self._send_json(
                            {"error": f"Folder not found: {raw}"}, 404
                        )
                        return
                    entries = list_dir(target, dirs_only=True)
                    if target.parent != target:
                        parent = str(target.parent)
                elif sys.platform != "win32":
                    target = Path("/")
                    entries = list_dir(target, dirs_only=True)
                self._send_json(
                    {
                        "path": str(target) if target else "",
                        "parent": parent,
                        "drives": drive_list(),
                        "entries": entries,
                    }
                )
                return

            if route == "/api/workspace/mkdir":
                raw = str(payload.get("path") or "").strip()
                if not raw:
                    self._send_json({"error": "Folder name is required."}, 400)
                    return
                if is_absolute(raw):
                    target = resolve_path(raw)
                    if target is None:
                        self._send_json({"error": "Invalid folder path."}, 400)
                        return
                else:
                    root, _state = self.pick_root(payload.get("root"))
                    if root is None:
                        self._send_json(
                            {"error": "Open and trust a folder first."}, 403
                        )
                        return
                    target, _rel = self.safe_target(root, raw)
                if target.exists():
                    if target.is_dir():
                        self._send_json(
                            {"ok": True, "created": False, "path": str(target)}
                        )
                        return
                    self._send_json(
                        {"error": f"A file with that name already exists: {target}"},
                        409,
                    )
                    return
                if not target.parent.is_dir():
                    self._send_json(
                        {
                            "error": (
                                f"Parent folder not found: {target.parent}. "
                                "Create or choose the parent folder first."
                            )
                        },
                        404,
                    )
                    return
                try:
                    target.mkdir()
                except OSError as e:
                    self._send_json({"error": str(e)}, 500)
                    return
                self._send_json({"ok": True, "created": True, "path": str(target)})
                return

            root, _state = self.pick_root(payload.get("root"))
            if root is None:
                self._send_json(
                    {
                        "error": (
                            "This folder is not trusted. Open the folder and "
                            "trust it first."
                        )
                    },
                    403,
                )
                return

            if route == "/api/workspace/list":
                target, rel = self.safe_target(root, payload.get("path", ""))
                if not target.is_dir():
                    self._send_json({"error": "Folder not found."}, 404)
                    return
                self._send_json(
                    {
                        "path": rel.strip("/"),
                        "root": str(root),
                        "entries": list_dir(target),
                    }
                )
                return

            if route == "/api/workspace/read":
                target, rel = self.safe_target(root, payload.get("path", ""))
                done = read_text_file(target)
                if not done["ok"]:
                    self._send_json({"error": done["error"]}, done["status"])
                    return
                self._send_json(
                    {
                        "path": rel,
                        "name": target.name,
                        "content": done["text"],
                        "size": done["size"],
                    }
                )
                return

            if route == "/api/workspace/write":
                content = payload.get("content")
                if not isinstance(content, str):
                    self._send_json({"error": "content is required."}, 400)
                    return
                target, rel = self.safe_target(root, payload.get("path", ""))
                if target == root or not rel:
                    self._send_json({"error": "Invalid file path."}, 400)
                    return
                done = write_text_file(target, content)
                if not done["ok"]:
                    self._send_json({"error": done["error"]}, done["status"])
                    return
                self._send_json(
                    {"ok": True, "path": rel, "name": target.name,
                     "size": done["size"]}
                )
                return

            self._send_json({"error": "not found"}, 404)
        except ValueError as e:
            self._send_json({"error": str(e)}, 403)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            file = WEB_DIR / "index.html"
            if not file.exists():
                self._send_json({"error": "index.html not found"}, 404)
                return
            body = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/config":
            config = load_config()
            preset = provider_preset(config["provider"]) or {}
            api_keys = config.get("api_keys", {})
            providers = []
            for pid, p in list(PROVIDERS.items()) + list(
                config.get("custom_providers", {}).items()
            ):
                has_key = bool(api_keys.get(pid)) or (
                    pid == config["provider"] and bool(config["api_key"])
                )
                providers.append(
                    {
                        "id": pid,
                        "label": p["label"],
                        "models": p.get("models", []),
                        "has_key": has_key or p.get("local", False),
                        "active": pid == config["provider"],
                        "custom": bool(p.get("custom")),
                        "key_url": p.get("key_url", ""),
                    }
                )
            self._send_json(
                {
                    "provider": preset.get("label", config["provider"]),
                    "provider_id": config["provider"],
                    "model": config["model"],
                    "ready": bool(config["api_key"]) or preset.get("local", False),
                    "providers": providers,
                    "workspace": self.workspace_state(),
                    "allow_exec": bool(config.get("allow_exec")),
                }
            )
        elif self.path == "/api/workspace":
            if not self._local_origin():
                self._send_json({"error": "forbidden origin"}, 403)
                return
            self._send_json(self.workspace_state())
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._local_origin():
            self._send_json({"error": "forbidden origin"}, 403)
            return
        if self.path.startswith("/api/workspace"):
            payload = self._body()
            if payload is None:
                self._send_json({"error": "invalid JSON"}, 400)
                return
            self.handle_workspace(payload)
            return

        if self.path == "/api/keys":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send_json({"error": "invalid JSON"}, 400)
                return
            from openlink_ai.config import set_api_key

            provider = str(payload.get("provider", "")).strip()
            key = str(payload.get("api_key", "")).strip()
            if not provider:
                self._send_json({"error": "provider is required"}, 400)
                return
            if not key:
                self._send_json({"error": "api_key is required"}, 400)
                return
            if provider not in PROVIDERS and provider not in load_config().get(
                "custom_providers", {}
            ):
                self._send_json({"error": f"Unknown provider: {provider}"}, 400)
                return
            set_api_key(key, provider)
            self._send_json({"ok": True, "provider": provider})
            return

        if self.path == "/api/models":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send_json({"error": "invalid JSON"}, 400)
                return
            base = str(payload.get("base_url", "")).strip().rstrip("/")
            key = str(payload.get("api_key", "")).strip()
            if not base.startswith(("http://", "https://")):
                self._send_json(
                    {"error": "Base URL must start with http:// or https://"}, 400
                )
                return
            import urllib.error
            import urllib.request

            req = urllib.request.Request(base + "/models")
            if key:
                req.add_header("Authorization", "Bearer " + key)
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                self._send_json(
                    {"error": f"Provider returned HTTP {e.code}: {detail}"}, 502
                )
                return
            except Exception as e:
                self._send_json({"error": f"Could not reach provider: {e}"}, 502)
                return
            raw = data.get("data") if isinstance(data, dict) else data
            ids = []
            if isinstance(raw, list):
                for m in raw:
                    if isinstance(m, dict) and m.get("id"):
                        ids.append(str(m["id"]))
                    elif isinstance(m, str):
                        ids.append(m)
            if not ids:
                self._send_json(
                    {"error": "Provider responded but returned no model list."}, 502
                )
                return
            self._send_json({"models": ids})
            return

        if self.path in ("/api/providers", "/api/providers/remove"):
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send_json({"error": "invalid JSON"}, 400)
                return
            from openlink_ai.config import add_provider, remove_provider

            try:
                if self.path == "/api/providers":
                    added = add_provider(
                        label=str(payload.get("label", "")),
                        base_url=str(payload.get("base_url", "")),
                        models=[str(m) for m in payload.get("models", [])],
                        model=str(payload.get("model", "")),
                        api_key=str(payload.get("api_key", "")),
                    )
                    self._send_json(
                        {
                            "provider_id": added["id"],
                            "provider": added["label"],
                            "model": added["model"],
                            "added": True,
                        }
                    )
                else:
                    remove_provider(str(payload.get("provider", "")))
                    self._send_json({"removed": True})
            except ValueError as e:
                self._send_json({"error": str(e)}, 400)
            return

        if self.path == "/api/select":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send_json({"error": "invalid JSON"}, 400)
                return
            from openlink_ai.config import set_provider

            try:
                if payload.get("provider"):
                    config = set_provider(payload["provider"])
                else:
                    config = update_config()
                if payload.get("model"):
                    config = update_config(model=payload["model"])
                provider = provider_preset(config["provider"]) or {}
                self._send_json(
                    {
                        "provider": provider.get("label", config["provider"]),
                        "provider_id": config["provider"],
                        "model": config["model"],
                        "ready": bool(config["api_key"])
                        or provider.get("local", False),
                    }
                )
            except ValueError as e:
                self._send_json({"error": str(e)}, 400)
            return

        if self.path == "/api/settings":
            payload = self._body()
            if payload is None:
                self._send_json({"error": "invalid JSON"}, 400)
                return
            if "allow_exec" not in payload:
                self._send_json({"error": "allow_exec is required"}, 400)
                return
            allow = bool(payload.get("allow_exec"))
            if allow:
                state = self.workspace_state()
                if not state["trusted"]:
                    self._send_json(
                        {
                            "error": (
                                "Open and trust a folder first — commands only "
                                "run inside a trusted folder."
                            )
                        },
                        403,
                    )
                    return
            update_config(allow_exec=allow)
            self._send_json({"allow_exec": allow})
            return

        if self.path == "/api/vscode":
            payload = self._body()
            if payload is None:
                self._send_json({"error": "invalid JSON"}, 400)
                return
            try:
                root, state = self.pick_root(payload.get("root"))
            except ValueError as e:
                self._send_json({"error": str(e)}, 403)
                return
            if root is None:
                self._send_json(
                    {"error": "Open and trust a folder before opening VS Code."},
                    403,
                )
                return
            rel = str(payload.get("path") or "")
            target = None
            if rel:
                for folder in self.trusted_roots(state):
                    try:
                        target, _rel = self.safe_target(folder, rel)
                    except ValueError:
                        continue
                    break
                if target is None:
                    self._send_json(
                        {"error": "Path is outside the trusted folder."}, 403
                    )
                    return
            else:
                target = root
            if not target.exists():
                self._send_json({"error": f"Not found: {rel or root}"}, 404)
                return
            from openlink_ai.core.tools import open_in_vscode

            result = open_in_vscode(str(target))
            self._send_json(result, 200 if result.get("ok") else 500)
            return

        if self.path != "/api/chat":
            self._send_json({"error": "not found"}, 404)
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON"}, 400)
            return

        message = (payload.get("message") or "").strip()
        files = payload.get("files") or []
        history = payload.get("history") or []
        mode = str(payload.get("mode") or "").strip().lower()
        if mode not in MODE_GUIDANCE:
            mode = "build"
        if files and not message:
            message = "Analyze the attached files."
        if not message:
            self._send_json({"error": "empty message"}, 400)
            return

        try:
            from openlink_ai.core.attachments import format_attachments

            final_message = format_attachments(message, files)
        except ValueError as e:
            self._send_json({"error": str(e)}, 413)
            return

        config = load_config()
        if not config["api_key"] and not (provider_preset(config["provider"]) or {}).get(
            "local"
        ):
            self._send_json({"error": "No API key set. Run the terminal app first."}, 401)
            return

        mode_tools: list[dict] = []
        ws_root = None
        ws_folders: list[Path] = []
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=config["api_key"] or "missing",
                base_url=config.get("base_url") or None,
            )
            system = config["system_prompt"]
            guide = MODE_GUIDANCE.get(mode)
            if guide:
                system = system + "\n\n" + guide
            ws = self.workspace_state()
            ws_folders = self.trusted_roots(ws)
            trusted = bool(ws["trusted"] and ws_folders)
            if ws["trusted"]:
                names = ", ".join(f["path"] for f in ws["folders"])
                system += (
                    "\n\nWorkspace: the user's trusted folders are "
                    f"{names}. Treat them as the project roots: use paths "
                    "relative to them, only work inside them, and never "
                    "suggest changes outside them."
                )
            if trusted:
                from openlink_ai.core.tools import READ_TOOLS, SHELL_TOOL, WRITE_TOOLS

                ws_root = ws_folders[0]
                if mode == "build":
                    mode_tools = list(WRITE_TOOLS)
                    if config.get("allow_exec"):
                        mode_tools.append(SHELL_TOOL)
                elif mode == "plan":
                    mode_tools = list(READ_TOOLS)
            tool_names = [t["function"]["name"] for t in mode_tools]
            if tool_names:
                system += (
                    "\n\nTools for this mode: "
                    + ", ".join(tool_names)
                    + f". They all work inside {ws['path']} and take paths "
                    "relative to it. Use them to actually do the work instead of "
                    "only describing it."
                )
                if "run_shell" in tool_names:
                    system += (
                        "\n\nThe run_shell tool executes PowerShell on the user's "
                        "machine inside that folder and returns stdout, stderr and "
                        "the exit code. Use it to inspect files, build, test and "
                        "install dependencies; keep commands short, avoid "
                        "destructive commands, and never touch paths outside that "
                        "folder."
                    )
                if mode == "plan":
                    system += (
                        "\n\nwrite_file and run_shell are not available: Plan mode "
                        "must not change anything on disk."
                    )
            elif mode == "build" and not trusted:
                system += (
                    "\n\nNo workspace folder is open, so you cannot read or change "
                    "files right now. Answer in chat and tell the user to open a "
                    "folder with the 📁 button so you can work on the files."
                )
            elif mode == "plan" and not trusted:
                system += (
                    "\n\nNo workspace folder is open, so you cannot inspect files. "
                    "Give the plan from what the user tells you and mention that "
                    "opening a folder with 📁 would let you read the project first."
                )
            preset = provider_preset(config["provider"]) or {}
            budget = int(preset.get("input_token_budget") or 100_000)
            history_msgs = [
                {"role": m["role"], "content": m["content"]}
                for m in history
                if m.get("role") in ("user", "assistant") and m.get("content")
            ]
            trimmed = 0
            cost = estimate_tokens(system) + estimate_tokens(final_message)
            total = cost + sum(estimate_tokens(m["content"]) for m in history_msgs)
            while history_msgs and total > budget:
                total -= estimate_tokens(history_msgs[0]["content"])
                history_msgs.pop(0)
                trimmed += 1
            if cost > budget:
                self._send_json(
                    {
                        "error": too_large_message(
                            config.get("model") or "this model", cost, budget
                        )
                    },
                    413,
                )
                return
            messages = [{"role": "system", "content": system}]
            messages.extend(history_msgs)
            messages.append({"role": "user", "content": final_message})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        class ClientGone(Exception):
            """The browser closed the stream (the user pressed ESC twice)."""

        def send(event: str, data):
            chunk = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            try:
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                raise ClientGone()
            except OSError:
                raise ClientGone()

        try:
            send(
                "meta",
                {
                    "user_message": final_message,
                    "mode": mode,
                    "mode_label": MODE_LABEL.get(mode, mode.title()),
                    "tools": [
                        t["function"]["name"]
                        for t in mode_tools
                    ],
                    "folder": ws["path"] if trusted else "",
                    "trusted": trusted,
                },
            )
            if trimmed:
                send(
                    "notice",
                    {
                        "message": (
                            f"{trimmed} older message(s) were left out to stay "
                            "within this provider's request limit."
                        )
                    },
                )
        except ClientGone:
            return

        from openlink_ai.core.completion import stream_completion

        base_messages = [dict(m) for m in messages]
        emitted = False

        allowed_tools = {t["function"]["name"] for t in mode_tools}

        def resolve_target(raw) -> tuple[Path, str]:
            rel = str(raw or "").strip()
            last = None
            for folder in ws_folders:
                try:
                    return self.safe_target(folder, rel)
                except ValueError as e:
                    last = e
            raise ValueError(str(last) or "Path is outside the trusted folder.")

        def run_tool(name: str, args: dict) -> dict:
            args = args if isinstance(args, dict) else {}
            if name not in allowed_tools:
                return {
                    "ok": False,
                    "tool": name,
                    "error": (
                        f"The {name} tool is not available in "
                        f"{MODE_LABEL.get(mode, mode)} mode."
                    ),
                }

            if name == "run_shell":
                command = str(args.get("command") or "")
                rel = str(args.get("cwd") or "").strip()
                target = ws_root
                if rel:
                    inside_any = False
                    found = None
                    for folder in ws_folders:
                        try:
                            candidate, _rel = self.safe_target(folder, rel)
                        except ValueError:
                            continue
                        inside_any = True
                        if candidate.is_dir():
                            found = candidate
                            break
                    if not inside_any:
                        return {
                            "ok": False,
                            "tool": name,
                            "command": command,
                            "error": "Path is outside the trusted folder.",
                        }
                    if found is None:
                        return {
                            "ok": False,
                            "tool": name,
                            "command": command,
                            "error": f"Not a folder inside the workspace: {rel}",
                        }
                    target = found
                from openlink_ai.core.tools import run_shell

                return {"tool": name, **run_shell(command, cwd=str(target))}

            try:
                target, rel = resolve_target(args.get("path", ""))
            except ValueError as e:
                return {"ok": False, "tool": name, "error": str(e)}

            if name == "list_dir":
                if not target.is_dir():
                    return {
                        "ok": False,
                        "tool": name,
                        "error": f"Not a folder: {rel or '.'}",
                    }
                return {
                    "ok": True,
                    "tool": name,
                    "path": rel,
                    "entries": list_dir(target),
                }

            if name == "read_file":
                done = read_text_file(target)
                if not done["ok"]:
                    return {"ok": False, "tool": name, "error": done["error"]}
                return {
                    "ok": True,
                    "tool": name,
                    "path": rel,
                    "content": done["text"],
                    "size": done["size"],
                }

            if name == "write_file":
                content = args.get("content")
                if not isinstance(content, str):
                    return {
                        "ok": False,
                        "tool": name,
                        "error": "content is required.",
                    }
                if target == ws_root or not rel:
                    return {"ok": False, "tool": name, "error": "Invalid file path."}
                done = write_text_file(target, content)
                if not done["ok"]:
                    return {"ok": False, "tool": name, "error": done["error"]}
                return {
                    "ok": True,
                    "tool": name,
                    "path": rel,
                    "size": done["size"],
                    "preview": content[:4000],
                }

            return {"ok": False, "tool": name, "error": f"Unknown tool: {name}"}

        def stream_plain(msgs) -> None:
            nonlocal emitted
            for delta in stream_completion(client, config, msgs):
                emitted = True
                send("token", {"text": delta})

        def fail(err) -> None:
            text = str(err)
            if looks_too_large(text):
                text = too_large_message(
                    config.get("model") or "this model", total, budget, text
                )
            send("error", {"message": text})

        def recover(err) -> None:
            # provider request/token limit: retry once with only this message
            if looks_too_large(str(err)) and history_msgs and not emitted:
                send(
                    "notice",
                    {
                        "message": (
                            "Request limit hit — retrying with only the "
                            "latest message."
                        )
                    },
                )
                try:
                    stream_plain([messages[0], messages[-1]])
                    send("done", {"ok": True})
                    return
                except Exception as retry:
                    err = retry
            fail(err)

        try:
            if mode_tools:
                from openlink_ai.core.tools import stream_agent

                for kind, data in stream_agent(
                    client, config, messages, run_tool, mode_tools
                ):
                    emitted = True
                    if kind == "text":
                        send("token", {"text": data})
                    else:
                        send("tool", data)
            else:
                stream_plain(messages)
            send("done", {"ok": True})
        except ClientGone:
            # the browser stopped the reply (ESC twice) — drop this run
            return
        except Exception as e:
            if mode_tools and not emitted:
                # this model/provider may not support tool calling: answer plainly
                try:
                    stream_plain([dict(m) for m in base_messages])
                    send("done", {"ok": True})
                    return
                except ClientGone:
                    return
                except Exception as retry:
                    recover(retry)
                    return
            try:
                recover(e)
            except ClientGone:
                return


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Openlink AI: http://127.0.0.1:{PORT}")
    for ip in lan_urls():
        print(f"LAN: http://{ip}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
