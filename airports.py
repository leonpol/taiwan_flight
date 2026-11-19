"""Airport & city metadata for strict layover validation (Rules 4, 6, 7, 8)."""

from __future__ import annotations

from dataclasses import dataclass

# Requirement 8: Taiwan commercial international airports
TAIWAN_AIRPORTS: dict[str, str] = {
    "TPE": "Taipei Taoyuan",
    "TSA": "Taipei Songshan",
    "KHH": "Kaohsiung",
    "RMQ": "Taichung",
}

# Requirement 4: Strict blocklist — No layovers in Turkey or the Persian Gulf
BLOCKED_COUNTRIES: frozenset[str] = frozenset(
    {
        "TR",  # Turkey
        "AE",  # United Arab Emirates
        "QA",  # Qatar
        "BH",  # Bahrain
        "KW",  # Kuwait
        "OM",  # Oman
        "SA",  # Saudi Arabia
        "IR",  # Iran
        "IQ",  # Iraq
    }
)

BLOCKED_AIRPORTS: frozenset[str] = frozenset(
    {
        # Turkey
        "IST", "SAW", "ESB", "AYT", "ADB", "DLM", "BJV", "TZX", "ADA", "GZT",
        "ASR", "KYA", "DIY", "VAN", "ERZ", "ISE", "MLX", "SZF", "BZI", "EDO",
        # UAE
        "DXB", "AUH", "SHJ", "DWC", "RKT", "FJR", "AAN", "AZI",
        # Qatar, Bahrain, Kuwait, Oman
        "DOH", "DIA", "BAH", "KWI", "MCT", "SLL", "DQM", "KHS",
        # Saudi Arabia
        "RUH", "JED", "DMM", "MED", "AHB", "TIF", "ELQ", "TUU", "YNB", "GIZ", "NUM",
        # Iran & Iraq
        "IKA", "THR", "MHD", "SYZ", "TBZ", "IFN", "KIH", "BGW", "EBL", "BSR", "NJF", "ISU",
    }
)

# Requirement 6: 18-20h overnight explore+sleep layover allowed ONLY in
# Eastern European cities, Hong Kong, or Bangkok.
OVERNIGHT_18_20H_AIRPORTS: dict[str, str] = {
    # Hong Kong & Bangkok
    "HKG": "Hong Kong",
    "BKK": "Bangkok (Suvarnabhumi)",
    "DMK": "Bangkok (Don Mueang)",
    # Eastern & Central-Eastern Europe
    "WAW": "Warsaw",
    "WMI": "Warsaw (Modlin)",
    "KRK": "Krakow",
    "GDN": "Gdansk",
    "KTW": "Katowice",
    "WRO": "Wroclaw",
    "PRG": "Prague",
    "BUD": "Budapest",
    "OTP": "Bucharest",
    "CLJ": "Cluj-Napoca",
    "SOF": "Sofia",
    "VAR": "Varna",
    "BEG": "Belgrade",
    "VIE": "Vienna",
    "BTS": "Bratislava",
    "ZAG": "Zagreb",
    "LJU": "Ljubljana",
    "VNO": "Vilnius",
    "RIX": "Riga",
    "TLL": "Tallinn",
    "TIA": "Tirana",
    "SKP": "Skopje",
    "RMO": "Chisinau",
    "KIV": "Chisinau",
    "TBS": "Tbilisi",
    "GYD": "Baku",
    "EVN": "Yerevan",
}

OVERNIGHT_ELIGIBLE_COUNTRIES_KIWI: list[str] = [
    "HK", "TH", "PL", "CZ", "HU", "RO", "BG", "RS", "AT", "SK",
    "HR", "SI", "LT", "LV", "EE", "AL", "MK", "MD", "GE", "AZ", "AM",
]

# Same-city airport pairs acceptable ONLY during 18-20h overnight layovers
SAME_METRO_OVERNIGHT_PAIRS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"BKK", "DMK"}),
        frozenset({"WAW", "WMI"}),
    }
)


@dataclass(frozen=True)
class AirportCityProfile:
    code: str
    city: str
    country: str
    has_left_luggage: bool
    transit_minutes_one_way: int
    transit_mode: str
    can_enter_landside_from_tlv: bool = True
    notes: str = ""


# Requirement 7: Verified airport left-luggage & fast city transit profiles
# Used to compute whether an 8-10h layover genuinely gives 5-8h in the city.
AIRPORT_CITY_PROFILES: dict[str, AirportCityProfile] = {
    "ZRH": AirportCityProfile("ZRH", "Zurich", "CH", True, 11, "SBB Train to Zurich HB", True, "SBB Service Center & 24h lockers"),
    "FRA": AirportCityProfile("FRA", "Frankfurt", "DE", True, 12, "S-Bahn S8/S9 to Frankfurt Hbf", True, "24h baggage storage in T1 & T2"),
    "CPH": AirportCityProfile("CPH", "Copenhagen", "DK", True, 15, "Metro M2 to Kongens Nytorv", True, "Smart lockers in P4 / Terminal 2"),
    "VIE": AirportCityProfile("VIE", "Vienna", "AT", True, 16, "CAT Train to Wien Mitte", True, "Baggage Service Center T1 & T3"),
    "AMS": AirportCityProfile("AMS", "Amsterdam", "NL", True, 17, "NS Intercity to Amsterdam Centraal", True, "Landside & airside baggage lockers"),
    "HND": AirportCityProfile("HND", "Tokyo", "JP", True, 18, "Tokyo Monorail / Keikyu Line", True, "T3 coin lockers & JAL ABC counter"),
    "WAW": AirportCityProfile("WAW", "Warsaw", "PL", True, 20, "SKM S2/S3 Train to Centrum", True, "24h luggage lockers outside T-A"),
    "BRU": AirportCityProfile("BRU", "Brussels", "BE", True, 20, "SNCB Train to Brussels Central", True, "24h baggage lockers on Level 0"),
    "ARN": AirportCityProfile("ARN", "Stockholm", "SE", True, 20, "Arlanda Express to Stockholm C", True, "Bagport storage in SkyCity / T5"),
    "MAD": AirportCityProfile("MAD", "Madrid", "ES", True, 22, "Cercanias C1/C10 or Metro Line 8", True, "24h left luggage in T1 & T4"),
    "HKG": AirportCityProfile("HKG", "Hong Kong", "HK", True, 24, "Airport Express to Central", True, "Baggage Storage on T1 Arrivals Level 5"),
    "SIN": AirportCityProfile("SIN", "Singapore", "SG", True, 25, "MRT / Taxi to Marina Bay", True, "24h Smarte Carte storage in Jewel & T1-T4"),
    "BKK": AirportCityProfile("BKK", "Bangkok", "TH", True, 26, "Airport Rail Link to Phaya Thai", True, "Airportels & Bellugg 24h storage on B Floor"),
    "PRG": AirportCityProfile("PRG", "Prague", "CZ", True, 30, "Trolleybus 59 + Metro A / AE Bus", True, "24h Dolezal baggage storage in T1 & T2"),
    "HEL": AirportCityProfile("HEL", "Helsinki", "FI", True, 30, "I/P Commuter Train to Central", True, "Smart lockers on Arrivals level"),
    "BCN": AirportCityProfile("BCN", "Barcelona", "ES", True, 30, "Aerobus / R2 Nord Train", True, "Excess Baggage Co storage in T1 & T2"),
    "FCO": AirportCityProfile("FCO", "Rome", "IT", True, 32, "Leonardo Express to Roma Termini", True, "Kipoint luggage storage in T3 Arrivals"),
    "OTP": AirportCityProfile("OTP", "Bucharest", "RO", False, 25, "CFR Train to Gara de Nord", True, "No reliable 24h terminal left-luggage lockers"),
    "BUD": AirportCityProfile("BUD", "Budapest", "HU", True, 35, "100E Airport Express to Deak Ferenc", True, "2B Arrivals baggage lockers"),
    "SOF": AirportCityProfile("SOF", "Sofia", "BG", False, 28, "Metro Line 4 to Serdika", True, "No dedicated terminal luggage storage"),
    "BEG": AirportCityProfile("BEG", "Belgrade", "RS", False, 30, "A1 Minibus to Slavija Square", True, "Limited locker availability"),
    "KRK": AirportCityProfile("KRK", "Krakow", "PL", True, 18, "SKA1 Train to Krakow Glowny", True, "24h automatic lockers near terminal"),
    "ATH": AirportCityProfile("ATH", "Athens", "GR", True, 40, "Metro Line 3 to Syntagma", True, "Care4Bag 24h storage at Arrivals Exit 1"),
    "CDG": AirportCityProfile("CDG", "Paris", "FR", True, 38, "RER B to Chatelet-Les Halles", True, "Bagages du Monde in Terminal 2 TGV"),
    "LHR": AirportCityProfile("LHR", "London", "GB", True, 22, "Elizabeth Line / Heathrow Express", True, "Excess Baggage Co in T2, T3, T4, T5"),
    "MUC": AirportCityProfile("MUC", "Munich", "DE", True, 44, "S-Bahn S1/S8 to Marienplatz", True, "Service Center T1/MAC storage; 44m each way"),
    "MXP": AirportCityProfile("MXP", "Milan", "IT", True, 51, "Malpensa Express to Milano Centrale", True, "51m each way — slow for 8h layover"),
    "ICN": AirportCityProfile("ICN", "Seoul", "KR", True, 45, "AREX Express to Seoul Station", True, "Hanjin/CJ storage in T1 & T2; 45m each way"),
    "NRT": AirportCityProfile("NRT", "Tokyo (Narita)", "JP", True, 55, "Skyliner to Ueno / NEX to Tokyo", True, "55m each way — Narita town nearby, Tokyo far"),
    "KIX": AirportCityProfile("KIX", "Osaka", "JP", True, 38, "Nankai Rapi:t to Namba", True, "JAL ABC / Kansai storage counters"),
    "DEL": AirportCityProfile("DEL", "New Delhi", "IN", True, 22, "Delhi Airport Metro Express", True, "24h Cloak Room at T3; e-Visa required ahead"),
    "BOM": AirportCityProfile("BOM", "Mumbai", "IN", True, 35, "Aqua Line Metro / Taxi", True, "T2 Left Luggage; e-Visa required ahead"),
    "HAN": AirportCityProfile("HAN", "Hanoi", "VN", True, 42, "Express Bus 86 / Grab to Old Quarter", True, "T2 luggage storage; e-Visa required ahead"),
    "SGN": AirportCityProfile("SGN", "Ho Chi Minh City", "VN", True, 28, "Taxi / Grab to District 1", True, "T2 ground floor lockers; e-Visa required ahead"),
    "GYD": AirportCityProfile("GYD", "Baku", "AZ", True, 30, "Aero Express / Bolt to 28 May", True, "Visa on arrival at GYD"),
    "LCA": AirportCityProfile("LCA", "Larnaca", "CY", True, 18, "Taxi / Bus 425 to Finikoudes", True, "Special Baggage storage counter"),
    "KUL": AirportCityProfile("KUL", "Kuala Lumpur", "MY", True, 28, "KLIA Ekspres", False, "Landside entry restricted for Israeli passports"),
    "CGK": AirportCityProfile("CGK", "Jakarta", "ID", True, 45, "Railink", False, "Landside entry restricted for Israeli passports"),
}


def is_blocked_station(airport_code: str, country_code: str = "") -> bool:
    """Return True if an airport or country violates Rule 4 (Persian Gulf or Turkey)."""
    code = (airport_code or "").upper().strip()
    cc = (country_code or "").upper().strip()
    return code in BLOCKED_AIRPORTS or cc in BLOCKED_COUNTRIES


def is_overnight_18_20h_hub(arr_airport: str, dep_airport: str) -> bool:
    """Return True if a layover airport (or same-metro pair) qualifies for Rule 6."""
    a = arr_airport.upper().strip()
    b = dep_airport.upper().strip()
    if a != b and frozenset({a, b}) not in SAME_METRO_OVERNIGHT_PAIRS:
        return False
    return a in OVERNIGHT_18_20H_AIRPORTS and b in OVERNIGHT_18_20H_AIRPORTS
