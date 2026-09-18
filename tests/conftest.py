import socket

import pytest


class RepoRootIsNotATestPackage:
    """The Dash app's root __init__.py makes pytest collect the repo root as a
    package and import it, which runs the whole Dash app. Collect the root as a
    plain directory instead. Delete this once the Dash app is removed (#10).

    Registered as a plugin rather than defined as a conftest hook, because
    conftest hooks only apply to paths under tests/, not the repo root.
    """

    @pytest.hookimpl(tryfirst=True)
    def pytest_collect_directory(self, path, parent):
        if path == parent.config.rootpath:
            return pytest.Dir.from_parent(parent, path=path)
        return None


def pytest_configure(config):
    config.pluginmanager.register(RepoRootIsNotATestPackage(), "repo-root-is-not-a-test-package")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests serve saved responses. Any real connection attempt fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
