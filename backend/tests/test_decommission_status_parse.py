"""Unit tests for mc decommission status parsing."""
import pytest

from app.api.instances import _parse_mc_decommission_status


@pytest.mark.parametrize(
    "stdout,stderr,expected",
    [
        ("The cluster is not decommissioning.", "", "active"),
        ("Pool is not being decommissioned.", "", "active"),
        ("Decommissioning complete for pool http://...", "", "decommissioned"),
        ("decommissioning complete\n", "", "decommissioned"),
        ("Status: draining data from pool ...", "", "decommissioning"),
        ("Drain in progress", "", "decommissioning"),
    ],
)
def test_parse_decommission_status(stdout: str, stderr: str, expected: str) -> None:
    status, detail = _parse_mc_decommission_status(stdout, stderr)
    assert status == expected
    assert isinstance(detail, str)
