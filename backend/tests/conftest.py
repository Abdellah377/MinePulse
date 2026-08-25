"""Pytest fixtures. Integration tests opt in with --integration."""

from __future__ import annotations

import pytest


def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true", default=False)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
