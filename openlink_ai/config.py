import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".openlink_ai"
CONFIG_FILE = CONFIG_DIR / "config.json"

PROVIDERS = {
    "opencode": {
        "label": "OpenCode Zen (Free)",
        "base_url": "https://opencode.ai/zen/v1",
        "model": "mimo-v2.6-flash-free",
        "models": [
            "mimo-v2.6-flash-free",
            "big-pickle",
            "space-bunny-free",
            "longcat-2.5-preview-free",
            "fledge-alpha-free",
            "mimo-v2.5-free",
            "ling-3.1-flash-free",
            "ling-3.0-flash-fin-free",
            "nemotron-3-ultra-free",
            "nemotron-3.5-lightning-free",
        ],
        "key_url": "https://opencode.ai/auth",
    },
    "openrouter": {
        "label": "OpenRouter (free models)",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
        "models": [
            "nvidia/nemotron-3-super-120b-a12b:free",
            "nvidia/nemotron-3.5-lightning:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "nvidia/nemotron-3.5-content-safety:free",
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
            "thinkingmachines/inkling:free",
            "thinkingmachines/inkling-small:free",
            "dots-studio/dots-3-note-preview:free",
            "poolside/laguna-s-2.1:free",
            "poolside/laguna-xs-2.1:free",
            "cohere/north-mini-code:free",
            "liquid/lfm-2.5-2.6b:free",
            "google/gemma-4-31b-it:free",
            "google/gemma-4-26b-a4b-it:free",
            "apodex/apodex-1.1-mini:free",
        ],
        "key_url": "https://openrouter.ai/keys",
    },
    "openlink": {
        "label": "Openlink AI",
        "base_url": "https://apihub.agnes-ai.com/v1",
        "model": "agnes-3.0-flash",
        "models": [
            "agnes-3.0-flash",
            "agnes-3.0-flash-max",
            "agnes-2.5-flash",
            "agnes-2.5-pro",
        ],
    },
    "nararouter": {
        "label": "Nara Router (free)",
        "base_url": "https://router.bynara.id/v1",
        "model": "agnes-3-flash",
        "input_token_budget": 16000,
        "models": [
            "agnes-3-flash",
            "agnes-2.5-flash",
            "longcat-2.5",
            "deepseek-v4-flash",
        ],
    },
    "siliconflow": {
        "label": "SiliconFlow (free models)",
        "base_url": "https://api.siliconflow.com/v1",
        "model": "Qwen/Qwen3-8B",
        "models": [
            "Qwen/Qwen3-8B",
        ],
        "key_url": "https://cloud.siliconflow.com/models",
    },
    "groq": {
        "label": "Groq (fast)",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
        "input_token_budget": 6000,
        "models": [
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "qwen/qwen3.8-27b",
            "allam-2-7b",
        ],
        "key_url": "https://console.groq.com",
    },
    "ollama": {
        "label": "Ollama (local, free)",
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.2",
        "models": ["llama3.2", "qwen2.5", "mistral", "phi3"],
        "local": True,
    },
}

DEFAULTS = {
    "provider": "openrouter",
    "api_key": "",
    "api_keys": {},
    "custom_providers": {},
    "base_url": "",
    "model": "",
    "system_prompt": (
        "You are OpenLink AI, a helpful assistant. Always finish the job: when you "
        "write code, an HTML page or any file, output the complete finished content "
        "from start to end and never stop partway or ask to continue."
    ),
    "temperature": 0.7,
    "max_tokens": 8192,
    "workspace_root": "",
    "workspace_folders": [],
    "trusted_paths": [],
    "allow_exec": False,
}

LEGACY_SYSTEM_PROMPT = "You are OpenLink AI, a helpful terminal assistant."
LEGACY_MAX_TOKENS = 2048


def load_config() -> dict:
    config = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            config.update({k: v for k, v in saved.items() if k in DEFAULTS})
        except (json.JSONDecodeError, OSError):
            pass

    if config.get("max_tokens") == LEGACY_MAX_TOKENS:
        config["max_tokens"] = DEFAULTS["max_tokens"]
    if config.get("system_prompt") == LEGACY_SYSTEM_PROMPT:
        config["system_prompt"] = DEFAULTS["system_prompt"]

    if config.get("api_key") and not config["api_keys"].get(config["provider"]):
        config["api_keys"][config["provider"]] = config["api_key"]

    provider = config.get("provider", "openrouter")
    preset = PROVIDERS.get(provider) or config.get("custom_providers", {}).get(
        provider
    )
    if preset:
        if not config.get("base_url"):
            config["base_url"] = preset["base_url"]
        if not config.get("model"):
            config["model"] = preset.get("model", "")

    env_key = (
        os.environ.get("OPENLINK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ZAI_API_KEY")
    )
    if env_key:
        config["api_keys"][provider] = env_key
    return config


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def update_config(**kwargs) -> dict:
    config = load_config()
    config.update(kwargs)
    save_config(config)
    return config


def provider_preset(provider: str) -> dict | None:
    if provider in PROVIDERS:
        return PROVIDERS[provider]
    return load_config().get("custom_providers", {}).get(provider)


def set_provider(provider: str) -> dict:
    config = load_config()
    preset = PROVIDERS.get(provider) or config.get("custom_providers", {}).get(
        provider
    )
    if not preset:
        raise ValueError(f"Unknown provider: {provider}")
    config["provider"] = provider
    config["base_url"] = preset["base_url"]
    config["model"] = preset.get("model", config.get("model", ""))
    config["api_key"] = config["api_keys"].get(provider, "")
    save_config(config)
    return config


def add_provider(
    label: str,
    base_url: str,
    models: list[str],
    model: str = "",
    api_key: str = "",
    pid: str = "",
) -> dict:
    label = (label or "").strip()
    base_url = (base_url or "").strip().rstrip("/")
    models = [m.strip() for m in models if m and m.strip()]
    if not label:
        raise ValueError("Provider name is required.")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("Base URL must start with http:// or https://")
    if not models:
        raise ValueError("At least one model is required.")
    model = (model or "").strip() or models[0]
    if model not in models:
        models.insert(0, model)

    slug = (
        "".join(c.lower() if c.isalnum() else "-" for c in label).strip("-")
        or "custom"
    )
    base = slug
    n = 2
    config = load_config()
    custom = config.get("custom_providers", {})
    while slug in PROVIDERS:
        slug = f"{base}-{n}"
        n += 1

    entry = {
        "label": label,
        "base_url": base_url,
        "model": model,
        "models": models,
        "custom": True,
    }
    custom[slug] = entry
    config["custom_providers"] = custom
    if api_key:
        config["api_keys"][slug] = api_key
    save_config(config)
    return {"id": slug, **entry}


def remove_provider(provider: str) -> dict:
    config = load_config()
    custom = config.get("custom_providers", {})
    if provider not in custom:
        raise ValueError(f"Unknown custom provider: {provider}")
    custom.pop(provider, None)
    config["custom_providers"] = custom
    config["api_keys"].pop(provider, None)
    if config.get("provider") == provider:
        fallback = "openrouter" if "openrouter" in PROVIDERS else next(iter(PROVIDERS))
        config["provider"] = fallback
        preset = PROVIDERS[fallback]
        config["base_url"] = preset["base_url"]
        config["model"] = preset["model"]
        config["api_key"] = config["api_keys"].get(fallback, "")
    save_config(config)
    return config


def set_api_key(key: str, provider: str | None = None) -> dict:
    config = load_config()
    provider = provider or config["provider"]
    config["api_keys"][provider] = key
    if provider == config["provider"]:
        config["api_key"] = key
    save_config(config)
    return config
