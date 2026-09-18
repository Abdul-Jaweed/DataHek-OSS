"""Structured logging — optional JSON output for production log pipelines.

DATAHEK_LOG_FORMAT=json switches the root handler to one-JSON-object-per-line
with timestamp, level, logger, message and exception info.
"""
import json
import logging
import os
import time


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    """Install the JSON formatter when DATAHEK_LOG_FORMAT=json (default: text)."""
    if os.environ.get("DATAHEK_LOG_FORMAT", "text").lower() != "json":
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
