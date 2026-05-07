"""Normalize OpenTelemetry OTLP exporter env vars before SDK/exporters initialize."""

import os


def normalize_otlp_endpoint_env() -> None:
    """OTLP exporters require an absolute URL; path-only values break requests (MissingSchema)."""
    for key in ("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT"):
        val = (os.environ.get(key) or "").strip()
        if not val or "://" in val:
            continue
        if not val.startswith("/"):
            continue
        base = (os.environ.get("LANGFUSE_HOST") or os.environ.get("LANGFUSE_BASE_URL") or "").strip().rstrip(
            "/"
        )
        if base:
            os.environ[key] = f"{base}{val}"
