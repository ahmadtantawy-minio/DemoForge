"""MinIO Console proxy URL helpers — legacy /console/* SPA routes."""

from app.engine.proxy_gateway import (
    _normalize_proxy_subpath,
    console_legacy_subpath_redirect,
)


def test_normalize_proxy_subpath_strips_inner_console_for_upstream():
    assert _normalize_proxy_subpath("console", "console/identity") == "identity"
    assert _normalize_proxy_subpath("console", "identity") == "identity"
    assert _normalize_proxy_subpath("console", "object-store/details") == "object-store/details"
    assert _normalize_proxy_subpath("s3", "foo") == "foo"


def test_console_legacy_redirect_adds_inner_console_segment():
    demo, node = "abc123", "minio-cluster-1-lb"
    assert console_legacy_subpath_redirect(demo, node, "console", "identity") == (
        f"/proxy/{demo}/{node}/console/console/identity"
    )
    assert console_legacy_subpath_redirect(demo, node, "console", "buckets") == (
        f"/proxy/{demo}/{node}/console/console/buckets"
    )


def test_console_legacy_redirect_skips_object_store_and_assets():
    demo, node = "abc123", "minio-cluster-1-lb"
    assert console_legacy_subpath_redirect(demo, node, "console", "object-store/details") is None
    assert console_legacy_subpath_redirect(demo, node, "console", "console/identity") is None
    assert console_legacy_subpath_redirect(demo, node, "console", "static/js/app.js") is None
    assert console_legacy_subpath_redirect(demo, node, "console", "api/v1/session") is None
    assert console_legacy_subpath_redirect(demo, node, "console", "login") is None
    assert console_legacy_subpath_redirect(demo, node, "console", "") is None
