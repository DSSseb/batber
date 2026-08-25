# Batteriberegner – prototype

Intern prototype til dimensionering af solcellebatterier ud fra Energinet/ElOverblik timeværdier.

## Hvad den gør
- uploader `.xlsx`
- finder `D06` (Leveret til net) og `D07` (Forbrugt fra net)
- kontrollerer dataperiode og manglende timer
- netter import/eksport konservativt pr. time
- simulerer batteriets SOC time for time
- tager højde for minimum SOC, round-trip virkningsgrad og lade-/afladeeffekt
- sammenligner flere batteristørrelser
- markerer et transparent knækpunkt som første anbefaling

## Start lokalt
1. Installer Python 3.11+.
2. Åbn terminalen i denne mappe.
3. Kør: `pip install -r requirements.txt`
4. Kør: `streamlit run app.py`
5. Browseren åbner værktøjet.

## Vigtigt om anbefalingen
Knækpunkt-reglen er foreløbig. Den er bevidst lagt separat i `choose_recommendation()` i `battery_engine.py`, så Dansk Solcelleservice kan kalibrere den efter den rådgivning, I bruger i praksis.

## Næste oplagte version
- konkrete batteriserier og produktpriser
- økonomisk gevinst i kr.
- typisk døgnprofil / månedsprofil
- kunderapport som PDF
- gemte analysesager
- login og intern hosting
