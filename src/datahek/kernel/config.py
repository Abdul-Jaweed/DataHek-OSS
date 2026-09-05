"""Typed configuration model — env-merged, never stores secrets in dumps."""
import dataclasses
import os
from typing import Any, get_type_hints

_SENSITIVE_FRAGMENTS = ("password", "secret", "token", "api_key", "apikey")


@dataclasses.dataclass
class Config:
    """Base class for typed config dataclasses. Subclass and annotate fields."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        dataclasses.dataclass(cls)


def _convert(value: str, typ: type) -> Any:
    if typ is bool:
        return value.strip().lower() in ("1", "true", "yes", "on")
    if typ is int:
        return int(value)
    if typ is float:
        return float(value)
    return value


def _as_dataclass(cls: type[Config]) -> type[Config]:
    """Ensure subclasses of Config are processed as dataclasses."""
    if not dataclasses.is_dataclass(cls):
        cls = dataclasses.dataclass(cls)
    return cls


def config_from_env(cls: type[Config], prefix: str = "") -> Config:
    """Build ``cls`` from environment variables ``<PREFIX><FIELD>``.

    Missing variables keep field defaults. Unknown env keys are ignored.
    Invalid values raise ``ValueError``.
    """
    cls = _as_dataclass(cls)
    hints = get_type_hints(cls)
    values: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        raw = os.environ.get(prefix + f.name.upper())
        if raw is None:
            continue
        values[f.name] = _convert(raw, hints.get(f.name, str))
    return cls(**values)


def dump_safe(cfg: Config) -> dict[str, Any]:
    """Field dump with sensitive values redacted (never emitted)."""
    cls = _as_dataclass(type(cfg))
    out: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        v = getattr(cfg, f.name)
        if any(frag in f.name.lower() for frag in _SENSITIVE_FRAGMENTS):
            v = "***"
        out[f.name] = v
    return out