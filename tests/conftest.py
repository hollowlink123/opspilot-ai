"""Offline-by-default verification: real clients and network access are forbidden."""
import socket

import pytest
from google import genai
from opspilot import config
from opspilot.config import Settings


@pytest.fixture(autouse=True)
def offline_test_boundary(monkeypatch, tmp_path):
    # Never load a developer's real .env during automated tests.
    monkeypatch.setattr(config, 'ENV_FILE', tmp_path / '.env')
    def forbidden(*args, **kwargs):
        raise AssertionError('Live network or Gemini client forbidden in automated tests')

    original_connect = socket.socket.connect

    def loopback_connect(sock, address):
        if isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'}:
            return original_connect(sock, address)
        forbidden()

    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GEMINI_MODEL', raising=False)
    for name in Settings.model_fields:
        monkeypatch.delenv(f'OPSPILOT_{name.upper()}', raising=False)
    monkeypatch.setattr(genai, 'Client', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', loopback_connect)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket.socket, 'sendto', forbidden)
