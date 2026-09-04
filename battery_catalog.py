from __future__ import annotations

from battery_engine import BatteryProduct

# Batteridatabase v2.3
# Kilde: "Batteri - mærker, størrelse og pris.xlsx".
# Lade-/afladeeffekt er bevidst ikke indregnet endnu. Derfor står power-felterne som None.

BATTERY_CATALOG: list[BatteryProduct] = [
    BatteryProduct("Fronius", "Reserva", 6.3, 29900),
    BatteryProduct("Fronius", "Reserva", 9.5, 38800),
    BatteryProduct("Fronius", "Reserva", 12.6, 48800),
    BatteryProduct("Fronius", "Reserva", 15.8, 57900),

    BatteryProduct("BYD", "HVM", 8.3, 36900),
    BatteryProduct("BYD", "HVM", 11.0, 43900),
    BatteryProduct("BYD", "HVM", 13.8, 50900),
    BatteryProduct("BYD", "HVM", 16.6, 57900),
    BatteryProduct("BYD", "HVM", 19.3, 64900),
    BatteryProduct("BYD", "HVM", 22.1, 71900),

    BatteryProduct("BYD", "HVS", 5.1, 20900),
    BatteryProduct("BYD", "HVS", 7.7, 28600),
    BatteryProduct("BYD", "HVS", 10.2, 35900),
    BatteryProduct("BYD", "HVS", 12.8, 43800),

    BatteryProduct("KOSTAL", "Helivor", 6.4, 26500),
    BatteryProduct("KOSTAL", "Helivor", 9.6, 34900),
    BatteryProduct("KOSTAL", "Helivor", 12.8, 43250),
    BatteryProduct("KOSTAL", "Helivor", 16.0, 52300),
    BatteryProduct("KOSTAL", "Helivor", 19.2, 62600),
    BatteryProduct("KOSTAL", "Helivor", 22.4, 71600),
    BatteryProduct("KOSTAL", "Helivor", 25.6, 80700),

    BatteryProduct("Solplanet", "G2", 5.1, 19900),
    BatteryProduct("Solplanet", "G2", 7.7, 26300),
    BatteryProduct("Solplanet", "G2", 10.2, 33200),
    BatteryProduct("Solplanet", "G2", 12.8, 40100),
    BatteryProduct("Solplanet", "G2", 15.4, 46900),
    BatteryProduct("Solplanet", "G2", 17.9, 53700),
    BatteryProduct("Solplanet", "G2", 20.5, 60600),

    BatteryProduct("Solplanet", "G2 Pro", 7.7, 26300),
    BatteryProduct("Solplanet", "G2 Pro", 10.2, 33200),
    BatteryProduct("Solplanet", "G2 Pro", 12.8, 40100),
    BatteryProduct("Solplanet", "G2 Pro", 15.4, 46900),
    BatteryProduct("Solplanet", "G2 Pro", 17.9, 53700),
    BatteryProduct("Solplanet", "G2 Pro", 20.5, 60600),

    BatteryProduct("Solplanet", "G2-E", 5.0, 12000),
    BatteryProduct("Solplanet", "G2-E", 10.0, 22200),
    BatteryProduct("Solplanet", "G2-E", 15.0, 33300),
    BatteryProduct("Solplanet", "G2-E", 20.0, 44100),
    BatteryProduct("Solplanet", "G2-E", 30.0, 66400),
    BatteryProduct("Solplanet", "G2-E", 40.0, 88100),
]


def brands() -> list[str]:
    return list(dict.fromkeys(p.brand for p in BATTERY_CATALOG))


def models_for_brand(brand: str) -> list[str]:
    return list(dict.fromkeys(p.model for p in BATTERY_CATALOG if p.brand == brand))


def products_for(brand: str, model: str) -> list[BatteryProduct]:
    return sorted(
        [p for p in BATTERY_CATALOG if p.brand == brand and p.model == model],
        key=lambda p: p.capacity_kwh,
    )
