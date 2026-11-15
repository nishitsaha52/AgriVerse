import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agriverse import observability


@pytest.mark.parametrize("endpoint", [None, "", "   "])
def test_unconfigured_telemetry_does_not_initialize_exporters(monkeypatch, endpoint):
    monkeypatch.setattr(
        observability,
        "settings",
        SimpleNamespace(otel_exporter_otlp_endpoint=endpoint),
    )
    initialize = Mock()
    monkeypatch.setattr(observability, "_configure_observability", initialize)
    observability.configure_observability()
    initialize.assert_not_called()


def test_configured_telemetry_receives_application_components(monkeypatch):
    monkeypatch.setattr(
        observability,
        "settings",
        SimpleNamespace(otel_exporter_otlp_endpoint="http://collector:4318"),
    )
    initialize = Mock()
    monkeypatch.setattr(observability, "_configure_observability", initialize)
    app, engine, redis = object(), object(), object()
    observability.configure_observability(app, engine, redis, "test-api")
    initialize.assert_called_once_with(app, engine, redis, "test-api")


def test_optional_telemetry_setup_failure_does_not_escape_or_log_secrets(monkeypatch, caplog):
    monkeypatch.setattr(
        observability,
        "settings",
        SimpleNamespace(otel_exporter_otlp_endpoint="http://collector:4318"),
    )
    initialize = Mock(side_effect=RuntimeError("sensitive provider configuration"))
    monkeypatch.setattr(observability, "_configure_observability", initialize)
    with caplog.at_level(logging.WARNING):
        observability.configure_observability()
    assert "continuing application startup" in caplog.text
    assert "sensitive provider configuration" not in caplog.text
