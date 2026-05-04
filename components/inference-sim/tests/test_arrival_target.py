"""Session arrival target follows the configured concurrent-users slider only."""

from app.simulation.request_generator import arrival_target_users


def test_arrival_target_users_is_non_negative_slider_value() -> None:
    assert arrival_target_users(500) == 500
    assert arrival_target_users(3) == 3
    assert arrival_target_users(0) == 0
