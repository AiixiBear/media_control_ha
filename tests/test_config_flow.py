"""Regression tests for the config flow."""

from custom_components.media_control_ha.const import DOMAIN


def test_domain_matches_manifest() -> None:
    """The integration domain should match the manifest entry."""
    assert DOMAIN == "media_control_ha"
