"""Data models for real flight segments, layovers, itineraries, and daily runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class FlightSegment:
    carrier_code: str
    carrier_name: str
    flight_number: str
    operating_carrier: str
    origin_code: str
    origin_name: str
    origin_city: str
    origin_country: str
    dest_code: str
    dest_name: str
    dest_city: str
    dest_country: str
    departure_local: str  # ISO 8601 YYYY-MM-DDTHH:MM:SS
    arrival_local: str    # ISO 8601 YYYY-MM-DDTHH:MM:SS
    duration_minutes: int
    layover_before_minutes: int | None = None
    is_baggage_recheck_before: bool = False


@dataclass
class LayoverEvaluation:
    arrival_airport: str
    departure_airport: str
    city: str
    country: str
    arrival_local: str
    departure_local: str
    duration_hours: float
    is_self_transfer: bool
    category: str
    # One of:
    # - "IDEAL_SHORT_2_4H"
    # - "ACCEPTABLE_SHORT_4_6H"
    # - "DAY_EXPLORE_8_10H"
    # - "OVERNIGHT_EXPLORE_18_20H"
    # - "LONG_LAYOVER"
    # - "WATCHLIST_NEAR_MISS"
    # - "REJECTED"
    strict_valid: bool
    watchlist_valid: bool
    usable_city_hours: float | None = None
    transit_summary: str = ""
    luggage_note: str = ""
    reason: str = ""


@dataclass
class FlightSector:
    segments: list[FlightSegment]
    total_duration_minutes: int

    @property
    def origin_code(self) -> str:
        return self.segments[0].origin_code

    @property
    def dest_code(self) -> str:
        return self.segments[-1].dest_code

    @property
    def departure_local(self) -> str:
        return self.segments[0].departure_local

    @property
    def arrival_local(self) -> str:
        return self.segments[-1].arrival_local

    @property
    def stops_count(self) -> int:
        return max(0, len(self.segments) - 1)


@dataclass
class RawItinerary:
    source_provider: str  # e.g., "kiwi_graphql_rt", "kiwi_sector_pair", "google_flights"
    price_usd: int
    pnr_count: int
    ticket_structure: str  # "single_ticket" | "split_outbound_inbound" | "self_transfer_connection"
    outbound: FlightSector
    inbound: FlightSector
    booking_url: str = ""
    inbound_booking_url: str = ""

    def route_fingerprint(self) -> str:
        """Stable route+flight+date key for tracking daily price changes."""
        out_key = "-".join(
            f"{s.carrier_code}{s.flight_number}@{s.departure_local[:10]}:{s.origin_code}>{s.dest_code}"
            for s in self.outbound.segments
        )
        in_key = "-".join(
            f"{s.carrier_code}{s.flight_number}@{s.departure_local[:10]}:{s.origin_code}>{s.dest_code}"
            for s in self.inbound.segments
        )
        return f"{out_key}||{in_key}"


@dataclass
class EvaluatedItinerary:
    fingerprint: str
    source_provider: str
    price_usd: int
    pnr_count: int
    ticket_structure: str
    is_open_jaw_taiwan: bool
    taiwan_arrival_airport: str
    taiwan_departure_airport: str
    outbound_date: str
    inbound_date: str
    inbound_arrival_tlv_date: str
    outbound: FlightSector
    inbound: FlightSector
    outbound_layovers: list[LayoverEvaluation]
    inbound_layovers: list[LayoverEvaluation]
    tier: str  # "STRICT_IDEAL" | "STRICT_ACCEPTABLE" | "WATCHLIST" | "REJECTED"
    score: float  # Lower is better (price + convenience penalty)
    badges: list[str] = field(default_factory=list)
    summary_note: str = ""
    booking_url: str = ""
    inbound_booking_url: str = ""
    previous_price_usd: int | None = None
    price_delta_usd: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
