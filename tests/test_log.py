import pytest
from loguru import logger

from craigslist.log import configure_logging


@pytest.fixture(autouse=True)
def remove_log_handlers():
    yield
    logger.remove()


def test_writes_craigslist_log_in_the_given_directory(tmp_path):
    log_file = configure_logging("INFO", log_dir=tmp_path / "logs")

    logger.info("hello from the test")

    assert log_file == tmp_path / "logs" / "craigslist.log"
    assert "hello from the test" in log_file.read_text()


def test_configuring_twice_does_not_duplicate_lines(tmp_path):
    configure_logging("INFO", log_dir=tmp_path)
    log_file = configure_logging("INFO", log_dir=tmp_path)

    logger.info("only once")

    assert log_file.read_text().count("only once") == 1


def test_log_directory_defaults_to_CRAIGSLIST_LOGDIR(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAIGSLIST_LOGDIR", str(tmp_path / "from-env"))

    log_file = configure_logging("INFO")
    logger.info("routed by env")

    assert log_file == tmp_path / "from-env" / "craigslist.log"
    assert "routed by env" in log_file.read_text()
