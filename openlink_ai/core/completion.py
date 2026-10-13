CONTINUE_ROUNDS = 15
NUDGE_ROUNDS = 3

CONTINUE_NUDGE = (
    "Continue exactly where you stopped. Do not repeat anything already produced, "
    "do not open a new code fence, and write no commentary - output only the "
    "remaining content until the file is complete."
)

MAX_TOKENS_ERROR = (
    "max_tokens",
    "max_completion_tokens",
    "max output tokens",
    "maximum output",
    "max output length",
)

CONTEXT_ERROR = (
    "context length",
    "maximum context",
    "context window",
    "prompt is too long",
    "input is too long",
    "too many tokens",
)


def _request_kwargs(config: dict, messages: list) -> dict:
    kwargs = {
        "model": config["model"],
        "messages": messages,
        "temperature": config.get("temperature", 0.7),
        "stream": True,
    }
    if config.get("max_tokens"):
        kwargs["max_tokens"] = config["max_tokens"]
    return kwargs


def _open_stream(client, kwargs: dict, messages: list):
    for _ in range(8):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:
            text = str(exc).lower()
            if kwargs.get("max_tokens") and any(t in text for t in MAX_TOKENS_ERROR):
                kwargs.pop("max_tokens")
            elif len(messages) > 2 and any(t in text for t in CONTEXT_ERROR):
                del messages[1]
            else:
                raise
    return client.chat.completions.create(**kwargs)


def _unclosed_fence(text: str) -> bool:
    return text.count("```") % 2 == 1


def stream_completion(client, config: dict, messages: list, max_rounds: int = CONTINUE_ROUNDS):
    rounds = 0
    nudges = 0
    written = []
    while rounds < max_rounds:
        rounds += 1
        stream = _open_stream(client, _request_kwargs(config, messages), messages)
        finish = None
        parts = []
        for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            choice = chunk.choices[0]
            if getattr(choice, "finish_reason", None):
                finish = choice.finish_reason
            delta = getattr(choice, "delta", None)
            text = getattr(delta, "content", None) if delta else None
            if text:
                parts.append(text)
                yield text
        if not parts:
            return
        produced = "".join(parts)
        written.append(produced)
        if finish == "length":
            messages.append({"role": "assistant", "content": produced})
            continue
        if finish in ("content_filter", "safety"):
            raise RuntimeError("The provider stopped the response (content filter).")
        if _unclosed_fence("".join(written)) and nudges < NUDGE_ROUNDS:
            nudges += 1
            messages.append({"role": "assistant", "content": produced})
            messages.append({"role": "user", "content": CONTINUE_NUDGE})
            continue
        return
    raise RuntimeError("Response stopped before it was finished (output limit reached).")
