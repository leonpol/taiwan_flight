"""Unit tests for Kiwi GraphQL filter construction and Google Flights SOCS cookie handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from config import DEFAULT_CONFIG
from providers.google_flights import (
    DEFAULT_GOOGLE_SOCS_COOKIE,
    GOOGLE_FLIGHTS_URL,
    _SocsFetchIntegration,
    _parse_gf_oneway_html,
)
from providers.kiwi_graphql import _build_kiwi_filter


def test_kiwi_filter_omits_exclude_when_stopover_countries_present() -> None:
    filt = _build_kiwi_filter(
        {"allowReturnFromDifferentCity": True},
        {"stopoverCountries": ["TH", "HK", "TR", "AE"], "stopoverTime": {"start": 2, "end": 28}},
        DEFAULT_CONFIG,
    )
    assert "excludeStopoverCountries" not in filt
    assert filt["stopoverCountries"] == ["TH", "HK"]
    assert filt["stopoverTime"] == {"start": 2, "end": 28}


def test_kiwi_filter_sets_exclude_when_no_stopover_countries() -> None:
    filt = _build_kiwi_filter(
        {"allowReturnFromDifferentCity": True},
        {"maxStopsCount": 1, "stopoverTime": {"start": 2, "end": 28}},
        DEFAULT_CONFIG,
    )
    assert "stopoverCountries" not in filt
    assert set(filt["excludeStopoverCountries"]) == set(DEFAULT_CONFIG.excluded_countries)


def test_google_flights_socs_integration_attaches_cookie() -> None:
    mock_resp = MagicMock()
    mock_resp.text = "<html>ok</html>"
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    fake_query = MagicMock()
    fake_query.params.return_value = {"tfs": "abc", "hl": "en", "curr": "USD"}

    with patch("providers.google_flights.Client", return_value=mock_client) as mock_cls:
        fetcher = _SocsFetchIntegration(timeout=15)
        html = fetcher.fetch_html(fake_query)

    assert html == "<html>ok</html>"
    mock_cls.assert_called_once_with(
        impersonate="chrome_145",
        impersonate_os="macos",
        referer=True,
        cookie_store=True,
        cookies={"SOCS": DEFAULT_GOOGLE_SOCS_COOKIE},
        timeout=15,
    )
    mock_client.get.assert_called_once_with(
        GOOGLE_FLIGHTS_URL,
        params={"tfs": "abc", "hl": "en", "curr": "USD"},
    )


def test_google_flights_parser_detects_consent_wall() -> None:
    consent_html = '<html><body><form action="https://consent.google.com/save"></form></body></html>'
    secs, err = _parse_gf_oneway_html(consent_html, "https://www.google.com/travel/flights", True)
    assert secs == []
    assert err == "google_consent_wall"
