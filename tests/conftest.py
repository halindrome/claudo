import os
import pytest


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Create an isolated CONFIG_DIR with required subdirectories.

    Sets the CONFIG_DIR env var so bash functions and Python modules under
    test use the temp directory instead of the real config location.
    Cleans up the env var after the test completes.
    """
    (tmp_path / "instances").mkdir()
    (tmp_path / "logs").mkdir()

    os.environ["CONFIG_DIR"] = str(tmp_path)
    yield tmp_path

    del os.environ["CONFIG_DIR"]
