from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from xlsx_reader import read_first_sheet
from battery_engine import (
    parse_energinet_rows,
    simulate_products,
    choose_technical_recommendation,
    choose_economic_recommendation,
    choose_combined_recommendation,
)
from battery_catalog import brands, models_for_brand, products_for

BRAND_COLOR = "#EC8A13"

st.set_page_config(page_title="Batteriberegner", page_icon="🔋", layout="wide")
st.markdown(
    f"""
<style>
.block-container {{max-width: 1280px; padding-top: 2rem;}}
[data-testid="stMetricValue"] {{font-weight: 700;}}
.reco {{border: 2px solid {BRAND_COLOR}; border-radius: 16px; padding: 22px; background: rgba(236,138,19,.06);}}
.secondary {{border:1px solid #ddd;border-radius:14px;padding:16px;height:100%;}}
.small {{color:#666;font-size:.9rem}}
</style>
""",
    unsafe_allow_html=True,
)

st.title("🔋 Batteriberegner")
st.caption("Dimensionering ud fra kundens faktiske timeværdier fra Energinet/ElOverblik")

uploaded = st.file_uploader("Upload kundens Excel-fil", type=["xlsx"])

with st.sidebar:
    st.header("Batteri og økonomi")
    selected_brand = st.selectbox("Batterimærke", brands())
    selected_model = st.selectbox("Batteriserie/model", models_for_brand(selected_brand))
    selected_products = products_for(selected_brand, selected_model)
    sizes_text = " · ".join(f"{p.capacity_kwh:g}" for p in selected_products)
    st.caption(f"Tilgængelige størrelser: {sizes_text} kWh")

    buy_price = st.number_input("Købspris strøm (kr./kWh)", 0.0, 10.0, 2.20, 0.05)
    sell_price = st.number_input("Salgspris overskudsstrøm (kr./kWh)", 0.0, 10.0, 0.40, 0.05)
    st.divider()
    rte = st.slider("Round-trip virkningsgrad", 70, 100, 90, 1)
    min_soc = st.slider("Minimum SOC", 0, 30, 10, 1)
    threshold = st.slider(
        "Teknisk knækpunkt-følsomhed",
        10,
        80,
        35,
        5,
        help="Lavere værdi accepterer typisk større batterier før kurven vurderes at være fladet ud.",
    )
    balance_capture = st.slider(
        "Minimum teknisk udbytte for balance",
        70,
        95,
        85,
        5,
        help="Anbefalet balance skal opnå mindst denne andel af netbesparelsen ved det tekniske sweet spot. Økonomien vælger derefter blandt de kvalificerede størrelser.",
    )
    st.caption("Lade-/afladeeffekt er endnu ikke indregnet. Simulationen vurderer foreløbigt kapacitet og økonomi.")

if not uploaded:
    st.info("Upload en .xlsx-fil for at starte analysen.")
    st.stop()

try:
    rows = read_first_sheet(uploaded.getvalue())
    points, meta = parse_energinet_rows(rows)
except Exception as e:
    st.error(f"Filen kunne ikke analyseres: {e}")
    st.stop()

st.subheader("1. Datakontrol")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Periode", f"{meta['start']:%d.%m.%Y} – {meta['end']:%d.%m.%Y}")
c2.metric("Datadækning", f"{meta['coverage_pct']:.1f} %")
c3.metric("Leveret til net (D06)", f"{meta['raw_export_kwh']:,.0f} kWh".replace(",", "."))
c4.metric("Forbrugt fra net (D07)", f"{meta['raw_import_kwh']:,.0f} kWh".replace(",", "."))
if meta["missing_hours"]:
    st.warning(
        f"D06 og D07 overlapper i {meta['coverage_pct']:.1f} % af den forventede periode. "
        f"Der mangler ca. {meta['missing_hours']} timer med begge retninger. Resultatet bør tolkes med forsigtighed."
    )
else:
    st.success("D06 og D07 dækker hele den analyserede periode time for time.")

with st.expander("Importdiagnose"):
    st.write(
        f"**Genkendt dato/tid:** `{meta['column_mapping']['date']}`  \n"
        f"**Genkendt energimængde:** `{meta['column_mapping']['volume']}`  \n"
        f"**Genkendt målepunktstype:** `{meta['column_mapping']['code']}`"
    )
    code_rows = []
    for code in sorted(meta["codes"]):
        code_rows.append(
            {
                "Kode": code,
                "Antal værdier": meta["codes"][code],
                "Sum kWh": round(meta["code_kwh"].get(code, 0.0), 1),
                "Bruges i beregningen": "Ja" if code in ("D06", "D07") else "Nej",
            }
        )
    st.dataframe(code_rows, use_container_width=True, hide_index=True)
    st.caption("Målepunkts-ID og øvrige identifikationsfelter bruges ikke i beregningen.")

results = simulate_products(
    points,
    selected_products,
    buy_price_dkk_kwh=buy_price,
    sell_price_dkk_kwh=sell_price,
    min_soc_pct=min_soc,
    roundtrip_efficiency_pct=rte,
)
technical = choose_technical_recommendation(results, threshold / 100)
economic = choose_economic_recommendation(results)
combined = choose_combined_recommendation(results, technical, economic, min_technical_capture_fraction=balance_capture / 100)

st.subheader("2. Sweet spots og anbefalet balance")
col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(
        f"""<div class="secondary"><div class="small">TEKNISK SWEET SPOT</div>
    <div style="font-size:2rem;font-weight:800">{technical.capacity_kwh:g} kWh</div>
    <div>Størrelsen før marginaludnyttelsen falder tydeligt.</div></div>""",
        unsafe_allow_html=True,
    )
with col2:
    st.markdown(
        f"""<div class="secondary"><div class="small">ØKONOMISK EFFEKTIVITET</div>
    <div style="font-size:2rem;font-weight:800">{economic.capacity_kwh:g} kWh</div>
    <div>Højeste værdi i måleperioden pr. 1.000 kr. batteripris.</div></div>""",
        unsafe_allow_html=True,
    )
with col3:
    st.markdown(
        f"""<div class="reco"><div class="small">ANBEFALET BALANCE</div>
    <div style="font-size:2rem;font-weight:800">{combined.capacity_kwh:g} kWh</div>
    <div>Økonomisk stærkeste størrelse, som samtidig opnår mindst den valgte andel af det tekniske potentiale.</div></div>""",
        unsafe_allow_html=True,
    )

next_result = None
for i, r in enumerate(results):
    if abs(r.capacity_kwh - combined.capacity_kwh) < 1e-9 and i + 1 < len(results):
        next_result = results[i + 1]
        break

technical_capture = (
    100 * combined.avoided_grid_import_kwh / technical.avoided_grid_import_kwh
    if technical.avoided_grid_import_kwh > 0 else 100.0
)
why_text = (
    f"Hvorfor {combined.capacity_kwh:g} kWh? Den opnår {technical_capture:.1f} % af den netbesparelse, "
    f"som det tekniske sweet spot på {technical.capacity_kwh:g} kWh giver, og er samtidig den økonomisk "
    f"mest effektive af de størrelser, der når mindst {balance_capture} % af det tekniske potentiale."
)
if next_result is not None:
    why_text += (
        f" Næste trin ({next_result.capacity_kwh:g} kWh) koster {next_result.marginal_price_dkk:,.0f} kr. mere "
        f"og giver {next_result.marginal_avoided_import_kwh:.0f} kWh ekstra reduceret netkøb i måleperioden."
    )
st.info(why_text.replace(",", "."))

st.caption(
    "Balance-reglen prioriterer nu kundens tekniske behov først. En størrelse skal nå minimumskravet til teknisk udbytte; "
    "derefter vælger økonomien mellem de kvalificerede størrelser. Lade-/afladeeffekt tilføjes senere, når effektdata er komplette."
)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Undgået netkøb", f"{combined.avoided_grid_import_kwh:,.0f} kWh".replace(",", "."))
m2.metric("Økonomisk værdi i perioden", f"{combined.economic_value_dkk:,.0f} kr.".replace(",", "."))
m3.metric("Batteripris", f"{combined.price_dkk:,.0f} kr.".replace(",", "."))
m4.metric("Ækvivalente cyklusser", f"{combined.cycles_equivalent:.0f}")

st.subheader("3. Teknisk sammenligning")
fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=[r.capacity_kwh for r in results],
        y=[r.avoided_grid_import_kwh for r in results],
        mode="lines+markers",
        name="Undgået netkøb",
        line=dict(color=BRAND_COLOR, width=4),
        marker=dict(size=9),
    )
)
# Den stiplede linje markerer den praktiske anbefaling, ikke det tekniske maksimum.
fig.add_vline(
    x=combined.capacity_kwh,
    line_dash="dash",
    line_color=BRAND_COLOR,
    annotation_text=f"Anbefalet balance: {combined.capacity_kwh:g} kWh",
)
fig.update_layout(
    xaxis_title="Batteristørrelse (kWh)",
    yaxis_title="Undgået netkøb i måleperioden (kWh)",
    margin=dict(l=20, r=20, t=30, b=20),
    height=420,
)
st.plotly_chart(fig, use_container_width=True)

st.subheader("4. Økonomisk sammenligning")
fig2 = go.Figure()
fig2.add_trace(
    go.Bar(
        x=[f"{r.capacity_kwh:g} kWh" for r in results],
        y=[r.economic_value_dkk for r in results],
        name="Økonomisk værdi",
        marker_color=BRAND_COLOR,
    )
)
fig2.update_layout(
    xaxis_title=f"{selected_brand} {selected_model}",
    yaxis_title="Økonomisk værdi i måleperioden (kr.)",
    margin=dict(l=20, r=20, t=20, b=20),
    height=390,
)
st.plotly_chart(fig2, use_container_width=True)

rows_for_table = []
for r in results:
    labels = []
    if r.technical_recommended:
        labels.append("Teknisk")
    if r.economic_recommended:
        labels.append("Økonomi")
    if r.combined_recommended:
        labels.append("Balance")
    rows_for_table.append(
        {
            "Batteri": f"{r.capacity_kwh:g} kWh" + (" ★" if r.combined_recommended else ""),
            "Pris": f"{r.price_dkk:,.0f} kr.".replace(",", "."),
            "Undgået netkøb": f"{r.avoided_grid_import_kwh:,.0f} kWh".replace(",", "."),
            "Ekstra sparet netkøb": "—"
            if not r.added_capacity_kwh
            else f"+{r.marginal_avoided_import_kwh:,.0f} kWh".replace(",", "."),
            "Marginal udnyttelse": "—"
            if not r.added_capacity_kwh
            else f"{r.marginal_per_added_kwh:.1f} kWh/kWh",
            "Teknisk udbytte": f"{(100 * r.avoided_grid_import_kwh / technical.avoided_grid_import_kwh if technical.avoided_grid_import_kwh else 100):.1f} %",
            "Økonomisk værdi": f"{r.economic_value_dkk:,.0f} kr.".replace(",", "."),
            "Merpris": "—"
            if not r.added_capacity_kwh
            else f"+{r.marginal_price_dkk:,.0f} kr.".replace(",", "."),
            "Ekstra økonomisk værdi": "—"
            if not r.added_capacity_kwh
            else f"+{r.marginal_economic_value_dkk:,.0f} kr.".replace(",", "."),
            "Markering": ", ".join(labels) if labels else "",
        }
    )
st.dataframe(rows_for_table, use_container_width=True, hide_index=True)
st.caption(
    "Marginal udnyttelse = ekstra reduceret netkøb pr. ekstra kWh installeret batterikapacitet sammenlignet med størrelsen lige under."
)

st.subheader("5. Sådan beregnes økonomien")
st.info(
    f"Standard lige nu: køb {buy_price:.2f} kr./kWh og salg {sell_price:.2f} kr./kWh. "
    "Økonomisk værdi = undgået køb fra nettet × købspris − den energi, som batteriet opsamler fra overskuddet × salgspris. "
    "Dermed reducerer batteritabet automatisk den økonomiske gevinst."
)

st.subheader("6. Forbehold")
st.caption(
    "Resultaterne gælder den uploadede måleperiode. Hvis filen ikke dækker et helt år, vises der bevidst ikke en simpel årlig tilbagebetalingstid endnu, "
    "fordi solcelleproduktion er sæsonafhængig og lineær annualisering kan være misvisende. D06/D07 nettes konservativt inden for samme time. "
    "Lade-/afladeeffekt er endnu ikke indregnet, så resultatet er foreløbigt en kapacitets- og økonomidimensionering."
)
