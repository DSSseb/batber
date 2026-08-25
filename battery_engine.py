from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from math import sqrt
from typing import Iterable

REQUIRED_COLUMNS = {"Fra_dato", "Mængde", "Målepunktstype_Kode"}
EXPORT_CODE = "D06"
IMPORT_CODE = "D07"


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
    max_charge_kw: float
    max_discharge_kw: float


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
    max_charge_kw: float = 0.0
    max_discharge_kw: float = 0.0
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


def parse_energinet_rows(rows: list[list[object]]) -> tuple[list[HourlyPoint], dict]:
    if not rows:
        raise ValueError("Filen indeholder ingen data.")
    headers = [str(x).strip() if x is not None else "" for x in rows[0]]
    missing = REQUIRED_COLUMNS - set(headers)
    if missing:
        raise ValueError("Mangler kolonner: " + ", ".join(sorted(missing)))
    idx = {h: i for i, h in enumerate(headers)}

    hourly: dict[datetime, HourlyPoint] = {}
    codes: dict[str, int] = {}
    raw_export = raw_import = 0.0

    for row in rows[1:]:
        if len(row) <= max(idx[c] for c in REQUIRED_COLUMNS):
            continue
        ts = row[idx["Fra_dato"]]
        code = str(row[idx["Målepunktstype_Kode"]]).strip()
        value = row[idx["Mængde"]]
        if not isinstance(ts, datetime) or value in (None, ""):
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        codes[code] = codes.get(code, 0) + 1
        if code not in (EXPORT_CODE, IMPORT_CODE):
            continue
        ts = ts.replace(microsecond=0)
        p = hourly.setdefault(ts, HourlyPoint(ts))
        if code == EXPORT_CODE:
            p.export_kwh += value
            raw_export += value
        else:
            p.import_kwh += value
            raw_import += value

    if not hourly:
        raise ValueError("Kunne ikke finde D06 (leveret til net) og D07 (forbrugt fra net).")

    points = sorted(hourly.values(), key=lambda p: p.timestamp)
    start, end = points[0].timestamp, points[-1].timestamp
    expected = int((end - start).total_seconds() // 3600) + 1
    present = len(points)
    missing_hours = max(expected - present, 0)

    # Konservativ nettning på timebasis, fordi rækkefølgen inden for timen ikke kendes.
    for p in points:
        net = p.export_kwh - p.import_kwh
        p.export_kwh = max(net, 0.0)
        p.import_kwh = max(-net, 0.0)

    meta = {
        "start": start,
        "end": end + timedelta(hours=1),
        "hours": present,
        "expected_hours": expected,
        "missing_hours": missing_hours,
        "coverage_pct": 100 * present / expected if expected else 100,
        "raw_export_kwh": raw_export,
        "raw_import_kwh": raw_import,
        "netted_export_kwh": sum(p.export_kwh for p in points),
        "netted_import_kwh": sum(p.import_kwh for p in points),
        "codes": codes,
    }
    return points, meta


def simulate(
    points: Iterable[HourlyPoint],
    capacity_kwh: float,
    min_soc_pct: float = 10.0,
    roundtrip_efficiency_pct: float = 90.0,
    max_charge_kw: float = 10.0,
    max_discharge_kw: float = 10.0,
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
        charge_from_ac = min(surplus, max_charge_kw, room / charge_eff if charge_eff else 0.0)
        soc += charge_from_ac * charge_eff
        captured += charge_from_ac
        remain_export += surplus - charge_from_ac

        available_ac = max((soc - min_soc) * discharge_eff, 0.0)
        discharge_to_load = min(demand, max_discharge_kw, available_ac)
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


def choose_combined_recommendation(results: list[SimulationResult], technical: SimulationResult, economic: SimulationResult) -> SimulationResult:
    """Transparent prototype-regel.

    Vi anbefaler ikke større end det tekniske sweet spot. Blandt størrelserne op til
    sweet spot vælges den størrelse, der har bedst balance mellem teknisk dækning og
    økonomisk effektivitet. Begge dele normaliseres mod bedste værdi og vægtes 50/50.
    Reglen skal kalibreres mod DSS' faglige cases, før den bruges som endeligt facit.
    """
    eligible = [r for r in results if r.capacity_kwh <= technical.capacity_kwh + 1e-9]
    max_avoided = max((r.avoided_grid_import_kwh for r in eligible), default=1.0) or 1.0
    max_econ_eff = max((r.value_per_1000_dkk_price for r in eligible), default=1.0) or 1.0
    scored = []
    for r in eligible:
        tech_score = r.avoided_grid_import_kwh / max_avoided
        econ_score = r.value_per_1000_dkk_price / max_econ_eff
        score = 0.5 * tech_score + 0.5 * econ_score
        scored.append((score, -r.capacity_kwh, r))
    recommendation = max(scored, key=lambda x: (x[0], x[1]))[2]
    recommendation.combined_recommended = True
    return recommendation
