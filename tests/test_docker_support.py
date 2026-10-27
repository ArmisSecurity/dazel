import pytest

from docker_support import REQUIRE_DOCKER_VARIABLE, skip_unless_required


def test_a_missing_requirement_skips_the_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REQUIRE_DOCKER_VARIABLE, raising=False)
    with pytest.raises(pytest.skip.Exception, match="needs a docker daemon"):
        skip_unless_required("a docker daemon")


def test_a_missing_requirement_fails_the_test_when_docker_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REQUIRE_DOCKER_VARIABLE, "1")
    with pytest.raises(pytest.fail.Exception, match="DAZEL_REQUIRE_DOCKER is set"):
        skip_unless_required("a docker daemon")
