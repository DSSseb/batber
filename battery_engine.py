from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from math import sqrt
from typing import Iterable

EXPORT_CODE = "D06"
IMPORT_CODE = "D07"

DATE_HEADER_ALIASES = {"fradato", "fromdate", "startdato", "startdate", "datetime", "timestamp", "starttime"}
VOLUME_HEADER_ALIASES = {"maengde", "mangde", "volume", "quantity", "energy", "energikwh", "kwh", "value"}
CODE_HEADER_ALIASES = {"malepunktstypekode", "maelepunktstypekode", "meteringpointtypecode", "meterpointtypecode", "measurementpointtypecode"}


@dataclass
class HourlyPoint:
    timestamp: datetime
    export_kwh: float = 0.0
    import_kwh: float = 0.0


@dataclass
class BatteryProduct:
    brand: str
    model: str
    capacity_kwh: float
    price_dkk: float
    max_charge_kw: float | None = None
    max_discharge_kw: float | None = None


@dataclass
class SimulationResult:
    capacity_kwh: float
    usable_capacity_kwh: float
    avoided_grid_import_kwh: float
    captured_export_kwh: float
    remaining_grid_import_kwh: float
    remaining_export_kwh: float
    cycles_equivalent: float
    utilization_pct: float
    marginal_avoided_import_kwh: float = 0.0
    marginal_per_added_kwh: float = 0.0
    added_capacity_kwh: float = 0.0
    price_dkk: float = 0.0
    max_charge_kw: float | None = None
    max_discharge_kw: float | None = None
    economic_value_dkk: float = 0.0
    value_per_1000_dkk_price: float = 0.0
    marginal_price_dkk: float = 0.0
    marginal_economic_value_dkk: float = 0.0
    marginal_value_per_1000_dkk: float = 0.0
    technical_recommended: bool = False
    economic_recommended: bool = False
    combined_recommended: bool = False

    def to_dict(self):
        return asdict(self)


def _normalize_header(value: object) -> str:
    import re, unicodedata
    text = "" if value is None else str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", text)


def _find_header_row(rows: list[list[object]]) -> tuple[int, list[str]]:
    best_index, best_headers, best_score = 0, [], -1
    for i, row in enumerate(rows[:30]):
        normalized = [_normalize_header(x) for x in row]
        score = int(any(h in DATE_HEADER_ALIASES for h in normalized)) + int(any(h in VOLUME_HEADER_ALIASES for h in normalized)) + int(any(h in CODE_HEADER_ALIASES for h in normalized))
        if score > best_score:
            best_index, best_headers, best_score = i, normalized, score
    return best_index, best_headers


def _sample_column(rows: list[list[object]], header_row: int, col: int, limit: int = 500) -> list[object]:
    values = []
    for row in rows[header_row + 1:]:
        if col < len(row) and row[col] not in (None, ""):
            values.append(row[col])
            if len(values) >= limit:
                break
    return values


def _resolve_columns(rows: list[list[object]]) -> tuple[int, dict[str, int], dict[str, str]]:
    import re
    header_row, normalized = _find_header_row(rows)
    original = [str(x).strip() if x is not None else "" for x in rows[header_row]]
    mapping = {}
    for i, h in enumerate(normalized):
        if "date" not in mapping and h in DATE_HEADER_ALIASES: mapping["date"] = i
        if "volume" not in mapping and h in VOLUME_HEADER_ALIASES: mapping["volume"] = i
        if "code" not in mapping and h in CODE_HEADER_ALIASES: mapping["code"] = i
    width = max((len(r) for r in rows[header_row:header_row + 600]), default=len(original))
    samples = {i: _sample_column(rows, header_row, i) for i in range(width)}
    if "date" not in mapping:
        candidates = [(sum(isinstance(v, datetime) for v in vals) / len(vals), i) for i, vals in samples.items() if vals]
        if candidates and max(candidates)[0] >= 0.7: mapping["date"] = max(candidates)[1]
    if "code" not in mapping:
        code_re = re.compile(r"^[A-Z][0-9]{2}$")
        candidates = [(sum(bool(code_re.match(str(v).strip().upper())) for v in vals) / len(vals), i) for i, vals in samples.items() if vals]
        if candidates and max(candidates)[0] >= 0.5: mapping["code"] = max(candidates)[1]
    if "volume" not in mapping:
        candidates = []
        for i, vals in samples.items():
            if i in mapping.values() or not vals: continue
            numeric = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
            ratio = len(numeric) / len(vals)
            sensible = sum(abs(float(v)) < 1_000_000 for v in numeric) / len(numeric) if numeric else 0.0
            candidates.append((ratio * sensible, i))
        if candidates and max(candidates)[0] >= 0.7: mapping["volume"] = max(candidates)[1]
    missing = [k for k in ("date", "volume", "code") if k not in mapping]
    if missing:
        readable = {"date": "dato/tid", "volume": "energimængde", "code": "målepunktstype"}
        raise ValueError("Kunne ikke identificere kolonne(r) for " + ", ".join(readable[m] for m in missing) + ". Fundne kolonner: " + ", ".join(h or "(tom)" for h in original))
    labels = {key: original[idx] if idx < len(original) else f"kolonne {idx + 1}" for key, idx in mapping.items()}
    return header_row, mapping, labels


def _snap_to_hour(ts: datetime) -> datetime:
    return (ts + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)


def _expected_hours_copenhagen(start: datetime, end_exclusive: datetime) -> int:
    # Energinet/ElOverblik timestamps are Danish local time. Calculating in UTC handles
    # the 23-hour spring day and 25-hour autumn day correctly.
    from datetime import timezone
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Copenhagen")
    start_utc = start.replace(tzinfo=tz).astimezone(timezone.utc)
    end_utc = end_exclusive.replace(tzinfo=tz).astimezone(timezone.utc)
    return max(int((end_utc - start_utc).total_seconds() // 3600), 0)


def parse_energinet_rows(rows: list[list[object]]) -> tuple[list[HourlyPoint], dict]:
    if not rows:
        raise ValueError("Filen indeholder ingen data.")
    header_row, idx, labels = _resolve_columns(rows)
    needed_max = max(idx.values())

    # The tuple key preserves the duplicated local clock hour at the autumn DST shift.
    hourly: dict[tuple[datetime, int], HourlyPoint] = {}
    occurrence: dict[str, dict[datetime, int]] = {EXPORT_CODE: {}, IMPORT_CODE: {}}
    codes, code_kwh = {}, {}
    export_keys, import_keys = set(), set()
    raw_export = raw_import = 0.0
    valid_rows = 0

    for row in rows[header_row + 1:]:
        if len(row) <= needed_max:
            continue
        ts = row[idx["date"]]
        code = str(row[idx["code"]]).strip().upper()
        value = row[idx["volume"]]
        if not isinstance(ts, datetime) or value in (None, ""):
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if value != value:
            continue

        valid_rows += 1
        codes[code] = codes.get(code, 0) + 1
        code_kwh[code] = code_kwh.get(code, 0.0) + value
        if code not in (EXPORT_CODE, IMPORT_CODE):
            continue

        ts = _snap_to_hour(ts)
        seen = occurrence[code].get(ts, 0)
        occurrence[code][ts] = seen + 1
        key = (ts, seen)
        p = hourly.setdefault(key, HourlyPoint(ts))
        if code == EXPORT_CODE:
            p.export_kwh += value
            raw_export += value
            export_keys.add(key)
        else:
            p.import_kwh += value
            raw_import += value
            import_keys.add(key)

    missing_codes = [c for c in (EXPORT_CODE, IMPORT_CODE) if codes.get(c, 0) == 0]
    if missing_codes:
        found = ", ".join(sorted(codes)) if codes else "ingen"
        meaning = {EXPORT_CODE: "leveret til nettet", IMPORT_CODE: "hentet fra nettet"}
        missing_text = ", ".join(f"{c} ({meaning[c]})" for c in missing_codes)
        raise ValueError(
            f"Filen kan ikke bruges til fuld batteridimensionering, fordi {missing_text} mangler. "
            f"Fundne målepunktstyper: {found}."
        )

    all_keys = export_keys | import_keys
    if not all_keys:
        raise ValueError("Der blev ikke fundet brugbare timeværdier for D06 og D07.")

    sorted_keys = sorted(all_keys, key=lambda k: (k[0], k[1]))
    points = [hourly[k] for k in sorted_keys]
    paired_keys = export_keys & import_keys
    start = sorted_keys[0][0]
    last = sorted_keys[-1][0]
    end_exclusive = last + timedelta(hours=1)
    expected = _expected_hours_copenhagen(start, end_exclusive)
    paired_hours = len(paired_keys)
    missing_hours = max(expected - paired_hours, 0)

    # Conservative netting within each hour. We cannot know intra-hour order from hourly data.
    for p in points:
        net = p.export_kwh - p.import_kwh
        p.export_kwh, p.import_kwh = max(net, 0.0), max(-net, 0.0)

    meta = {
        "start": start, "end": end_exclusive, "hours": len(points), "paired_hours": paired_hours,
        "expected_hours": expected, "missing_hours": missing_hours,
        "coverage_pct": min(100.0, 100 * paired_hours / expected) if expected else 100.0,
        "raw_export_kwh": raw_export, "raw_import_kwh": raw_import,
        "netted_export_kwh": sum(p.export_kwh for p in points),
        "netted_import_kwh": sum(p.import_kwh for p in points),
        "codes": codes, "code_kwh": code_kwh, "valid_rows": valid_rows,
        "header_row": header_row + 1, "column_mapping": labels,
    }
    return points, meta


def simulate(
    points: Iterable[HourlyPoint],
    capacity_kwh: float,
    min_soc_pct: float = 10.0,
    roundtrip_efficiency_pct: float = 90.0,
    max_charge_kw: float | None = None,
    max_discharge_kw: float | None = None,
    initial_soc_pct: float | None = None,
) -> SimulationResult:
    capacity = float(capacity_kwh)
    min_soc = capacity * min_soc_pct / 100.0
    max_soc = capacity
    usable = max(max_soc - min_soc, 0.0)
    rte = max(min(roundtrip_efficiency_pct / 100.0, 1.0), 0.01)
    charge_eff = discharge_eff = sqrt(rte)
    soc = min_soc if initial_soc_pct is None else min(max(capacity * initial_soc_pct / 100.0, min_soc), max_soc)

    avoided = captured = remain_import = remain_export = throughput_out = 0.0

    for p in points:
        surplus = max(p.export_kwh, 0.0)
        demand = max(p.import_kwh, 0.0)

        room = max_soc - soc
        charge_limit = float("inf") if max_charge_kw is None else max_charge_kw
        discharge_limit = float("inf") if max_discharge_kw is None else max_discharge_kw
        charge_from_ac = min(surplus, charge_limit, room / charge_eff if charge_eff else 0.0)
        soc += charge_from_ac * charge_eff
        captured += charge_from_ac
        remain_export += surplus - charge_from_ac

        available_ac = max((soc - min_soc) * discharge_eff, 0.0)
        discharge_to_load = min(demand, discharge_limit, available_ac)
        soc -= discharge_to_load / discharge_eff if discharge_eff else 0.0
        avoided += discharge_to_load
        throughput_out += discharge_to_load
        remain_import += demand - discharge_to_load

    cycles = throughput_out / usable if usable > 0 else 0.0
    total_import = avoided + remain_import
    utilization = 100 * avoided / total_import if total_import else 0.0
    return SimulationResult(
        capacity_kwh=capacity,
        usable_capacity_kwh=usable,
        avoided_grid_import_kwh=avoided,
        captured_export_kwh=captured,
        remaining_grid_import_kwh=remain_import,
        remaining_export_kwh=remain_export,
        cycles_equivalent=cycles,
        utilization_pct=utilization,
        max_charge_kw=max_charge_kw,
        max_discharge_kw=max_discharge_kw,
    )


def simulate_products(
    points: list[HourlyPoint],
    products: list[BatteryProduct],
    *,
    buy_price_dkk_kwh: float,
    sell_price_dkk_kwh: float,
    min_soc_pct: float = 10.0,
    roundtrip_efficiency_pct: float = 90.0,
) -> list[SimulationResult]:
    results: list[SimulationResult] = []
    for p in sorted(products, key=lambda x: x.capacity_kwh):
        r = simulate(
            points,
            p.capacity_kwh,
            min_soc_pct=min_soc_pct,
            roundtrip_efficiency_pct=roundtrip_efficiency_pct,
            max_charge_kw=p.max_charge_kw,
            max_discharge_kw=p.max_discharge_kw,
        )
        r.price_dkk = p.price_dkk
        # Økonomisk værdi i måleperioden:
        # undgået køb minus mistet salgsindtægt på den energi, der blev sendt ind i batteriet.
        r.economic_value_dkk = (
            r.avoided_grid_import_kwh * buy_price_dkk_kwh
            - r.captured_export_kwh * sell_price_dkk_kwh
        )
        r.value_per_1000_dkk_price = (
            r.economic_value_dkk / r.price_dkk * 1000 if r.price_dkk > 0 else 0.0
        )
        results.append(r)

    previous = None
    for r in results:
        if previous is not None:
            r.added_capacity_kwh = r.capacity_kwh - previous.capacity_kwh
            r.marginal_avoided_import_kwh = r.avoided_grid_import_kwh - previous.avoided_grid_import_kwh
            r.marginal_per_added_kwh = (
                r.marginal_avoided_import_kwh / r.added_capacity_kwh if r.added_capacity_kwh else 0.0
            )
            r.marginal_price_dkk = r.price_dkk - previous.price_dkk
            r.marginal_economic_value_dkk = r.economic_value_dkk - previous.economic_value_dkk
            r.marginal_value_per_1000_dkk = (
                r.marginal_economic_value_dkk / r.marginal_price_dkk * 1000
                if r.marginal_price_dkk > 0 else 0.0
            )
        previous = r
    return results


def choose_technical_recommendation(results: list[SimulationResult], threshold_fraction_of_peak: float = 0.35) -> SimulationResult:
    if not results:
        raise ValueError("Ingen simuleringsresultater.")
    marginals = [r.marginal_per_added_kwh for r in results[1:] if r.marginal_per_added_kwh > 0]
    if not marginals:
        results[0].technical_recommended = True
        return results[0]
    peak = max(marginals)
    cutoff = peak * threshold_fraction_of_peak
    recommendation = results[-1]
    for i in range(1, len(results)):
        if results[i].marginal_per_added_kwh < cutoff:
            recommendation = results[i - 1]
            break
    recommendation.technical_recommended = True
    return recommendation


def choose_economic_recommendation(results: list[SimulationResult]) -> SimulationResult:
    if not results:
        raise ValueError("Ingen simuleringsresultater.")
    # Højeste økonomiske værdi i måleperioden pr. 1.000 kr. batteripris.
    recommendation = max(results, key=lambda r: r.value_per_1000_dkk_price)
    recommendation.economic_recommended = True
    return recommendation


def choose_combined_recommendation(
    results: list[SimulationResult],
    technical: SimulationResult,
    economic: SimulationResult,
    *,
    min_technical_capture_fraction: float = 0.85,
) -> SimulationResult:
    """Choose a practical balance with technical need first, economics second.

    The customer's energy profile defines the technical sweet spot. A product can
    only become the recommended balance if it captures at least
    ``min_technical_capture_fraction`` of the avoided grid import delivered by the
    technical sweet spot. Among those technically relevant products, the product
    with the highest economic value per DKK invested is selected.

    This prevents one unusually cheap early module step from forcing an
    unrealistically small recommendation, while still letting price decide between
    products that cover roughly the same technical need.
    """
    if not results:
        raise ValueError("Ingen simuleringsresultater.")

    for r in results:
        r.combined_recommended = False

    target_benefit = technical.avoided_grid_import_kwh
    minimum_benefit = target_benefit * min_technical_capture_fraction

    # Keep the balance within the technical envelope.
    eligible = [
        r for r in results
        if r.capacity_kwh <= technical.capacity_kwh + 1e-9
        and r.avoided_grid_import_kwh + 1e-9 >= minimum_benefit
    ]

    # Defensive fallback: if a very sparse product series has no qualifying size,
    # use the technical sweet spot itself.
    if not eligible:
        recommendation = technical
    else:
        recommendation = max(
            eligible,
            key=lambda r: (r.value_per_1000_dkk_price, -r.capacity_kwh),
        )

    recommendation.combined_recommended = True
    return recommendation

