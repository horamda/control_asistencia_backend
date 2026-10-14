import pytest
from scripts.check_deployed_revision import validate


def test_exact_revision_passes():
    validate({"status": "ok", "revision": "abc123"}, "abc123")


@pytest.mark.parametrize("payload", [
    {"status": "ok"},
    {"status": "ok", "revision": "older"},
    {"status": "error", "revision": "abc123"},
])
def test_missing_old_or_unhealthy_release_is_rejected(payload):
    with pytest.raises(ValueError):
        validate(payload, "abc123")
