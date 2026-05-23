# Colophon – e-book metadata manager
"""Tests for the Kobo eReader.conf upload+patch flow."""
import io

import pytest


# ---------------------------------------------------------------------------
# Pure-logic patcher tests
# ---------------------------------------------------------------------------

_MINIMAL_CONF = """\
[OneStoreServices]
api_endpoint=https://storeapi.kobo.com
image_host=https://image-tag.kobo.com
image_url_template=https://image-tag.kobo.com/{ImageId}/{Width}/{Height}/false/image.jpg
image_url_quality_template=https://image-tag.kobo.com/{ImageId}/{Width}/{Height}/{Quality}/{IsGreyscale}/image.jpg
authentication_endpoint=https://oauth.kobo.com/authentication

[OAuth]
client_id=kobo
client_secret=somesecret

[Browser]
disable_javascript=false
"""


def test_patch_replaces_api_endpoint():
    from app.services.kobo_conf import patch_conf_text

    result = patch_conf_text(_MINIMAL_CONF, "http://192.168.1.100:5055/kobo/abc123")

    assert "api_endpoint=http://192.168.1.100:5055/kobo/abc123" in result
    assert "api_endpoint=https://storeapi.kobo.com" not in result


def test_patch_removes_image_lines():
    from app.services.kobo_conf import patch_conf_text

    result = patch_conf_text(_MINIMAL_CONF, "http://x/kobo/y")

    assert "image_host=" not in result
    assert "image_url_template=" not in result
    assert "image_url_quality_template=" not in result


def test_patch_preserves_other_sections_and_keys():
    """Anything outside [OneStoreServices] is byte-preserved."""
    from app.services.kobo_conf import patch_conf_text

    result = patch_conf_text(_MINIMAL_CONF, "http://x/kobo/y")

    assert "[OAuth]" in result
    assert "client_id=kobo" in result
    assert "client_secret=somesecret" in result
    assert "[Browser]" in result
    assert "disable_javascript=false" in result
    # And the surviving non-target key inside [OneStoreServices]
    assert "authentication_endpoint=https://oauth.kobo.com/authentication" in result


def test_patch_only_touches_target_section():
    """A key with the same name in a different section is left alone."""
    from app.services.kobo_conf import patch_conf_text

    conf = """\
[OneStoreServices]
api_endpoint=https://storeapi.kobo.com

[SomethingElse]
api_endpoint=https://other-thing.example
image_host=https://leave-me-alone.example
"""
    result = patch_conf_text(conf, "http://x/kobo/y")

    assert "api_endpoint=http://x/kobo/y" in result
    # The other section's lines must survive intact
    assert "api_endpoint=https://other-thing.example" in result
    assert "image_host=https://leave-me-alone.example" in result


def test_patch_idempotent_on_already_patched_file():
    """Re-uploading an already-patched conf produces the same result."""
    from app.services.kobo_conf import patch_conf_text

    once = patch_conf_text(_MINIMAL_CONF, "http://x/kobo/y")
    twice = patch_conf_text(once, "http://x/kobo/y")

    assert once == twice


def test_patch_appends_api_endpoint_when_missing():
    """Some firmwares ship without an explicit api_endpoint; we must add one."""
    from app.services.kobo_conf import patch_conf_text

    conf = """\
[OneStoreServices]
image_host=https://image-tag.kobo.com

[OAuth]
client_id=kobo
"""
    result = patch_conf_text(conf, "http://x/kobo/y")

    assert "api_endpoint=http://x/kobo/y" in result
    assert "image_host=" not in result
    # The added api_endpoint must be inside [OneStoreServices], not after [OAuth]
    one_store_idx = result.index("[OneStoreServices]")
    oauth_idx = result.index("[OAuth]")
    api_idx = result.index("api_endpoint=")
    assert one_store_idx < api_idx < oauth_idx


def test_patch_appends_api_endpoint_at_eof_when_target_is_last_section():
    from app.services.kobo_conf import patch_conf_text

    conf = """\
[OAuth]
client_id=kobo

[OneStoreServices]
image_host=https://image-tag.kobo.com
"""
    result = patch_conf_text(conf, "http://x/kobo/y")
    assert "api_endpoint=http://x/kobo/y" in result
    assert "image_host=" not in result


def test_patch_preserves_crlf_line_endings():
    from app.services.kobo_conf import patch_conf_text

    conf = "[OneStoreServices]\r\napi_endpoint=https://storeapi.kobo.com\r\n\r\n[OAuth]\r\nclient_id=kobo\r\n"
    result = patch_conf_text(conf, "http://x/kobo/y")

    # CRLF on the rewritten line (matches source line)
    assert "api_endpoint=http://x/kobo/y\r\n" in result
    # Other CRLF lines preserved
    assert "[OAuth]\r\n" in result


def test_patch_preserves_lf_line_endings():
    from app.services.kobo_conf import patch_conf_text

    conf = "[OneStoreServices]\napi_endpoint=https://storeapi.kobo.com\n"
    result = patch_conf_text(conf, "http://x/kobo/y")

    assert "\r\n" not in result
    assert "api_endpoint=http://x/kobo/y\n" in result


def test_patch_preserves_comments_and_blank_lines():
    """Kobo conf has occasional blank lines and (rare) #-comments. Keep them."""
    from app.services.kobo_conf import patch_conf_text

    conf = """\
# Top-of-file comment that some firmware writes
[OneStoreServices]

api_endpoint=https://storeapi.kobo.com

# inline comment
image_host=https://image-tag.kobo.com

[OAuth]
"""
    result = patch_conf_text(conf, "http://x/kobo/y")
    assert "# Top-of-file comment" in result
    assert "# inline comment" in result
    # The blank lines around the kept content survive
    assert result.count("\n\n") >= 2


def test_patch_rejects_non_kobo_file():
    from app.services.kobo_conf import KoboConfError, patch_conf_text

    with pytest.raises(KoboConfError):
        patch_conf_text("just some random text", "http://x/kobo/y")


def test_decode_handles_utf8_bom():
    from app.services.kobo_conf import decode_conf, encode_conf

    raw = b"\xef\xbb\xbf[OneStoreServices]\napi_endpoint=foo\n"
    text, encoding = decode_conf(raw)
    assert text.startswith("[OneStoreServices]")
    assert encoding == "utf-8-sig"
    # Round-trip
    assert encode_conf(text, encoding) == raw


def test_decode_handles_utf16():
    from app.services.kobo_conf import decode_conf, encode_conf

    source_text = "[OneStoreServices]\napi_endpoint=foo\n"
    raw = source_text.encode("utf-16")
    text, encoding = decode_conf(raw)
    assert text == source_text
    assert encoding == "utf-16"
    # Round-trip
    assert encode_conf(text, encoding) == raw


def test_decode_handles_plain_utf8():
    from app.services.kobo_conf import decode_conf

    raw = b"[OneStoreServices]\napi_endpoint=foo\n"
    text, encoding = decode_conf(raw)
    assert text.startswith("[OneStoreServices]")
    assert encoding == "utf-8"


# ---------------------------------------------------------------------------
# Integration — Flask route end-to-end
# ---------------------------------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("COLOPHON_SECRET_KEY", "test-secret")
    from app import create_app
    from app.models import KoboDevice, db
    from sqlalchemy import text as sqltext

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        db.session.execute(sqltext("DELETE FROM kobo_devices"))
        db.session.commit()
    yield flask_app
    with flask_app.app_context():
        db.session.execute(sqltext("DELETE FROM kobo_devices"))
        db.session.commit()


@pytest.fixture
def client(app):
    return app.test_client()


def test_patch_route_returns_modified_file(app, client):
    from app.services.kobo_auth import create_device

    with app.app_context():
        _, token = create_device("Upload test")

    resp = client.post(
        "/settings/kobo/patch-conf",
        data={
            "token": token,
            "conf": (io.BytesIO(_MINIMAL_CONF.encode("utf-8")), "Kobo eReader.conf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert resp.headers["Content-Disposition"].startswith("attachment")
    body = resp.data.decode("utf-8")
    assert f"api_endpoint=" in body
    assert token in body
    assert "image_host=" not in body
    assert "image_url_template=" not in body


def test_patch_route_rejects_invalid_token(app, client):
    resp = client.post(
        "/settings/kobo/patch-conf",
        data={
            "token": "not-a-valid-token",
            "conf": (io.BytesIO(_MINIMAL_CONF.encode("utf-8")), "Kobo eReader.conf"),
        },
        content_type="multipart/form-data",
    )
    # Invalid token → redirect to settings page with flash
    assert resp.status_code == 302
    assert "/settings/kobo" in resp.headers["Location"]


def test_patch_route_rejects_unknown_token(app, client):
    # Well-formed but no matching device
    resp = client.post(
        "/settings/kobo/patch-conf",
        data={
            "token": "a" * 32,
            "conf": (io.BytesIO(_MINIMAL_CONF.encode("utf-8")), "Kobo eReader.conf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302


def test_patch_route_rejects_non_kobo_file(app, client):
    from app.services.kobo_auth import create_device

    with app.app_context():
        _, token = create_device("Bad upload test")

    resp = client.post(
        "/settings/kobo/patch-conf",
        data={
            "token": token,
            "conf": (io.BytesIO(b"random text not a kobo conf"), "evil.txt"),
        },
        content_type="multipart/form-data",
    )
    # Bad file → redirect with flash, not a 500
    assert resp.status_code == 302


def test_patch_route_rejects_huge_file(app, client):
    from app.services.kobo_auth import create_device
    from app.services.kobo_conf import MAX_CONF_BYTES

    with app.app_context():
        _, token = create_device("Big upload test")

    huge = b"x" * (MAX_CONF_BYTES + 100)
    resp = client.post(
        "/settings/kobo/patch-conf",
        data={
            "token": token,
            "conf": (io.BytesIO(huge), "Kobo eReader.conf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302
