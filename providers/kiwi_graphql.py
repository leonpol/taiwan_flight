"""Live flight fetcher using Kiwi / Skypicker's Umbrella GraphQL API (100% real fares)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from typing import Any

import requests

from airports import OVERNIGHT_ELIGIBLE_COUNTRIES_KIWI
from config import DEFAULT_CONFIG, SearchConfig
from evaluator import evaluate_sector
from models import FlightSector, FlightSegment, RawItinerary

KIWI_GRAPHQL_URL = "https://api.skypicker.com/umbrella/v2/graphql"

RETURN_QUERY = """
query SearchReturnItineraries($search: SearchReturnInput, $filter: ItinerariesFilterInput, $options: ItinerariesOptionsInput) {
  returnItineraries(search: $search, filter: $filter, options: $options) {
    ... on AppError { error: message }
    ... on Itineraries {
      itineraries {
        ... on ItineraryReturn {
          id
          price { amount }
          pnrCount
          bookingOptions {
            edges {
              node {
                bookingUrl
                price { amount }
              }
            }
          }
          outbound {
            duration
            sectorSegments {
              layover { duration isBaggageRecheck }
              segment {
                code
                duration
                carrier { code name }
                operatingCarrier { code name }
                source { localTime station { code name city { name } country { code name } } }
                destination { localTime station { code name city { name } country { code name } } }
              }
            }
          }
          inbound {
            duration
            sectorSegments {
              layover { duration isBaggageRecheck }
              segment {
                code
                duration
                carrier { code name }
                operatingCarrier { code name }
                source { localTime station { code name city { name } country { code name } } }
                destination { localTime station { code name city { name } country { code name } } }
              }
            }
          }
        }
      }
    }
  }
}
"""

ONEWAY_QUERY = """
query SearchOneWay($search: SearchOnewayInput, $filter: ItinerariesFilterInput, $options: ItinerariesOptionsInput) {
  onewayItineraries(search: $search, filter: $filter, options: $options) {
    ... on AppError { error: message }
    ... on Itineraries {
      itineraries {
        ... on ItineraryOneWay {
          id
          price { amount }
          pnrCount
          bookingOptions {
            edges {
              node {
                bookingUrl
                price { amount }
              }
            }
          }
          sector {
            duration
            sectorSegments {
              layover { duration isBaggageRecheck }
              segment {
                code
                duration
                carrier { code name }
                operatingCarrier { code name }
                source { localTime station { code name city { name } country { code name } } }
                destination { localTime station { code name city { name } country { code name } } }
              }
            }
          }
        }
      }
    }
  }
}
"""


def _parse_sector(sector_obj: dict[str, Any]) -> FlightSector:
    segs: list[FlightSegment] = []
    for ss in sector_obj.get("sectorSegments", []):
        seg = ss["segment"]
        lv = ss.get("layover")
        carrier = seg.get("carrier") or {}
        op_carrier = seg.get("operatingCarrier") or carrier
        src = seg["source"]
        dst = seg["destination"]
        src_st = src["station"]
        dst_st = dst["station"]

        segs.append(
            FlightSegment(
                carrier_code=carrier.get("code", ""),
                carrier_name=carrier.get("name", ""),
                flight_number=str(seg.get("code", "")),
                operating_carrier=op_carrier.get("code", carrier.get("code", "")),
                origin_code=src_st.get("code", ""),
                origin_name=src_st.get("name", ""),
                origin_city=(src_st.get("city") or {}).get("name", ""),
                origin_country=(src_st.get("country") or {}).get("code", ""),
                dest_code=dst_st.get("code", ""),
                dest_name=dst_st.get("name", ""),
                dest_city=(dst_st.get("city") or {}).get("name", ""),
                dest_country=(dst_st.get("country") or {}).get("code", ""),
                departure_local=src.get("localTime", ""),
                arrival_local=dst.get("localTime", ""),
                duration_minutes=int(round((seg.get("duration") or 0) / 60)),
                layover_before_minutes=(
                    int(round(lv["duration"] / 60)) if lv and lv.get("duration") is not None else None
                ),
                is_baggage_recheck_before=bool(lv.get("isBaggageRecheck")) if lv else False,
            )
        )
    total_min = int(round((sector_obj.get("duration") or 0) / 60))
    return FlightSector(segments=segs, total_duration_minutes=total_min)


def _extract_booking_url(itin: dict[str, Any]) -> str:
    edges = ((itin.get("bookingOptions") or {}).get("edges")) or []
    if not edges:
        return ""
    node = edges[0].get("node") or {}
    path = node.get("bookingUrl") or ""
    if path.startswith("http"):
        return path
    if path.startswith("/"):
        return f"https://www.kiwi.com{path}"
    return ""


def _post_graphql(payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    for attempt in range(2):
        try:
            resp = requests.post(
                KIWI_GRAPHQL_URL,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            if attempt == 1:
                raise
    return {}


def _fetch_return_pass(
    label: str,
    out_start: str,
    out_end: str,
    in_start: str,
    in_end: str,
    filt: dict[str, Any],
    sort_by: str,
    cfg: SearchConfig,
) -> tuple[str, list[RawItinerary], str | None]:
    tw_ids = [f"Station:airport:{code}" for code in cfg.taiwan_airports]
    variables = {
        "search": {
            "itinerary": {
                "source": {"ids": [f"Station:airport:{cfg.origin_airport}"]},
                "destination": {"ids": tw_ids},
                "outboundDepartureDate": {"start": out_start, "end": out_end},
                "inboundDepartureDate": {"start": in_start, "end": in_end},
            },
            "passengers": {"adults": cfg.passengers_adults, "children": 0, "infants": 0},
            "cabinClass": {"cabinClass": cfg.cabin_class, "applyMixedClasses": False},
        },
        "filter": {
            "excludeStopoverCountries": list(cfg.excluded_countries),
            "allowReturnFromDifferentCity": True,
            "allowReturnToDifferentCity": False,
            "allowChangeInboundDestination": False,
            "allowChangeInboundSource": True,
            **filt,
        },
        "options": {
            "currency": cfg.currency,
            "locale": "en",
            "partner": "skypicker",
            "sortBy": sort_by,
        },
    }
    try:
        data = _post_graphql({"query": RETURN_QUERY, "variables": variables}, cfg.request_timeout_sec)
        node = (data.get("data") or {}).get("returnItineraries") or {}
        if "error" in node:
            return label, [], str(node["error"])
        results: list[RawItinerary] = []
        for it in node.get("itineraries") or []:
            price_raw = (it.get("price") or {}).get("amount")
            if not price_raw:
                continue
            price_usd = int(round(float(price_raw)))
            pnr = int(it.get("pnrCount") or 1)
            outbound = _parse_sector(it["outbound"])
            inbound = _parse_sector(it["inbound"])
            has_conn_recheck = any(s.is_baggage_recheck_before for s in outbound.segments[1:] + inbound.segments[1:])
            if pnr == 1 and not has_conn_recheck:
                t_struct = "single_ticket"
            elif has_conn_recheck:
                t_struct = "self_transfer_connection"
            else:
                t_struct = "split_outbound_inbound"

            results.append(
                RawItinerary(
                    source_provider=f"kiwi_rt:{label}",
                    price_usd=price_usd,
                    pnr_count=pnr,
                    ticket_structure=t_struct,
                    outbound=outbound,
                    inbound=inbound,
                    booking_url=_extract_booking_url(it),
                )
            )
        return label, results, None
    except Exception as exc:
        return label, [], str(exc)


def _fetch_oneway_pass(
    label: str,
    src_ids: list[str],
    dst_ids: list[str],
    dep_start: str,
    dep_end: str,
    filt: dict[str, Any],
    cfg: SearchConfig,
) -> tuple[str, list[tuple[int, int, FlightSector, str]], str | None]:
    variables = {
        "search": {
            "itinerary": {
                "source": {"ids": src_ids},
                "destination": {"ids": dst_ids},
                "outboundDepartureDate": {"start": dep_start, "end": dep_end},
            },
            "passengers": {"adults": cfg.passengers_adults, "children": 0, "infants": 0},
            "cabinClass": {"cabinClass": cfg.cabin_class, "applyMixedClasses": False},
        },
        "filter": {
            "excludeStopoverCountries": list(cfg.excluded_countries),
            **filt,
        },
        "options": {
            "currency": cfg.currency,
            "locale": "en",
            "partner": "skypicker",
            "sortBy": "PRICE",
        },
    }
    try:
        data = _post_graphql({"query": ONEWAY_QUERY, "variables": variables}, cfg.request_timeout_sec)
        node = (data.get("data") or {}).get("onewayItineraries") or {}
        if "error" in node:
            return label, [], str(node["error"])
        sectors: list[tuple[int, int, FlightSector, str]] = []
        for it in node.get("itineraries") or []:
            price_raw = (it.get("price") or {}).get("amount")
            if not price_raw:
                continue
            price_usd = int(round(float(price_raw)))
            pnr = int(it.get("pnrCount") or 1)
            sec = _parse_sector(it["sector"])
            sectors.append((price_usd, pnr, sec, _extract_booking_url(it)))
        return label, sectors, None
    except Exception as exc:
        return label, [], str(exc)


def fetch_kiwi_itineraries(cfg: SearchConfig = DEFAULT_CONFIG) -> tuple[list[RawItinerary], dict[str, Any]]:
    """Run multi-pass live Kiwi GraphQL searches across all layover profiles & dates."""
    out_start = f"{cfg.outbound_start.isoformat()}T00:00:00"
    out_end = f"{cfg.outbound_end.isoformat()}T23:59:59"
    in_start = f"{cfg.inbound_start.isoformat()}T00:00:00"
    in_end = f"{cfg.inbound_end.isoformat()}T23:59:59"

    rt_tasks: list[tuple[str, str, str, str, str, dict[str, Any], str]] = [
        # 1. Ideal 2-4h single-PNR (price & quality)
        ("ideal_2_4h_price", out_start, out_end, in_start, in_end, {"limit": 60, "maxStopsCount": 2, "enableSelfTransfer": False, "stopoverTime": {"start": 2, "end": 4}}, "PRICE"),
        ("ideal_2_4h_quality", out_start, out_end, in_start, in_end, {"limit": 60, "maxStopsCount": 2, "enableSelfTransfer": False, "stopoverTime": {"start": 2, "end": 4}}, "QUALITY"),
        # 2. Acceptable 2-6h single-PNR
        ("short_2_6h_price", out_start, out_end, in_start, in_end, {"limit": 80, "maxStopsCount": 2, "enableSelfTransfer": False, "stopoverTime": {"start": 2, "end": 6}}, "PRICE"),
        # 3. Single-PNR 2-22h (captures mixed 3h out + 18.5h BKK/HKG/EastEU overnight in!)
        ("single_pnr_2_22h", out_start, out_end, in_start, in_end, {"limit": 80, "maxStopsCount": 2, "enableSelfTransfer": False, "stopoverTime": {"start": 2, "end": 22}}, "PRICE"),
        # 4. Overnight hubs (East Europe / HK / Bangkok) incl. self-transfer
        ("overnight_hubs", out_start, out_end, in_start, in_end, {"limit": 80, "maxStopsCount": 2, "enableSelfTransfer": True, "stopoverCountries": OVERNIGHT_ELIGIBLE_COUNTRIES_KIWI, "stopoverTime": {"start": 2, "end": 22}}, "PRICE"),
        # 5. 1-stop mixed (captures 8-10h daytime city explore & 18-20h overnight self-transfer)
        ("1stop_mixed_price", out_start, out_end, in_start, in_end, {"limit": 80, "maxStopsCount": 1, "enableSelfTransfer": True, "stopoverTime": {"start": 2, "end": 22}}, "PRICE"),
        ("1stop_mixed_quality", out_start, out_end, in_start, in_end, {"limit": 80, "maxStopsCount": 1, "enableSelfTransfer": True, "stopoverTime": {"start": 2, "end": 22}}, "QUALITY"),
    ]

    # Also query individual outbound dates against return window so cheaper single days don't crowd out other days
    cur = cfg.outbound_start
    while cur <= cfg.outbound_end:
        ds = f"{cur.isoformat()}T00:00:00"
        de = f"{cur.isoformat()}T23:59:59"
        rt_tasks.append(
            (
                f"day_{cur.isoformat()}_1stop",
                ds,
                de,
                in_start,
                in_end,
                {"limit": 45, "maxStopsCount": 1, "enableSelfTransfer": True, "stopoverTime": {"start": 2, "end": 22}},
                "PRICE",
            )
        )
        cur += timedelta(days=1)

    all_raw: list[RawItinerary] = []
    errors: list[str] = []
    pass_counts: dict[str, int] = {}

    tw_ids = [f"Station:airport:{code}" for code in cfg.taiwan_airports]
    tlv_ids = [f"Station:airport:{cfg.origin_airport}"]

    ow_tasks = [
        ("ow_out_single", tlv_ids, tw_ids, out_start, out_end, {"limit": 60, "maxStopsCount": 2, "enableSelfTransfer": False, "stopoverTime": {"start": 2, "end": 22}}),
        ("ow_out_1stop", tlv_ids, tw_ids, out_start, out_end, {"limit": 80, "maxStopsCount": 1, "enableSelfTransfer": True, "stopoverTime": {"start": 2, "end": 22}}),
        ("ow_out_hubs", tlv_ids, tw_ids, out_start, out_end, {"limit": 60, "maxStopsCount": 2, "enableSelfTransfer": True, "stopoverCountries": OVERNIGHT_ELIGIBLE_COUNTRIES_KIWI, "stopoverTime": {"start": 2, "end": 22}}),
        ("ow_in_single", tw_ids, tlv_ids, in_start, in_end, {"limit": 60, "maxStopsCount": 2, "enableSelfTransfer": False, "stopoverTime": {"start": 2, "end": 22}}),
        ("ow_in_1stop", tw_ids, tlv_ids, in_start, in_end, {"limit": 80, "maxStopsCount": 1, "enableSelfTransfer": True, "stopoverTime": {"start": 2, "end": 22}}),
        ("ow_in_hubs", tw_ids, tlv_ids, in_start, in_end, {"limit": 60, "maxStopsCount": 2, "enableSelfTransfer": True, "stopoverCountries": OVERNIGHT_ELIGIBLE_COUNTRIES_KIWI, "stopoverTime": {"start": 2, "end": 22}}),
    ]

    out_sectors: list[tuple[int, int, FlightSector, str]] = []
    in_sectors: list[tuple[int, int, FlightSector, str]] = []

    with ThreadPoolExecutor(max_workers=6) as pool:
        rt_futs = [
            pool.submit(_fetch_return_pass, lbl, os_, oe_, is_, ie_, flt, srt, cfg)
            for (lbl, os_, oe_, is_, ie_, flt, srt) in rt_tasks
        ]
        ow_futs = [
            pool.submit(_fetch_oneway_pass, lbl, s_ids, d_ids, ds, de, flt, cfg)
            for (lbl, s_ids, d_ids, ds, de, flt) in ow_tasks
        ]

        for fut in as_completed(rt_futs):
            lbl, res, err = fut.result()
            pass_counts[lbl] = len(res)
            if err:
                errors.append(f"{lbl}: {err}")
            all_raw.extend(res)

        for fut in as_completed(ow_futs):
            lbl, secs, err = fut.result()
            pass_counts[lbl] = len(secs)
            if err:
                errors.append(f"{lbl}: {err}")
            if lbl.startswith("ow_out"):
                out_sectors.extend(secs)
            else:
                in_sectors.extend(secs)

    # Pre-filter valid outbound & inbound one-way sectors and pair best combinations
    valid_out: dict[str, tuple[int, int, FlightSector, str]] = {}
    for price, pnr, sec, burl in out_sectors:
        _, watch_ok, _, _ = evaluate_sector(sec, cfg)
        if watch_ok:
            key = "-".join(f"{s.carrier_code}{s.flight_number}@{s.departure_local[:10]}" for s in sec.segments)
            if key not in valid_out or price < valid_out[key][0]:
                valid_out[key] = (price, pnr, sec, burl)

    valid_in: dict[str, tuple[int, int, FlightSector, str]] = {}
    for price, pnr, sec, burl in in_sectors:
        _, watch_ok, _, _ = evaluate_sector(sec, cfg)
        if watch_ok:
            key = "-".join(f"{s.carrier_code}{s.flight_number}@{s.departure_local[:10]}" for s in sec.segments)
            if key not in valid_in or price < valid_in[key][0]:
                valid_in[key] = (price, pnr, sec, burl)

    sorted_out = sorted(valid_out.values(), key=lambda x: x[0])[:18]
    sorted_in = sorted(valid_in.values(), key=lambda x: x[0])[:18]
    paired_count = 0
    for o_price, o_pnr, o_sec, o_url in sorted_out:
        for i_price, i_pnr, i_sec, i_url in sorted_in:
            has_conn_recheck = any(
                s.is_baggage_recheck_before for s in o_sec.segments[1:] + i_sec.segments[1:]
            )
            t_struct = "self_transfer_connection" if has_conn_recheck else "split_outbound_inbound"
            all_raw.append(
                RawItinerary(
                    source_provider="kiwi_oneway_pair",
                    price_usd=o_price + i_price,
                    pnr_count=o_pnr + i_pnr,
                    ticket_structure=t_struct,
                    outbound=o_sec,
                    inbound=i_sec,
                    booking_url=o_url,
                    inbound_booking_url=i_url,
                )
            )
            paired_count += 1

    meta = {
        "provider": "kiwi_umbrella_graphql",
        "status": "ok" if all_raw else ("error" if errors else "empty"),
        "raw_candidates_fetched": len(all_raw),
        "valid_oneway_outbound": len(valid_out),
        "valid_oneway_inbound": len(valid_in),
        "paired_combinations": paired_count,
        "pass_counts": pass_counts,
        "errors": errors,
    }
    return all_raw, meta
