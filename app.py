from __future__ import annotations
import streamlit as st
import plotly.graph_objects as go
from xlsx_reader import read_first_sheet
from battery_engine import parse_energinet_rows, simulate_sizes, choose_recommendation

BRAND = "#EC8A13"

st.set_page_config(page_title="Batteriberegner", page_icon="🔋", layout="wide")
st.markdown(f"""
<style>
.block-container {{max-width: 1250px; padding-top: 2rem;}}
[data-testid="stMetricValue"] {{font-weight: 700;}}
.reco {{border: 2px solid {BRAND}; border-radius: 16px; padding: 22px; background: rgba(236,138,19,.06);}}
.small {{color:#666;font-size:.9rem}}
</style>
""", unsafe_allow_html=True)

st.title("🔋 Batteriberegner")
st.caption("Dimensionering ud fra kundens faktiske timeværdier fra Energinet/ElOverblik")

uploaded = st.file_uploader("Upload kundens Excel-fil", type=["xlsx"])

with st.sidebar:
    st.header("Batteriindstillinger")
    system = st.selectbox("Batteriserie", ["Fri simulering", "Fronius Reserva (3,15 kWh moduler)"])
    if system == "Fronius Reserva (3,15 kWh moduler)":
        sizes = [6.3, 9.45, 12.6, 15.75, 18.9, 22.05, 25.2]
    else:
        raw = st.text_input("Størrelser (kWh)", "5, 7.5, 10, 12.5, 15, 20, 25, 30")
        try:
            sizes = [float(x.strip().replace(",", ".")) for x in raw.split(",")]
        except ValueError:
            st.error("Skriv størrelser adskilt med komma.")
            st.stop()
    rte = st.slider("Round-trip virkningsgrad", 70, 100, 90, 1)
    min_soc = st.slider("Minimum SOC", 0, 30, 10, 1)
    charge_kw = st.number_input("Maks. ladeeffekt (kW)", 1.0, 30.0, 10.0, 0.5)
    discharge_kw = st.number_input("Maks. afladeeffekt (kW)", 1.0, 30.0, 10.0, 0.5)
    threshold = st.slider("Knækpunkt-følsomhed", 10, 80, 35, 5, help="Lavere værdi anbefaler typisk et større batteri.")

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
    st.warning(f"Der mangler ca. {meta['missing_hours']} timer i perioden. Resultatet bør tolkes med forsigtighed.")
else:
    st.success("Tidsserien er sammenhængende i den analyserede periode.")

results = simulate_sizes(
    points, sizes,
    min_soc_pct=min_soc,
    roundtrip_efficiency_pct=rte,
    max_charge_kw=charge_kw,
    max_discharge_kw=discharge_kw,
)
recommended = choose_recommendation(results, threshold / 100)

st.subheader("2. Anbefaling")
st.markdown(f"""
<div class="reco">
<div class="small">ANBEFALET BATTERISTØRRELSE</div>
<div style="font-size:3rem;font-weight:800;line-height:1.1">{recommended.capacity_kwh:g} kWh</div>
<div style="margin-top:8px">Første tydelige knæk i den målte gevinstkurve med de valgte antagelser.</div>
</div>
""", unsafe_allow_html=True)

m1, m2, m3 = st.columns(3)
m1.metric("Undgået netkøb", f"{recommended.avoided_grid_import_kwh:,.0f} kWh".replace(",", "."))
m2.metric("Andel af netkøb dækket", f"{recommended.utilization_pct:.1f} %")
m3.metric("Ækvivalente cyklusser", f"{recommended.cycles_equivalent:.0f}")

st.subheader("3. Sammenligning af batteristørrelser")
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=[r.capacity_kwh for r in results],
    y=[r.avoided_grid_import_kwh for r in results],
    mode="lines+markers",
    name="Undgået netkøb",
    line=dict(color=BRAND, width=4),
    marker=dict(size=9),
))
fig.add_vline(x=recommended.capacity_kwh, line_dash="dash", line_color=BRAND,
              annotation_text=f"Anbefalet: {recommended.capacity_kwh:g} kWh")
fig.update_layout(xaxis_title="Batteristørrelse (kWh)", yaxis_title="Undgået netkøb i måleperioden (kWh)",
                  margin=dict(l=20,r=20,t=30,b=20), height=430)
st.plotly_chart(fig, use_container_width=True)

rows_for_table = []
for r in results:
    rows_for_table.append({
        "Batteri": f"{r.capacity_kwh:g} kWh" + (" ★" if r.recommended else ""),
        "Undgået netkøb": round(r.avoided_grid_import_kwh),
        "Ekstra gevinst vs. forrige": round(r.marginal_avoided_import_kwh),
        "Gevinst pr. ekstra kWh batteri": round(r.marginal_per_added_kwh, 1),
        "Dækket netkøb": f"{r.utilization_pct:.1f} %",
    })
st.dataframe(rows_for_table, use_container_width=True, hide_index=True)

st.subheader("4. Forbehold")
st.caption("Beregningen bruger D06 = leveret til net og D07 = forbrugt fra net. Inden simuleringen nettes køb og salg inden for samme time konservativt, fordi timeværdier ikke afslører rækkefølgen inden for timen. Resultatet er en teknisk dimensioneringsindikator – ikke en garanti for økonomisk tilbagebetaling.")
