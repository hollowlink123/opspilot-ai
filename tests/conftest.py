"""Offline-by-default verification: real clients and network access are forbidden."""
import socket

import pytest
from google import genai
from opspilot.config import Settings


@pytest.fixture(autouse=True)
def offline_test_boundary(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Live network or Gemini client forbidden in automated tests')

    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GEMINI_MODEL', raising=False)
    for name in Settings.model_fields:
        monkeypatch.delenv(f'OPSPILOT_{name.upper()}', raising=False)
    monkeypatch.setattr(genai, 'Client', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket.socket, 'sendto', forbidden)
