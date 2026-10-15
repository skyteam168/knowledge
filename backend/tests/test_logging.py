import json
import logging

from app.core.logging import JsonFormatter, trace_id_var


def test_json_formatter_includes_trace_id_and_extra() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.user = "alice"
    token = trace_id_var.set("trace-xyz")
    try:
        out = json.loads(JsonFormatter().format(record))
    finally:
        trace_id_var.reset(token)
    assert out["message"] == "hello world"
    assert out["trace_id"] == "trace-xyz"
    assert out["level"] == "INFO"
    assert out["user"] == "alice"
