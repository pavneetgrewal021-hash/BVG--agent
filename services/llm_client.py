"""
The only module that talks to a language model.

Everything model-specific lives here (provider, host, timeouts, context size),
so the rest of the app just asks for "JSON matching this schema" and gets
either a validated object or an LLMError it can fall back from.
"""
import time

from pydantic import ValidationError

DEFAULT_MODEL = "qwen3:4b"
DEFAULT_HOST = "http://localhost:11434"


class LLMError(Exception):
    """Any reason the model could not give a usable answer. Callers fall back on this."""


_clients = {}
_thinking_support = {}


def _client(host, timeout):
    import ollama  # imported lazily so the app still runs without the package when the LLM is off

    key = (host, timeout)
    if key not in _clients:
        _clients[key] = ollama.Client(host=host, timeout=timeout)
    return _clients[key]


def _supports_thinking(client, model):
    if model not in _thinking_support:
        try:
            _thinking_support[model] = "thinking" in (client.show(model).capabilities or [])
        except Exception:
            _thinking_support[model] = False
    return _thinking_support[model]


def chat_tools(messages, tools, settings, num_ctx=4096, num_predict=300):
    """One model turn that may call tools. Returns the assistant message (with .tool_calls)."""
    if settings.get("llm_provider", "ollama") != "ollama":
        raise LLMError("LLM is switched off in Settings")
    model = settings.get("llm_model", DEFAULT_MODEL)
    try:
        client = _client(settings.get("llm_host", DEFAULT_HOST), settings.get("llm_timeout_s", 60))
        kwargs = {"model": model, "messages": messages, "tools": tools,
                  "options": {"temperature": 0, "num_ctx": num_ctx, "num_predict": num_predict}}
        if _supports_thinking(client, model):
            kwargs["think"] = False
        return client.chat(**kwargs).message
    except Exception as e:
        raise LLMError(f"{type(e).__name__}: {e}") from e


def check_model(settings):
    """(ok, message) for the Settings page: is the server up and the model downloaded?"""
    model = settings.get("llm_model", DEFAULT_MODEL)
    try:
        client = _client(settings.get("llm_host", DEFAULT_HOST), 10)
        installed = [m.model for m in client.list().models]
    except Exception as e:
        return False, f"Ollama is not reachable: {e}"
    if model not in installed and f"{model}:latest" not in installed:
        return False, f"Model '{model}' is not downloaded. Run: ollama pull {model}"
    return True, f"Ollama is running and '{model}' is available."


def estimate_tokens(text):
    """Rough upper estimate (about 3 characters per token) used to refuse over-long inputs."""
    return len(text) // 3 + 1


def chat_json(messages, schema, settings, num_ctx=4096, num_predict=256):
    """
    Sends messages and returns (parsed, usage).
      schema   : a pydantic model; generation is constrained to its JSON schema
      parsed   : a validated instance of schema
      usage    : {"model", "prompt_tokens", "output_tokens", "seconds"}
    Raises LLMError for: LLM switched off, server down or slow, input too long,
    output cut off, or output that does not validate.
    """
    if settings.get("llm_provider", "ollama") != "ollama":
        raise LLMError("LLM is switched off in Settings")

    model = settings.get("llm_model", DEFAULT_MODEL)

    # Ollama silently drops the start of a prompt that exceeds num_ctx. Refuse instead.
    prompt_estimate = sum(estimate_tokens(m["content"]) for m in messages)
    if prompt_estimate + num_predict > num_ctx:
        raise LLMError(f"input too long: ~{prompt_estimate} tokens for a {num_ctx}-token context")

    start = time.perf_counter()
    try:
        client = _client(settings.get("llm_host", DEFAULT_HOST), settings.get("llm_timeout_s", 60))
        kwargs = {
            "model": model,
            "messages": messages,
            "format": schema.model_json_schema(),
            "options": {"temperature": 0, "num_ctx": num_ctx, "num_predict": num_predict},
        }
        if _supports_thinking(client, model):
            kwargs["think"] = False  # measured: ~100x slower on this task and no better
        response = client.chat(**kwargs)
    except Exception as e:
        raise LLMError(f"{type(e).__name__}: {e}") from e

    if response.done_reason == "length":
        raise LLMError(f"output cut off at {num_predict} tokens")

    try:
        parsed = schema.model_validate_json(response.message.content)
    except ValidationError as e:
        raise LLMError(f"model output did not match the schema: {e.errors()[0]['msg']}") from e

    usage = {
        "model": model,
        "prompt_tokens": response.prompt_eval_count,
        "output_tokens": response.eval_count,
        "seconds": round(time.perf_counter() - start, 3),
    }
    return parsed, usage
