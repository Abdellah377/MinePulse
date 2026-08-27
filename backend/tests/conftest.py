"""Pytest fixtures. Integration tests opt in with --integration."""

from __future__ import annotations

import pytest


def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true", default=False)
    parser.addoption(
        "--run-ai",
        action="store_true",
        default=False,
        help="Run opt-in tests that call the configured paid AI provider.",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "ai_eval: LangGraph evaluation harness tests")
    config.addinivalue_line("markers", "real_ai: invokes the configured external AI provider")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
