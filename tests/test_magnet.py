"""Tests for boltdown.magnet utilities."""

import pytest

from boltdown.magnet import extract_hash, extract_name, extract_trackers, validate
from boltdown.exceptions import InvalidMagnetError


VALID_MAGNET = (
    "magnet:?xt=urn:btih:dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c"
    "&dn=ubuntu-22.04.iso"
    "&tr=udp://tracker.opentrackr.org:1337/announce"
)

B32_MAGNET = (
    "magnet:?xt=urn:btih:3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ"
    "&dn=test-file.zip"
)


class TestValidate:
    def test_valid_magnet_passes(self):
        validate(VALID_MAGNET)  # should not raise

    def test_missing_xt_raises(self):
        with pytest.raises(InvalidMagnetError, match="xt=urn:btih"):
            validate("magnet:?dn=something")

    def test_not_a_magnet_raises(self):
        with pytest.raises(InvalidMagnetError):
            validate("http://example.com/file.torrent")

    def test_none_raises(self):
        with pytest.raises(InvalidMagnetError):
            validate(None)  # type: ignore

    def test_empty_string_raises(self):
        with pytest.raises(InvalidMagnetError):
            validate("")


class TestExtractHash:
    def test_hex_hash(self):
        ih = extract_hash(VALID_MAGNET)
        assert ih == "dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c"

    def test_returns_lowercase(self):
        magnet = "magnet:?xt=urn:btih:DD8255ECDC7CA55FB0BBF81323D87062DB1F6D1C"
        assert extract_hash(magnet) == "dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c"

    def test_no_hash_returns_none(self):
        assert extract_hash("magnet:?dn=nothing") is None


class TestExtractName:
    def test_name_decoded(self):
        assert extract_name(VALID_MAGNET) == "ubuntu-22.04.iso"

    def test_name_url_encoded(self):
        magnet = "magnet:?xt=urn:btih:aabbcc&dn=hello+world"
        assert extract_name(magnet) == "hello world"

    def test_no_name_returns_none(self):
        assert extract_name("magnet:?xt=urn:btih:aabb") is None


class TestExtractTrackers:
    def test_single_tracker(self):
        trackers = extract_trackers(VALID_MAGNET)
        assert len(trackers) == 1
        assert "opentrackr" in trackers[0]

    def test_multiple_trackers(self):
        magnet = "magnet:?xt=urn:btih:aabb&tr=http://a.com&tr=http://b.com"
        assert len(extract_trackers(magnet)) == 2

    def test_no_trackers(self):
        assert extract_trackers("magnet:?xt=urn:btih:aabb") == []
