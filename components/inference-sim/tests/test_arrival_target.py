"""Replica-capped session arrival target."""

from app.simulation.request_generator import arrival_target_users


def test_arrival_target_users_caps_high_slider():
    assert arrival_target_users(500, 8) == 8
    assert arrival_target_users(3, 8) == 3


def test_arrival_target_users_minimum_replica_one():
    assert arrival_target_users(100, 0) == 1
