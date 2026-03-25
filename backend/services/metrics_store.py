import json
import os
import threading
import time

_METRICS_FILE = "/app/data/claude_metrics.json"
_LOCK = threading.Lock()

_DEFAULT_METRICS = {
    "requests_total": 0,
    "input_tokens_total": 0,
    "output_tokens_total": 0,
    "tokens_total": 0,

    "requests_today": 0,
    "tokens_today": 0,
    "last_day": None,

    "last_request_ts": None,
    "last_error": None,
}


def _load_metrics() -> dict:
    if not os.path.exists(_METRICS_FILE):
        return _DEFAULT_METRICS.copy()

    try:
        with open(_METRICS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        result = _DEFAULT_METRICS.copy()
        result.update(data)
        return result
    except Exception:
        return _DEFAULT_METRICS.copy()


def _save_metrics(data: dict) -> None:
    tmp_file = f"{_METRICS_FILE}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, _METRICS_FILE)


def get_metrics() -> dict:
    with _LOCK:
        return _load_metrics()


def record_usage(input_tokens: int, output_tokens: int) -> None:
    with _LOCK:
        data = _load_metrics()

        today = time.strftime("%Y-%m-%d")

        # Reset diario
        if data.get("last_day") != today:
            data["requests_today"] = 0
            data["tokens_today"] = 0
            data["last_day"] = today

        tokens = int(input_tokens or 0) + int(output_tokens or 0)

        # Totales históricos
        data["requests_total"] += 1
        data["input_tokens_total"] += int(input_tokens or 0)
        data["output_tokens_total"] += int(output_tokens or 0)
        data["tokens_total"] = data["input_tokens_total"] + data["output_tokens_total"]

        # Totales diarios
        data["requests_today"] += 1
        data["tokens_today"] += tokens

        data["last_request_ts"] = time.time()
        data["last_error"] = None

        _save_metrics(data)


def record_error(error_message: str) -> None:
    with _LOCK:
        data = _load_metrics()
        data["last_error"] = str(error_message)
        data["last_request_ts"] = time.time()
        _save_metrics(data)


def reset_metrics() -> None:
    with _LOCK:
        _save_metrics(_DEFAULT_METRICS.copy())