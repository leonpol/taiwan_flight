"""Unit tests verifying all 9 user flight rules and self-transfer policies."""

from __future__ import annotations

from evaluator import evaluate_itineraries, evaluate_layover, evaluate_sector
from models import FlightSector, FlightSegment, RawItinerary


def _seg(
    orig: str,
    dest: str,
    dep: str,
    arr: str,
    carrier: str = "BR",
    fnum: str = "101",
    orig_cc: str = "",
    dest_cc: str = "",
    lv_min: int | None = None,
    recheck: bool = False,
) -> FlightSegment:
    return FlightSegment(
        carrier_code=carrier,
        carrier_name=carrier,
        flight_number=fnum,
        operating_carrier=carrier,
        origin_code=orig,
        origin_name=orig,
        origin_city=orig,
        origin_country=orig_cc,
        dest_code=dest,
        dest_name=dest,
        dest_city=dest,
        dest_country=dest_cc,
        departure_local=dep,
        arrival_local=arr,
        duration_minutes=300,
        layover_before_minutes=lv_min,
        is_baggage_recheck_before=recheck,
    )


def test_blocks_persian_gulf_and_turkey() -> None:
    for hub, cc, carrier in [("IST", "TR", "TK"), ("DXB", "AE", "EK"), ("DOH", "QA", "QR"), ("SHJ", "AE", "G9")]:
        sec = FlightSector(
            segments=[
                _seg("TLV", hub, "2027-10-06T08:00:00", "2027-10-06T11:00:00", carrier=carrier, dest_cc=cc),
                _seg(hub, "TPE", "2027-10-06T14:00:00", "2027-10-07T06:00:00", carrier=carrier, orig_cc=cc, lv_min=180),
            ],
            total_duration_minutes=960,
        )
        strict_ok, watch_ok, _, _ = evaluate_sector(sec)
        assert not strict_ok
        assert not watch_ok


def test_short_layover_2_4h_requires_single_ticket() -> None:
    # Protected 3h layover -> IDEAL_SHORT_2_4H
    lv_ok = evaluate_layover("BKK", "BKK", "Bangkok", "TH", "2027-10-07T14:00:00", "2027-10-07T17:00:00", 180, False)
    assert lv_ok.strict_valid
    assert lv_ok.category == "IDEAL_SHORT_2_4H"

    # Self-transfer 3h layover -> REJECTED (Rule A3)
    lv_bad = evaluate_layover("BKK", "BKK", "Bangkok", "TH", "2027-10-07T14:00:00", "2027-10-07T17:00:00", 180, True)
    assert not lv_bad.strict_valid
    assert not lv_bad.watchlist_valid
    assert lv_bad.category == "REJECTED"


def test_day_explore_8_10h_checks_luggage_transit_and_daytime() -> None:
    # Daytime 9.0h in Vienna (arrives 09:00, departs 18:00, 16m CAT train, left-luggage available, self-transfer OK)
    lv_day = evaluate_layover("VIE", "VIE", "Vienna", "AT", "2027-10-06T09:00:00", "2027-10-06T18:00:00", 540, True)
    assert lv_day.strict_valid
    assert lv_day.category == "DAY_EXPLORE_8_10H"
    assert lv_day.usable_city_hours is not None and lv_day.usable_city_hours >= 5.0

    # Middle-of-the-night 9.5h at Milan Malpensa (arrives 01:15 AM, 51m train) -> REJECTED
    lv_night = evaluate_layover("MXP", "MXP", "Milan", "IT", "2027-10-07T01:15:00", "2027-10-07T10:45:00", 570, True)
    assert not lv_night.strict_valid
    assert not lv_night.watchlist_valid


def test_overnight_18_20h_allowed_only_in_east_eu_hk_bangkok() -> None:
    # 19h overnight in Bangkok (arrives 16:00, flies next day 11:00) -> STRICT VALID
    lv_bkk = evaluate_layover("BKK", "BKK", "Bangkok", "TH", "2027-10-06T16:00:00", "2027-10-07T11:00:00", 1140, True)
    assert lv_bkk.strict_valid
    assert lv_bkk.category == "OVERNIGHT_EXPLORE_18_20H"

    # 19h overnight in Warsaw -> STRICT VALID
    lv_waw = evaluate_layover("WAW", "WAW", "Warsaw", "PL", "2027-10-06T17:00:00", "2027-10-07T12:00:00", 1140, True)
    assert lv_waw.strict_valid
    assert lv_waw.category == "OVERNIGHT_EXPLORE_18_20H"

    # 19h overnight in Paris CDG (Western Europe, not East EU/HK/BKK) -> REJECTED
    lv_cdg = evaluate_layover("CDG", "CDG", "Paris", "FR", "2027-10-06T17:00:00", "2027-10-07T12:00:00", 1140, False)
    assert not lv_cdg.strict_valid
    assert not lv_cdg.watchlist_valid


def test_open_jaw_taiwan_airports_and_good_price_4_6h_comparison() -> None:
    # Itinerary 1: Ideal 3h layover, $1800, open-jaw TPE -> KHH
    ideal_raw = RawItinerary(
        source_provider="test",
        price_usd=1800,
        pnr_count=1,
        ticket_structure="single_ticket",
        outbound=FlightSector(
            segments=[
                _seg("TLV", "HKG", "2027-10-07T22:00:00", "2027-10-08T14:00:00", "CX", "676"),
                _seg("HKG", "TPE", "2027-10-08T17:00:00", "2027-10-08T18:55:00", "CX", "472", lv_min=180),
            ],
            total_duration_minutes=955,
        ),
        inbound=FlightSector(
            segments=[
                _seg("KHH", "HKG", "2027-10-23T14:00:00", "2027-10-23T15:35:00", "CX", "431"),
                _seg("HKG", "TLV", "2027-10-23T18:35:00", "2027-10-24T01:20:00", "CX", "675", lv_min=180),
            ],
            total_duration_minutes=980,
        ),
    )

    # Itinerary 2: 5.5h layover saving $250 ($1550) -> Good-Price 4-6h badge
    good_5h_raw = RawItinerary(
        source_provider="test",
        price_usd=1550,
        pnr_count=1,
        ticket_structure="single_ticket",
        outbound=FlightSector(
            segments=[
                _seg("TLV", "BKK", "2027-10-06T22:00:00", "2027-10-07T13:30:00", "LY", "81"),
                _seg("BKK", "TPE", "2027-10-07T19:00:00", "2027-10-07T23:45:00", "CI", "836", lv_min=330),
            ],
            total_duration_minutes=1185,
        ),
        inbound=ideal_raw.inbound,
    )

    evaluated = evaluate_itineraries([ideal_raw, good_5h_raw], previous_prices={ideal_raw.route_fingerprint(): 1920})
    assert len(evaluated) == 2
    by_price = {e.price_usd: e for e in evaluated}
    assert by_price[1800].is_open_jaw_taiwan is True
    assert by_price[1800].price_delta_usd == -120
    assert "Good-Price 4–6h" in by_price[1550].badges
