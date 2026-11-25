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
        for lv_min in (180, 900, 1500):
            sec = FlightSector(
                segments=[
                    _seg("TLV", hub, "2027-10-06T08:00:00", "2027-10-06T11:00:00", carrier=carrier, dest_cc=cc),
                    _seg(hub, "TPE", "2027-10-07T02:00:00", "2027-10-07T18:00:00", carrier=carrier, orig_cc=cc, lv_min=lv_min),
                ],
                total_duration_minutes=960 + lv_min,
            )
            strict_ok, watch_ok, _, _ = evaluate_sector(sec)
            assert not strict_ok
            assert not watch_ok


def test_short_layover_under_4h_blocks_self_transfer_and_allows_4h_plus() -> None:
    # Protected 3h layover -> IDEAL_SHORT_2_4H
    lv_ok = evaluate_layover("BKK", "BKK", "Bangkok", "TH", "2027-10-07T14:00:00", "2027-10-07T17:00:00", 180, False)
    assert lv_ok.strict_valid
    assert lv_ok.category == "IDEAL_SHORT_2_4H"

    # Self-transfer 3h and 3.9h layovers -> REJECTED (<4h self-transfer block)
    for mins in (120, 180, 234):
        lv_bad = evaluate_layover("BKK", "BKK", "Bangkok", "TH", "2027-10-07T14:00:00", "2027-10-07T17:54:00", mins, True)
        assert not lv_bad.strict_valid
        assert not lv_bad.watchlist_valid
        assert lv_bad.category == "REJECTED"

    # Self-transfer 4.0h and 5.5h layovers -> ACCEPTABLE_SHORT_4_6H
    lv_4h = evaluate_layover("PRG", "PRG", "Prague", "CZ", "2027-10-07T12:00:00", "2027-10-07T16:00:00", 240, True)
    assert lv_4h.strict_valid
    assert lv_4h.category == "ACCEPTABLE_SHORT_4_6H"
    assert lv_4h.is_self_transfer

    lv_55h = evaluate_layover("BKK", "BKK", "Bangkok", "TH", "2027-10-07T12:00:00", "2027-10-07T17:30:00", 330, True)
    assert lv_55h.strict_valid
    assert lv_55h.category == "ACCEPTABLE_SHORT_4_6H"
    assert lv_55h.is_self_transfer

    # Landside-restricted airport (KUL) still blocks self-transfer even on long layovers
    lv_kul = evaluate_layover("KUL", "KUL", "Kuala Lumpur", "MY", "2027-10-07T08:00:00", "2027-10-07T20:00:00", 720, True)
    assert not lv_kul.strict_valid
    assert not lv_kul.watchlist_valid
    assert lv_kul.category == "REJECTED"


def test_day_explore_8_10h_and_general_long_layovers_up_to_28h() -> None:
    # Daytime 9.0h in Vienna (fast transit, left luggage, daytime) -> DAY_EXPLORE_8_10H
    lv_day = evaluate_layover("VIE", "VIE", "Vienna", "AT", "2027-10-06T09:00:00", "2027-10-06T18:00:00", 540, True)
    assert lv_day.strict_valid
    assert lv_day.category == "DAY_EXPLORE_8_10H"
    assert lv_day.usable_city_hours is not None and lv_day.usable_city_hours >= 5.0

    # Middle-of-the-night 9.5h at Milan Malpensa -> NOT DAY_EXPLORE, accepted as LONG_LAYOVER
    lv_night = evaluate_layover("MXP", "MXP", "Milan", "IT", "2027-10-07T01:15:00", "2027-10-07T10:45:00", 570, True)
    assert lv_night.strict_valid
    assert lv_night.category == "LONG_LAYOVER"

    # 14.5h at Rome FCO and 28.0h at Hong Kong -> accepted as LONG_LAYOVER
    lv_fco = evaluate_layover("FCO", "FCO", "Rome", "IT", "2027-10-06T19:00:00", "2027-10-07T09:30:00", 870, True)
    assert lv_fco.strict_valid
    assert lv_fco.category == "LONG_LAYOVER"

    lv_28h = evaluate_layover("HKG", "HKG", "Hong Kong", "HK", "2027-10-06T10:00:00", "2027-10-07T14:00:00", 1680, True)
    assert lv_28h.strict_valid
    assert lv_28h.category == "LONG_LAYOVER"

    # Just over 28h (29.0h) -> WATCHLIST_NEAR_MISS; 31.0h -> REJECTED
    lv_29h = evaluate_layover("HKG", "HKG", "Hong Kong", "HK", "2027-10-06T10:00:00", "2027-10-07T15:00:00", 1740, True)
    assert not lv_29h.strict_valid
    assert lv_29h.watchlist_valid
    assert lv_29h.category == "WATCHLIST_NEAR_MISS"

    lv_31h = evaluate_layover("HKG", "HKG", "Hong Kong", "HK", "2027-10-06T10:00:00", "2027-10-07T17:00:00", 1860, True)
    assert not lv_31h.strict_valid
    assert not lv_31h.watchlist_valid
    assert lv_31h.category == "REJECTED"


def test_overnight_18_20h_preferred_hubs_and_other_hubs_long_layover() -> None:
    # 19h overnight in Bangkok -> OVERNIGHT_EXPLORE_18_20H
    lv_bkk = evaluate_layover("BKK", "BKK", "Bangkok", "TH", "2027-10-06T16:00:00", "2027-10-07T11:00:00", 1140, True)
    assert lv_bkk.strict_valid
    assert lv_bkk.category == "OVERNIGHT_EXPLORE_18_20H"

    # 19h overnight in Warsaw -> OVERNIGHT_EXPLORE_18_20H
    lv_waw = evaluate_layover("WAW", "WAW", "Warsaw", "PL", "2027-10-06T17:00:00", "2027-10-07T12:00:00", 1140, True)
    assert lv_waw.strict_valid
    assert lv_waw.category == "OVERNIGHT_EXPLORE_18_20H"

    # 19h overnight in Paris CDG -> accepted as general LONG_LAYOVER (not East EU/HK/BKK overnight tier)
    lv_cdg = evaluate_layover("CDG", "CDG", "Paris", "FR", "2027-10-06T17:00:00", "2027-10-07T12:00:00", 1140, False)
    assert lv_cdg.strict_valid
    assert lv_cdg.category == "LONG_LAYOVER"


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

    # Itinerary 3: 14h FCO self-transfer + 24h BKK self-transfer at $1200 -> STRICT_ACCEPTABLE with Long Layover badge
    long_raw = RawItinerary(
        source_provider="test",
        price_usd=1200,
        pnr_count=4,
        ticket_structure="self_transfer_connection",
        outbound=FlightSector(
            segments=[
                _seg("TLV", "FCO", "2027-10-06T08:00:00", "2027-10-06T11:00:00", "AZ", "807"),
                _seg("FCO", "TPE", "2027-10-07T01:00:00", "2027-10-07T19:00:00", "CI", "76", lv_min=840, recheck=True),
            ],
            total_duration_minutes=2100,
        ),
        inbound=FlightSector(
            segments=[
                _seg("TPE", "BKK", "2027-10-23T09:00:00", "2027-10-23T12:00:00", "TG", "633"),
                _seg("BKK", "TLV", "2027-10-24T12:00:00", "2027-10-24T19:00:00", "LY", "82", lv_min=1440, recheck=True),
            ],
            total_duration_minutes=2040,
        ),
    )

    evaluated = evaluate_itineraries([ideal_raw, good_5h_raw, long_raw], previous_prices={ideal_raw.route_fingerprint(): 1920})
    assert len(evaluated) == 3
    by_price = {e.price_usd: e for e in evaluated}
    assert by_price[1800].is_open_jaw_taiwan is True
    assert by_price[1800].price_delta_usd == -120
    assert "Good-Price 4–6h" in by_price[1550].badges
    assert by_price[1200].tier == "STRICT_ACCEPTABLE"
    assert any(b.startswith("Long Layover 24h") for b in by_price[1200].badges)
    assert "Self-Transfer (≥4h)" in by_price[1200].badges
    assert evaluated[0].price_usd == 1200
