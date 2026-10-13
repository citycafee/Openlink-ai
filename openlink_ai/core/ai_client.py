from openai import OpenAI


class AIClient:
    def __init__(self, config: dict):
        self.config = config
        self.client = self._build_client()
        self.history: list[dict] = [
            {"role": "system", "content": config["system_prompt"]}
        ]

    def _build_client(self) -> OpenAI:
        return OpenAI(
            api_key=self.config["api_key"] or "missing",
            base_url=self.config.get("base_url") or None,
        )

    def apply_config(self, config: dict, reset_history: bool = False):
        old_key = self.config.get("api_key")
        old_base = self.config.get("base_url")
        self.config = config
        if config.get("api_key") != old_key or config.get("base_url") != old_base:
            self.client = self._build_client()
        if reset_history:
            self.reset()

    @property
    def configured(self) -> bool:
        return bool(self.config["api_key"])

    def chat(self, user_input: str) -> str:
        self.history.append({"role": "user", "content": user_input})
        response = self.client.chat.completions.create(
            model=self.config["model"],
            messages=self.history,
            temperature=self.config["temperature"],
            max_tokens=self.config["max_tokens"],
        )
        reply = response.choices[0].message.content or ""
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def chat_stream(self, user_input: str):
        from .completion import stream_completion

        self.history.append({"role": "user", "content": user_input})
        chunks = []
        for delta in stream_completion(self.client, self.config, list(self.history)):
            chunks.append(delta)
            yield delta
        self.history.append({"role": "assistant", "content": "".join(chunks)})

    def reset(self):
        self.history = [{"role": "system", "content": self.config["system_prompt"]}]
