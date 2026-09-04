from __future__ import annotations

from io import BytesIO
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from datetime import timedelta
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    Flowable, KeepTogether,
)

BRAND = colors.HexColor('#EC8A13')
DARK = colors.HexColor('#232323')
MID = colors.HexColor('#666666')
LIGHT = colors.HexColor('#F7F7F7')
BORDER = colors.HexColor('#DDDDDD')
PALE_ORANGE = colors.HexColor('#FFF4E6')

# Unicode-font til danske tegn. Fonten bruges kun ved PDF-generering og deles ikke som fil.
pdfmetrics.registerFont(TTFont('DSSSans', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DSSSans-Bold', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))


def _dk_number(value: float, decimals: int = 0) -> str:
    if decimals == 0:
        s = f"{value:,.0f}"
    else:
        s = f"{value:,.{decimals}f}"
    return s.replace(',', 'X').replace('.', ',').replace('X', '.')


class BatteryCurve(Flowable):
    def __init__(self, results, recommended_kwh: float, range_min: float, range_max: float,
                 width=165*mm, height=62*mm):
        super().__init__()
        self.results = list(results)
        self.recommended_kwh = recommended_kwh
        self.range_min = range_min
        self.range_max = range_max
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        left, bottom = 15*mm, 12*mm
        plot_w = self.width - 25*mm
        plot_h = self.height - 20*mm
        xs = [r.capacity_kwh for r in self.results]
        ys = [r.avoided_grid_import_kwh for r in self.results]
        if not xs or not ys:
            return
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = 0.0, max(ys) * 1.08
        if xmax == xmin:
            xmax += 1
        if ymax <= 0:
            ymax = 1

        def px(x):
            return left + (x - xmin) / (xmax - xmin) * plot_w
        def py(y):
            return bottom + (y - ymin) / (ymax - ymin) * plot_h

        # Relevant recommendation range
        if self.range_max > self.range_min:
            c.setFillColor(PALE_ORANGE)
            c.rect(px(self.range_min), bottom, px(self.range_max)-px(self.range_min), plot_h, stroke=0, fill=1)

        # Grid + y labels
        c.setFont('DSSSans', 7)
        c.setFillColor(MID)
        for i in range(5):
            yv = ymax * i / 4
            yy = py(yv)
            c.setStrokeColor(colors.HexColor('#E8E8E8'))
            c.setLineWidth(0.5)
            c.line(left, yy, left+plot_w, yy)
            c.drawRightString(left-2*mm, yy-2, _dk_number(yv))

        # Axis titles
        c.setFillColor(MID)
        c.setFont('DSSSans', 7)
        c.drawCentredString(left + plot_w/2, 1.5*mm, 'Batteristørrelse (kWh)')
        c.saveState()
        c.translate(3*mm, bottom + plot_h/2)
        c.rotate(90)
        c.drawCentredString(0, 0, 'Undgået netkøb (kWh)')
        c.restoreState()

        # Curve
        c.setStrokeColor(BRAND)
        c.setLineWidth(2.2)
        path = c.beginPath()
        path.moveTo(px(xs[0]), py(ys[0]))
        for x, y in zip(xs[1:], ys[1:]):
            path.lineTo(px(x), py(y))
        c.drawPath(path, stroke=1, fill=0)

        # Points + x labels
        for x, y in zip(xs, ys):
            c.setFillColor(BRAND)
            c.circle(px(x), py(y), 2.2, stroke=0, fill=1)
            c.setFillColor(MID)
            c.setFont('DSSSans', 6.5)
            c.drawCentredString(px(x), bottom-4*mm, f"{x:g}")

        # Recommended line
        rx = px(self.recommended_kwh)
        c.setStrokeColor(BRAND)
        c.setDash(4, 3)
        c.setLineWidth(1.2)
        c.line(rx, bottom, rx, bottom+plot_h)
        c.setDash()
        c.setFillColor(DARK)
        c.setFont('DSSSans-Bold', 7)
        c.drawString(min(rx+2*mm, left+plot_w-38*mm), bottom+plot_h+2*mm,
                     f"Anbefalet: {self.recommended_kwh:g} kWh")


def generate_customer_report(*, brand: str, model: str, results: Sequence,
                             technical, economic, combined, meta: dict,
                             buy_price: float, sell_price: float,
                             roundtrip_efficiency_pct: float, min_soc_pct: float,
                             balance_capture_pct: float,
                             range_min: float, range_max: float) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=18*mm, leftMargin=18*mm,
        topMargin=17*mm, bottomMargin=17*mm,
        title=f"Batterianbefaling - {brand} {model}",
        author="Dansk Solcelleservice",
    )

    styles = getSampleStyleSheet()
    title = ParagraphStyle('TitleDSS', parent=styles['Title'], fontName='DSSSans-Bold',
                           fontSize=23, leading=27, textColor=DARK, spaceAfter=4*mm)
    h1 = ParagraphStyle('H1DSS', parent=styles['Heading1'], fontName='DSSSans-Bold',
                        fontSize=14, leading=18, textColor=DARK, spaceBefore=3*mm, spaceAfter=2*mm)
    body = ParagraphStyle('BodyDSS', parent=styles['BodyText'], fontName='DSSSans',
                          fontSize=9.5, leading=14, textColor=DARK)
    small = ParagraphStyle('SmallDSS', parent=body, fontSize=8, leading=11, textColor=MID)
    hero_label = ParagraphStyle('HeroLabel', parent=small, fontName='DSSSans-Bold',
                                fontSize=8, textColor=MID, alignment=TA_LEFT)
    hero_value = ParagraphStyle('HeroValue', parent=body, fontName='DSSSans-Bold',
                                fontSize=23, leading=26, textColor=BRAND)
    card_value = ParagraphStyle('CardValue', parent=body, fontName='DSSSans-Bold',
                                fontSize=14, leading=17, textColor=DARK, alignment=TA_CENTER)
    card_label = ParagraphStyle('CardLabel', parent=small, alignment=TA_CENTER)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(18*mm, 13*mm, A4[0]-18*mm, 13*mm)
        canvas.setFont('DSSSans', 7.5)
        canvas.setFillColor(MID)
        canvas.drawString(18*mm, 8.5*mm, 'Dansk Solcelleservice - Batterianalyse baseret på historiske timedata')
        canvas.drawRightString(A4[0]-18*mm, 8.5*mm, f'Side {doc.page}')
        canvas.restoreState()

    story = []
    story.append(Paragraph('DANSK SOLCELLESERVICE', ParagraphStyle('BrandHead', parent=small, fontName='DSSSans-Bold', textColor=BRAND, fontSize=9)))
    story.append(Paragraph('Batterianbefaling', title))
    story.append(Paragraph(
        f"Analyse af historiske timedata fra <b>{meta['start']:%d.%m.%Y}</b> til <b>{(meta['end'] - timedelta(hours=1)):%d.%m.%Y}</b>. "
        "Formålet er at finde en batteristørrelse, der giver en god balance mellem faktisk udnyttelse og investering.", body))
    story.append(Spacer(1, 5*mm))

    if range_max > range_min:
        range_text = f"{range_min:g}-{range_max:g} kWh"
    else:
        range_text = f"{range_min:g} kWh"

    hero = Table([
        [Paragraph('ANBEFALET BATTERI', hero_label), Paragraph('RELEVANT KAPACITETSOMRÅDE', hero_label)],
        [Paragraph(f'{brand} {model}<br/><font size="23"><b>{combined.capacity_kwh:g} kWh</b></font>', hero_value),
         Paragraph(f'<b>{range_text}</b>', ParagraphStyle('Range', parent=hero_value, fontSize=19, leading=23, textColor=DARK))],
    ], colWidths=[96*mm, 72*mm])
    hero.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),PALE_ORANGE), ('BOX',(0,0),(-1,-1),1.2,BRAND),
        ('INNERGRID',(0,0),(-1,-1),0,PALE_ORANGE), ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),6*mm), ('RIGHTPADDING',(0,0),(-1,-1),6*mm),
        ('TOPPADDING',(0,0),(-1,-1),4*mm), ('BOTTOMPADDING',(0,0),(-1,-1),4*mm),
    ]))
    story.append(hero)
    story.append(Spacer(1, 5*mm))

    technical_capture = 100 * combined.avoided_grid_import_kwh / technical.avoided_grid_import_kwh if technical.avoided_grid_import_kwh else 100
    cards = Table([
        [Paragraph(_dk_number(combined.avoided_grid_import_kwh) + ' kWh', card_value),
         Paragraph(_dk_number(combined.economic_value_dkk) + ' kr.', card_value),
         Paragraph(_dk_number(combined.price_dkk) + ' kr.', card_value),
         Paragraph(f'{technical_capture:.1f} %'.replace('.', ','), card_value)],
        [Paragraph('Undgået netkøb i perioden', card_label),
         Paragraph('Beregnet økonomisk værdi', card_label),
         Paragraph('Batteripris', card_label),
         Paragraph('Af teknisk sweet spot', card_label)]
    ], colWidths=[42*mm]*4)
    cards.setStyle(TableStyle([
        ('BOX',(0,0),(-1,-1),0.7,BORDER), ('INNERGRID',(0,0),(-1,-1),0.7,BORDER),
        ('BACKGROUND',(0,0),(-1,-1),colors.white), ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,0),4*mm), ('BOTTOMPADDING',(0,1),(-1,1),3*mm),
    ]))
    story.append(cards)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph('Hvorfor denne størrelse?', h1))
    next_result = None
    for i, r in enumerate(results):
        if abs(r.capacity_kwh - combined.capacity_kwh) < 1e-9 and i+1 < len(results):
            next_result = results[i+1]
            break
    why = (
        f"{combined.capacity_kwh:g} kWh opnår <b>{technical_capture:.1f} %</b> af den netbesparelse, som det tekniske sweet spot "
        f"på {technical.capacity_kwh:g} kWh giver. Dermed ligger batteriet i den teknisk relevante målzone uden at betale for unødvendigt meget ekstra kapacitet."
    )
    if next_result is not None:
        why += (
            f" Næste størrelse, {next_result.capacity_kwh:g} kWh, koster <b>{_dk_number(next_result.marginal_price_dkk)} kr. mere</b> "
            f"og reducerer netkøbet med yderligere <b>{_dk_number(next_result.marginal_avoided_import_kwh)} kWh</b> i den analyserede periode."
        )
    story.append(Paragraph(why, body))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph('Udnyttelse af batteristørrelser', h1))
    story.append(BatteryCurve(results, combined.capacity_kwh, range_min, range_max))
    story.append(Paragraph(
        'Kurven viser, hvor meget netkøb de forskellige batteristørrelser historisk kunne have reduceret. '
        'Når kurven flader ud, giver ekstra batterikapacitet stadig en gevinst, men gevinsten pr. ekstra kWh batteri bliver mindre.', small))

    story.append(PageBreak())
    story.append(Paragraph('Sammenligning af batteristørrelser', title))
    story.append(Paragraph(
        f"Alle størrelser i {brand} {model}-serien er simuleret mod den samme historiske energiprofil. "
        "Stjernen markerer den anbefalede balance.", body))
    story.append(Spacer(1, 4*mm))

    table_data = [['Batteri', 'Pris', 'Undgået netkøb', 'Teknisk udbytte', 'Økonomisk værdi']]
    for r in results:
        tech_pct = 100 * r.avoided_grid_import_kwh / technical.avoided_grid_import_kwh if technical.avoided_grid_import_kwh else 100
        name = f"{r.capacity_kwh:g} kWh" + (' *' if abs(r.capacity_kwh-combined.capacity_kwh)<1e-9 else '')
        table_data.append([
            name,
            _dk_number(r.price_dkk) + ' kr.',
            _dk_number(r.avoided_grid_import_kwh) + ' kWh',
            f"{tech_pct:.1f} %".replace('.', ','),
            _dk_number(r.economic_value_dkk) + ' kr.',
        ])
    comparison = Table(table_data, colWidths=[28*mm, 31*mm, 40*mm, 35*mm, 36*mm], repeatRows=1)
    comparison.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),DARK), ('TEXTCOLOR',(0,0),(-1,0),colors.white),
        ('FONTNAME',(0,0),(-1,0),'DSSSans-Bold'), ('FONTNAME',(0,1),(-1,-1),'DSSSans'),
        ('FONTSIZE',(0,0),(-1,-1),8), ('ALIGN',(1,1),(-1,-1),'RIGHT'),
        ('GRID',(0,0),(-1,-1),0.5,BORDER), ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,LIGHT]),
        ('TOPPADDING',(0,0),(-1,-1),2.2*mm), ('BOTTOMPADDING',(0,0),(-1,-1),2.2*mm),
    ]))
    # Highlight recommended row
    for idx, r in enumerate(results, start=1):
        if abs(r.capacity_kwh-combined.capacity_kwh)<1e-9:
            comparison.setStyle(TableStyle([('BACKGROUND',(0,idx),(-1,idx),PALE_ORANGE), ('FONTNAME',(0,idx),(-1,idx),'DSSSans-Bold')]))
            break
    story.append(comparison)
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph('Forudsætninger for beregningen', h1))
    assumptions = [
        ['Kobspris på strom', f'{buy_price:.2f} kr./kWh'.replace('.', ',')],
        ['Salgspris på overskudsstrom', f'{sell_price:.2f} kr./kWh'.replace('.', ',')],
        ['Round-trip virkningsgrad', f'{roundtrip_efficiency_pct:.0f} %'],
        ['Minimum SOC', f'{min_soc_pct:.0f} %'],
        ['Teknisk mål for balance', f'{balance_capture_pct:.0f} % med blød målzone'],
        ['Datadækning', f"{meta['coverage_pct']:.1f} %".replace('.', ',')],
        ['D06 - leveret til nettet', _dk_number(meta['raw_export_kwh']) + ' kWh'],
        ['D07 - hentet fra nettet', _dk_number(meta['raw_import_kwh']) + ' kWh'],
    ]
    at = Table(assumptions, colWidths=[75*mm, 75*mm])
    at.setStyle(TableStyle([
        ('GRID',(0,0),(-1,-1),0.5,BORDER), ('ROWBACKGROUNDS',(0,0),(-1,-1),[colors.white,LIGHT]),
        ('FONTNAME',(0,0),(0,-1),'DSSSans-Bold'), ('FONTNAME',(1,0),(1,-1),'DSSSans'),
        ('FONTSIZE',(0,0),(-1,-1),8.5), ('TOPPADDING',(0,0),(-1,-1),1.8*mm), ('BOTTOMPADDING',(0,0),(-1,-1),1.8*mm),
    ]))
    story.append(at)
    story.append(Spacer(1, 3*mm))

    story.append(Paragraph('Vigtigt at vide', h1))
    story.append(Paragraph(
        'Beregningen er en historisk simulering baseret på kundens timedata. Resultatet er ikke en garanti for fremtidig besparelse, da forbrug, '
        'solproduktion, elpriser og anvendelsesmonster kan aendre sig. Hvis måleperioden ikke dækker et helt ar, er den økonomiske værdi kun angivet '
        'for den faktiske måleperiode. Lade- og afladeeffekt samt inverterbegrænsninger er endnu ikke indregnet i denne version.', body))
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph(
        '<b>Konklusion:</b> Rapporten er et datadrevet beslutningsgrundlag til dimensionering. Den endelige løsning bør altid kontrolleres i forhold til '
        'det konkrete solcelleanlæg, inverter, installation og kundens fremtidige behov.', body))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
