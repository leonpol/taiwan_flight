"""Strict itinerary rule engine & smart deal scorer (Requirements 2-8 + A3)."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from airports import (
    AIRPORT_CITY_PROFILES,
    OVERNIGHT_18_20H_AIRPORTS,
    TAIWAN_AIRPORTS,
    is_blocked_station,
    is_overnight_18_20h_hub,
)
from config import DEFAULT_CONFIG, SearchConfig
from models import (
    EvaluatedItinerary,
    FlightSector,
    LayoverEvaluation,
    RawItinerary,
)

# Carriers domiciled in Turkey or Persian Gulf states (extra defense-in-depth for Rule 4)
BLOCKED_CARRIERS: frozenset[str] = frozenset(
    {
        "TK", "PC", "VF", "XQ",        # Turkish Airlines, Pegasus, AJet, SunExpress
        "EK", "EY", "FZ", "G9", "5W",  # Emirates, Etihad, flydubai, Air Arabia, Wizz Abu Dhabi
        "QR", "GF", "WY", "OV", "KU",  # Qatar, Gulf Air, Oman Air, SalamAir, Kuwait Airways
        "SV", "XY", "F3",              # Saudia, flynas, flyadeal
        "IR", "W5", "IA",              # Iran Air, Mahan, Iraqi Airways
    }
)


def _parse_local(ts: str) -> datetime:
    return datetime.fromisoformat(ts[:19])


def _waking_overlap_hours(start_dt: datetime, end_dt: datetime) -> float:
    """Hours between start_dt and end_dt falling inside 07:30-23:00 local time."""
    if end_dt <= start_dt:
        return 0.0
    total_sec = 0.0
    cur_day = start_dt.date()
    last_day = end_dt.date()
    while cur_day <= last_day:
        w_start = datetime.combine(cur_day, time(7, 30))
        w_end = datetime.combine(cur_day, time(23, 0))
        ov_start = max(start_dt, w_start)
        ov_end = min(end_dt, w_end)
        if ov_end > ov_start:
            total_sec += (ov_end - ov_start).total_seconds()
        cur_day += timedelta(days=1)
    return total_sec / 3600.0


def _spans_overnight_sleep(arr_dt: datetime, dep_dt: datetime) -> bool:
    """Return True if [arr_dt, dep_dt] crosses to the next day and covers 01:30-05:30."""
    if dep_dt.date() <= arr_dt.date():
        return False
    cur_day = arr_dt.date()
    while cur_day <= dep_dt.date():
        sleep_start = datetime.combine(cur_day, time(1, 30))
        sleep_end = datetime.combine(cur_day, time(5, 30))
        if arr_dt <= sleep_start and dep_dt >= sleep_end:
            return True
        cur_day += timedelta(days=1)
    return False


def evaluate_layover(
    arr_airport: str,
    dep_airport: str,
    city: str,
    country: str,
    arr_local: str,
    dep_local: str,
    duration_minutes: int,
    is_baggage_recheck: bool,
    cfg: SearchConfig = DEFAULT_CONFIG,
) -> LayoverEvaluation:
    """Evaluate a single layover against Rules 4, 5, 6, 7, and A3."""
    arr_code = arr_airport.upper().strip()
    dep_code = dep_airport.upper().strip()
    cc = (country or "").upper().strip()
    hours = round(duration_minutes / 60.0, 2)
    same_airport = arr_code == dep_code
    is_self_transfer = bool(is_baggage_recheck or not same_airport)

    # Rule 4: Persian Gulf / Turkey block
    if is_blocked_station(arr_code, cc) or is_blocked_station(dep_code, cc):
        return LayoverEvaluation(
            arrival_airport=arr_code,
            departure_airport=dep_code,
            city=city,
            country=cc,
            arrival_local=arr_local,
            departure_local=dep_local,
            duration_hours=hours,
            is_self_transfer=is_self_transfer,
            category="REJECTED",
            strict_valid=False,
            watchlist_valid=False,
            reason=f"Blocked layover region ({arr_code}/{cc} — Persian Gulf/Turkey prohibited)",
        )

    arr_dt = _parse_local(arr_local)
    dep_dt = _parse_local(dep_local)

    # Profile lookup for city exploration
    profile = AIRPORT_CITY_PROFILES.get(arr_code)
    if profile and not profile.can_enter_landside_from_tlv and is_self_transfer:
        return LayoverEvaluation(
            arrival_airport=arr_code,
            departure_airport=dep_code,
            city=city or profile.city,
            country=cc or profile.country,
            arrival_local=arr_local,
            departure_local=dep_local,
            duration_hours=hours,
            is_self_transfer=is_self_transfer,
            category="REJECTED",
            strict_valid=False,
            watchlist_valid=False,
            reason=f"Self-transfer landside entry restricted at {arr_code}: {profile.notes}",
        )

    # Rule A3: Block self-transfers under 4h (high missed-connection risk)
    if is_self_transfer and hours < cfg.min_self_transfer_h:
        return LayoverEvaluation(
            arrival_airport=arr_code,
            departure_airport=dep_code,
            city=city or (profile.city if profile else ""),
            country=cc or (profile.country if profile else ""),
            arrival_local=arr_local,
            departure_local=dep_local,
            duration_hours=hours,
            is_self_transfer=True,
            category="REJECTED",
            strict_valid=False,
            watchlist_valid=False,
            reason=(
                f"Self-transfer not allowed on <{cfg.min_self_transfer_h:.0f}h layover "
                f"({hours:.1f}h at {arr_code})"
            ),
        )

    # 1. Rule 5 (Preferred): 2.0h - 4.0h short layover (Single-PNR only, same airport)
    if not is_self_transfer and cfg.ideal_short_min_h <= hours <= cfg.ideal_short_max_h:
        return LayoverEvaluation(
            arrival_airport=arr_code,
            departure_airport=dep_code,
            city=city,
            country=cc,
            arrival_local=arr_local,
            departure_local=dep_local,
            duration_hours=hours,
            is_self_transfer=False,
            category="IDEAL_SHORT_2_4H",
            strict_valid=True,
            watchlist_valid=True,
            luggage_note="Bags checked through automatically",
            reason=f"Ideal {hours:.1f}h connection at {arr_code}",
        )

    # 2. Rule 5 (Acceptable): 4.0h - 6.0h (protected or >=4h self-transfer)
    if (cfg.ideal_short_max_h < hours <= cfg.acceptable_short_max_h) or (
        is_self_transfer and cfg.min_self_transfer_h <= hours <= cfg.acceptable_short_max_h
    ):
        if is_self_transfer:
            luggage_msg = (
                f"Airport change ({arr_code}→{dep_code}): collect & re-check bags"
                if not same_airport
                else f"Self-transfer: collect & re-check bags at {arr_code}"
            )
            reason_msg = f"Acceptable {hours:.1f}h self-transfer layover at {arr_code}"
        else:
            luggage_msg = "Bags checked through automatically"
            reason_msg = f"Acceptable {hours:.1f}h layover at {arr_code} (good-price tier)"
        return LayoverEvaluation(
            arrival_airport=arr_code,
            departure_airport=dep_code,
            city=city,
            country=cc,
            arrival_local=arr_local,
            departure_local=dep_local,
            duration_hours=hours,
            is_self_transfer=is_self_transfer,
            category="ACCEPTABLE_SHORT_4_6H",
            strict_valid=True,
            watchlist_valid=True,
            luggage_note=luggage_msg,
            reason=reason_msg,
        )

    # 3. Rule 7: 8.0h - 10.0h quick city explore (Leave luggage + quick transit + 5-8h city)
    if (
        cfg.day_explore_min_h <= hours <= cfg.day_explore_max_h
        and same_airport
        and profile
        and profile.can_enter_landside_from_tlv
        and profile.has_left_luggage
        and profile.transit_minutes_one_way <= 38
    ):
        exit_h = 0.9 if is_self_transfer else 0.6
        return_h = 1.6 if is_self_transfer else 1.35
        transit_h = profile.transit_minutes_one_way / 60.0
        usable_city_h = round(hours - exit_h - return_h - 2.0 * transit_h, 1)
        city_start = arr_dt + timedelta(hours=exit_h + transit_h)
        city_end = dep_dt - timedelta(hours=return_h + transit_h)
        waking_h = round(_waking_overlap_hours(city_start, city_end), 1)

        if usable_city_h >= 4.8 and waking_h >= 4.5:
            luggage_msg = (
                f"Store bags at {arr_code} ({profile.notes}) & re-check in"
                if is_self_transfer
                else f"Checked bags transferred; store carry-on at {arr_code} ({profile.notes})"
            )
            return LayoverEvaluation(
                arrival_airport=arr_code,
                departure_airport=dep_code,
                city=profile.city,
                country=profile.country,
                arrival_local=arr_local,
                departure_local=dep_local,
                duration_hours=hours,
                is_self_transfer=is_self_transfer,
                category="DAY_EXPLORE_8_10H",
                strict_valid=True,
                watchlist_valid=True,
                usable_city_hours=usable_city_h,
                transit_summary=f"{profile.transit_minutes_one_way}m via {profile.transit_mode}",
                luggage_note=luggage_msg,
                reason=(
                    f"{hours:.1f}h layover in {profile.city}: ~{usable_city_h:.1f}h in city "
                    f"({city_start.strftime('%H:%M')}–{city_end.strftime('%H:%M')}, {profile.transit_minutes_one_way}m transit)"
                ),
            )

    # 4. Rule 6: 18.0h - 20.0h overnight explore + sleep in East Europe / HK / Bangkok
    if (
        cfg.overnight_explore_min_h <= hours <= cfg.overnight_explore_max_h
        and is_overnight_18_20h_hub(arr_code, dep_code)
        and _spans_overnight_sleep(arr_dt, dep_dt)
    ):
        hub_city = OVERNIGHT_18_20H_AIRPORTS.get(arr_code, city)
        usable_explore = round(max(4.0, hours - 8.0 - 3.2), 1)
        transit_note = (
            f"{profile.transit_minutes_one_way}m via {profile.transit_mode}"
            if profile
            else f"City transfer in {hub_city}"
        )
        return LayoverEvaluation(
            arrival_airport=arr_code,
            departure_airport=dep_code,
            city=hub_city,
            country=cc,
            arrival_local=arr_local,
            departure_local=dep_local,
            duration_hours=hours,
            is_self_transfer=is_self_transfer,
            category="OVERNIGHT_EXPLORE_18_20H",
            strict_valid=True,
            watchlist_valid=True,
            usable_city_hours=usable_explore,
            transit_summary=transit_note,
            luggage_note="Overnight hotel stay — take bags or use hotel/airport storage",
            reason=(
                f"{hours:.1f}h overnight in {hub_city} (lands {arr_dt.strftime('%b %d %H:%M')}, "
                f"flies next day {dep_dt.strftime('%b %d %H:%M')})"
            ),
        )

    # 5. General long layover up to max_layover_h (28h) at any non-blocked hub
    if cfg.acceptable_short_max_h < hours <= cfg.max_layover_h:
        display_city = (
            (profile.city if profile else "")
            or OVERNIGHT_18_20H_AIRPORTS.get(arr_code, "")
            or city
            or arr_code
        )
        display_cc = cc or (profile.country if profile else "")
        transit_note = (
            f"{profile.transit_minutes_one_way}m via {profile.transit_mode}"
            if profile
            else ""
        )
        spans_night = _spans_overnight_sleep(arr_dt, dep_dt)
        if not same_airport:
            luggage_msg = f"Airport change ({arr_code}→{dep_code}): collect & re-check bags"
        elif is_self_transfer:
            luggage_msg = f"Self-transfer: collect & re-check bags at {arr_code}"
        elif spans_night:
            luggage_msg = "Overnight layover — confirm whether airline holds checked bags overnight"
        else:
            luggage_msg = "Checked bags transferred automatically"

        if spans_night:
            reason_msg = (
                f"{hours:.1f}h overnight layover in {display_city} "
                f"(lands {arr_dt.strftime('%b %d %H:%M')}, flies {dep_dt.strftime('%b %d %H:%M')})"
            )
        else:
            reason_msg = f"{hours:.1f}h long layover in {display_city} ({arr_code})"

        return LayoverEvaluation(
            arrival_airport=arr_code,
            departure_airport=dep_code,
            city=display_city,
            country=display_cc,
            arrival_local=arr_local,
            departure_local=dep_local,
            duration_hours=hours,
            is_self_transfer=is_self_transfer,
            category="LONG_LAYOVER",
            strict_valid=True,
            watchlist_valid=True,
            transit_summary=transit_note,
            luggage_note=luggage_msg,
            reason=reason_msg,
        )

    # 6. Secondary Watchlist check (near-misses just outside 2h..max_layover_h)
    # Never allow short self-transfers (<4h already rejected above)!
    if not is_self_transfer and 1.5 <= hours < cfg.ideal_short_min_h:
        return LayoverEvaluation(
            arrival_airport=arr_code,
            departure_airport=dep_code,
            city=city,
            country=cc,
            arrival_local=arr_local,
            departure_local=dep_local,
            duration_hours=hours,
            is_self_transfer=False,
            category="WATCHLIST_NEAR_MISS",
            strict_valid=False,
            watchlist_valid=True,
            luggage_note="Bags checked through",
            reason=f"Near-miss {hours:.1f}h single-ticket layover at {arr_code} (slightly under 2h)",
        )

    if cfg.max_layover_h < hours <= cfg.max_layover_h + cfg.watchlist_layover_slack_h:
        return LayoverEvaluation(
            arrival_airport=arr_code,
            departure_airport=dep_code,
            city=city or (profile.city if profile else arr_code),
            country=cc or (profile.country if profile else ""),
            arrival_local=arr_local,
            departure_local=dep_local,
            duration_hours=hours,
            is_self_transfer=is_self_transfer,
            category="WATCHLIST_NEAR_MISS",
            strict_valid=False,
            watchlist_valid=True,
            reason=f"Near-miss {hours:.1f}h layover at {arr_code} (just over {cfg.max_layover_h:.0f}h limit)",
        )

    return LayoverEvaluation(
        arrival_airport=arr_code,
        departure_airport=dep_code,
        city=city,
        country=cc,
        arrival_local=arr_local,
        departure_local=dep_local,
        duration_hours=hours,
        is_self_transfer=is_self_transfer,
        category="REJECTED",
        strict_valid=False,
        watchlist_valid=False,
        reason=f"{hours:.1f}h layover at {arr_code} outside allowed range (2–{cfg.max_layover_h:.0f}h)",
    )


def evaluate_sector(
    sector: FlightSector,
    cfg: SearchConfig = DEFAULT_CONFIG,
) -> tuple[bool, bool, list[LayoverEvaluation], str]:
    """Validate all segments and layovers of one sector (outbound or inbound).

    Returns (strict_ok, watchlist_ok, layover_evals, rejection_reason).
    """
    if not sector.segments:
        return False, False, [], "Empty sector"

    # Reject excessive multi-stop itineraries (>2 stops per direction)
    if len(sector.segments) > 3:
        return False, False, [], f"Too many stops ({len(sector.segments) - 1})"

    for seg in sector.segments:
        if seg.carrier_code.upper() in BLOCKED_CARRIERS or seg.operating_carrier.upper() in BLOCKED_CARRIERS:
            return False, False, [], f"Blocked carrier {seg.carrier_code}"
        if is_blocked_station(seg.origin_code, seg.origin_country) or is_blocked_station(seg.dest_code, seg.dest_country):
            return False, False, [], f"Blocked airport/country on segment {seg.origin_code}->{seg.dest_code}"

    layovers: list[LayoverEvaluation] = []
    for i in range(1, len(sector.segments)):
        prev_seg = sector.segments[i - 1]
        curr_seg = sector.segments[i]
        if curr_seg.layover_before_minutes is not None:
            dur_min = curr_seg.layover_before_minutes
        else:
            dur_min = int((_parse_local(curr_seg.departure_local) - _parse_local(prev_seg.arrival_local)).total_seconds() // 60)

        ev = evaluate_layover(
            arr_airport=prev_seg.dest_code,
            dep_airport=curr_seg.origin_code,
            city=prev_seg.dest_city,
            country=prev_seg.dest_country,
            arr_local=prev_seg.arrival_local,
            dep_local=curr_seg.departure_local,
            duration_minutes=dur_min,
            is_baggage_recheck=curr_seg.is_baggage_recheck_before,
            cfg=cfg,
        )
        layovers.append(ev)

    # Avoid two long explore layovers inside a single direction
    long_count = sum(1 for lv in layovers if lv.duration_hours >= 7.5)
    if long_count > 1:
        return False, False, layovers, "Multiple long layovers in one direction"

    strict_ok = all(lv.strict_valid for lv in layovers)
    watchlist_ok = all(lv.watchlist_valid for lv in layovers)
    reason = ""
    if not watchlist_ok:
        bad = next((lv.reason for lv in layovers if not lv.watchlist_valid), "Invalid layover")
        reason = bad
    return strict_ok, watchlist_ok, layovers, reason


def evaluate_itineraries(
    raw_list: list[RawItinerary],
    previous_prices: dict[str, int] | None = None,
    cfg: SearchConfig = DEFAULT_CONFIG,
) -> list[EvaluatedItinerary]:
    """Deduplicate, validate, classify, and rank all raw itineraries."""
    previous_prices = previous_prices or {}

    # Deduplicate by fingerprint keeping lowest price
    dedup: dict[str, RawItinerary] = {}
    for raw in raw_list:
        fp = raw.route_fingerprint()
        if fp not in dedup or raw.price_usd < dedup[fp].price_usd:
            dedup[fp] = raw

    preliminary: list[EvaluatedItinerary] = []
    for fp, raw in dedup.items():
        # Verify origin/destination & date windows (Rules 2, 3, 8)
        if raw.outbound.origin_code != cfg.origin_airport:
            continue
        if raw.outbound.dest_code not in TAIWAN_AIRPORTS:
            continue
        if raw.inbound.origin_code not in TAIWAN_AIRPORTS:
            continue
        if raw.inbound.dest_code != cfg.origin_airport:
            continue

        out_dep_date = _parse_local(raw.outbound.departure_local).date()
        in_dep_date = _parse_local(raw.inbound.departure_local).date()
        in_arr_date = _parse_local(raw.inbound.arrival_local).date()

        if not (cfg.outbound_start <= out_dep_date <= cfg.outbound_end):
            continue
        if not (cfg.inbound_start <= in_dep_date <= cfg.inbound_end):
            continue

        out_strict, out_watch, out_layovers, _ = evaluate_sector(raw.outbound, cfg)
        if not out_watch:
            continue
        in_strict, in_watch, in_layovers, _ = evaluate_sector(raw.inbound, cfg)
        if not in_watch:
            continue

        all_layovers = out_layovers + in_layovers
        both_strict = out_strict and in_strict

        has_4_6h = any(lv.category == "ACCEPTABLE_SHORT_4_6H" for lv in all_layovers)
        has_day_explore = any(lv.category == "DAY_EXPLORE_8_10H" for lv in all_layovers)
        has_overnight = any(lv.category == "OVERNIGHT_EXPLORE_18_20H" for lv in all_layovers)
        has_long_layover = any(lv.category == "LONG_LAYOVER" for lv in all_layovers)
        has_self_transfer = any(lv.is_self_transfer for lv in all_layovers)
        is_open_jaw = raw.outbound.dest_code != raw.inbound.origin_code

        if not both_strict:
            tier = "WATCHLIST"
        elif not has_4_6h and not has_day_explore and not has_overnight and not has_long_layover:
            tier = "STRICT_IDEAL"
        else:
            tier = "STRICT_ACCEPTABLE"

        badges: list[str] = []
        if tier == "STRICT_IDEAL":
            badges.append("Ideal 2–4h Layovers")
        if has_4_6h:
            badges.append("4–6h Layover")
        if has_day_explore:
            cities = sorted({lv.city for lv in all_layovers if lv.category == "DAY_EXPLORE_8_10H"})
            badges.append(f"8–10h City Explore ({', '.join(cities)})")
        if has_overnight:
            cities = sorted({lv.city for lv in all_layovers if lv.category == "OVERNIGHT_EXPLORE_18_20H"})
            badges.append(f"18–20h Overnight ({', '.join(cities)})")
        if has_long_layover:
            long_lvs = [lv for lv in all_layovers if lv.category == "LONG_LAYOVER"]
            max_lh = max(lv.duration_hours for lv in long_lvs)
            cities = sorted({lv.city or lv.arrival_airport for lv in long_lvs})
            badges.append(f"Long Layover {max_lh:.0f}h ({', '.join(cities)})")
        if is_open_jaw:
            badges.append(f"Open-Jaw ({raw.outbound.dest_code} / {raw.inbound.origin_code})")
        if raw.pnr_count == 1 and raw.ticket_structure == "single_ticket":
            badges.append("Single Airline Ticket")
        elif has_self_transfer:
            badges.append("Self-Transfer (≥4h)")
        elif raw.ticket_structure == "split_outbound_inbound":
            badges.append("2 Separate One-Ways")

        prev_price = previous_prices.get(fp)
        delta = (raw.price_usd - prev_price) if prev_price is not None else None

        preliminary.append(
            EvaluatedItinerary(
                fingerprint=fp,
                source_provider=raw.source_provider,
                price_usd=raw.price_usd,
                pnr_count=raw.pnr_count,
                ticket_structure=raw.ticket_structure,
                is_open_jaw_taiwan=is_open_jaw,
                taiwan_arrival_airport=raw.outbound.dest_code,
                taiwan_departure_airport=raw.inbound.origin_code,
                outbound_date=out_dep_date.isoformat(),
                inbound_date=in_dep_date.isoformat(),
                inbound_arrival_tlv_date=in_arr_date.isoformat(),
                outbound=raw.outbound,
                inbound=raw.inbound,
                outbound_layovers=out_layovers,
                inbound_layovers=in_layovers,
                tier=tier,
                score=float(raw.price_usd),
                badges=badges,
                booking_url=raw.booking_url,
                inbound_booking_url=raw.inbound_booking_url,
                previous_price_usd=prev_price,
                price_delta_usd=delta,
            )
        )

    # Pass 2: Price-context scoring ("Preferably 2-4h. If the price is good 6h is acceptable.")
    ideal_prices = [it.price_usd for it in preliminary if it.tier == "STRICT_IDEAL"]
    best_ideal_price = min(ideal_prices) if ideal_prices else None

    for it in preliminary:
        all_lvs = it.outbound_layovers + it.inbound_layovers
        penalty = 0.0
        notes: list[str] = []

        # Extra stop penalty (1 stop each way preferred over 2 stops)
        extra_stops = max(0, it.outbound.stops_count - 1) + max(0, it.inbound.stops_count - 1)
        penalty += extra_stops * 95.0

        has_4_6h = any(lv.category == "ACCEPTABLE_SHORT_4_6H" for lv in all_lvs)
        if has_4_6h:
            if best_ideal_price is not None:
                savings = best_ideal_price - it.price_usd
                if savings >= cfg.good_price_savings_vs_ideal_usd or it.price_usd <= cfg.good_price_absolute_usd:
                    penalty += 45.0
                    notes.append(f"Saves ${savings} vs best 2–4h flight (${best_ideal_price})")
                    if "Good-Price 4–6h" not in it.badges:
                        it.badges.append("Good-Price 4–6h")
                else:
                    # 4-6h layover is NOT cheaper enough vs 2-4h ideal option
                    penalty += 220.0
                    if savings > 0:
                        notes.append(f"Only ${savings} cheaper than best 2–4h option (${best_ideal_price})")
                    else:
                        notes.append(f"${-savings} more expensive than best 2–4h option (${best_ideal_price})")
            else:
                penalty += 60.0

        for lv in all_lvs:
            if lv.category == "ACCEPTABLE_SHORT_4_6H" and lv.is_self_transfer:
                penalty += 35.0
                notes.append(lv.reason)
            elif lv.category == "DAY_EXPLORE_8_10H":
                penalty += 55.0 + (35.0 if lv.is_self_transfer else 0.0)
                notes.append(lv.reason)
            elif lv.category == "OVERNIGHT_EXPLORE_18_20H":
                penalty += 70.0 + (30.0 if lv.is_self_transfer else 0.0)
                notes.append(lv.reason)
            elif lv.category == "LONG_LAYOVER":
                penalty += 85.0 + min(65.0, max(0.0, lv.duration_hours - 6.0) * 3.0) + (35.0 if lv.is_self_transfer else 0.0)
                notes.append(lv.reason)
            elif lv.category == "WATCHLIST_NEAR_MISS":
                penalty += 400.0
                notes.append(lv.reason)

        if not notes:
            notes.append(
                "; ".join(lv.reason for lv in all_lvs)
                if all_lvs
                else "Direct flights"
            )

        it.score = round(it.price_usd + penalty, 1)
        it.summary_note = " | ".join(notes)

    # Prune unbookable full-fare IATA Y-class placeholders (e.g. >$5,000 economy) when normal fares exist
    strict_prices = [it.price_usd for it in preliminary if it.tier != "WATCHLIST"]
    if strict_prices:
        min_strict = min(strict_prices)
        outlier_cap = max(4500, int(min_strict * 2.2))
        preliminary = [it for it in preliminary if it.price_usd <= outlier_cap]

    preliminary.sort(key=lambda x: (0 if x.tier != "WATCHLIST" else 1, x.score, x.price_usd))
    return preliminary
