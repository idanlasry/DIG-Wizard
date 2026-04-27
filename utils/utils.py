# utils.py
import time
import anthropic

_RETRYABLE = {429, 500, 529}


def with_backoff(fn, *args, **kwargs):
    last_exc = None
    for attempt in range(3):
        try:
            return fn(*args, **kwargs)
        except anthropic.APIStatusError as e:
            if e.status_code not in _RETRYABLE:
                raise
            last_exc = e
            time.sleep(2 ** attempt)  # 1s, 2s, 4s
    raise last_exc


MODEL_PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-20250514":  {"input": 3.00, "output": 15.00},
}


def calculate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    pricing = MODEL_PRICING.get(model, {"input": 3.00, "output": 15.00})
    return (input_tokens / 1_000_000 * pricing["input"]) + (output_tokens / 1_000_000 * pricing["output"])
