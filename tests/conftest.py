import pytest

from app import docker_exec


@pytest.fixture(autouse=True)
def _fresh_exec_gate():
    """The exec permission cache is process-wide: never let it leak between tests."""
    docker_exec.gate.reset()
    yield
    docker_exec.gate.reset()
