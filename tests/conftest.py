import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests serve saved responses. Any real connection attempt fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
