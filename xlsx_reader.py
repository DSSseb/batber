from __future__ import annotations
from datetime import datetime, timedelta
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from pathlib import Path
from typing import BinaryIO

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKGREL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _col_index(ref: str) -> int:
    letters = "".join(c for c in ref if c.isalpha())
    n = 0
    for c in letters:
        n = n * 26 + (ord(c.upper()) - 64)
    return n - 1


def _excel_date(value: float) -> datetime:
    return datetime(1899, 12, 30) + timedelta(days=float(value))


def _open_zip(source: str | Path | bytes | BinaryIO) -> ZipFile:
    if isinstance(source, (str, Path)):
        return ZipFile(source)
    if isinstance(source, bytes):
        return ZipFile(BytesIO(source))
    return ZipFile(source)


def _load_shared_strings(z: ZipFile) -> list[str]:
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
    return shared


def _load_date_styles(z: ZipFile) -> set[int]:
    date_styles: set[int] = set()
    if "xl/styles.xml" not in z.namelist():
        return date_styles
    root = ET.fromstring(z.read("xl/styles.xml"))
    custom: dict[int, str] = {}
    numfmts = root.find(NS + "numFmts")
    if numfmts is not None:
        for n in numfmts.findall(NS + "numFmt"):
            custom[int(n.attrib["numFmtId"])] = n.attrib.get("formatCode", "")
    built_in_date = set(range(14, 23)) | {45, 46, 47}
    cellxfs = root.find(NS + "cellXfs")
    if cellxfs is not None:
        for i, xf in enumerate(cellxfs.findall(NS + "xf")):
            fmt_id = int(xf.attrib.get("numFmtId", "0"))
            fmt = custom.get(fmt_id, "").lower()
            if fmt_id in built_in_date or any(k in fmt for k in ("yy", "dd", "hh", "ss")):
                date_styles.add(i)
    return date_styles


def _first_sheet_path(z: ZipFile) -> str:
    workbook = ET.fromstring(z.read("xl/workbook.xml"))
    relroot = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rels = {r.attrib["Id"]: r.attrib["Target"] for r in relroot.findall(PKGREL + "Relationship")}
    sheets = workbook.find(NS + "sheets")
    if sheets is None or sheets.find(NS + "sheet") is None:
        raise ValueError("Excel-filen indeholder ingen regneark.")
    sheet = sheets.find(NS + "sheet")
    target = rels[sheet.attrib[REL + "id"]]
    if target.startswith("/"):
        return target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return "xl/" + target


def _cell_value(c: ET.Element, shared: list[str], date_styles: set[int]) -> object:
    typ = c.attrib.get("t")
    style = int(c.attrib.get("s", "0"))
    v = c.find(NS + "v")
    if typ == "inlineStr":
        inline = c.find(NS + "is")
        return "".join(t.text or "" for t in inline.iter(NS + "t")) if inline is not None else ""
    if v is None:
        return None
    raw = v.text or ""
    if typ == "s":
        return shared[int(raw)]
    if typ == "b":
        return raw == "1"
    if typ in ("str", "e"):
        return raw
    try:
        number = float(raw)
        value: object = int(number) if number.is_integer() else number
        if style in date_styles:
            value = _excel_date(number)
        return value
    except ValueError:
        return raw


def read_first_sheet(source: str | Path | bytes | BinaryIO, *, empty_tail_limit: int = 250) -> list[list[object]]:
    """Read the first tabular worksheet from .xlsx using streaming XML.

    Some exports contain formatting on all 1,048,576 Excel rows. After real data has
    started, this reader stops after a long run of rows with no actual values.
    """
    with _open_zip(source) as z:
        shared = _load_shared_strings(z)
        date_styles = _load_date_styles(z)
        sheet_path = _first_sheet_path(z)
        rows: list[list[object]] = []
        empty_run = 0
        saw_meaningful = False
        with z.open(sheet_path) as stream:
            for _, elem in ET.iterparse(stream, events=("end",)):
                if elem.tag != NS + "row":
                    continue
                cells: dict[int, object] = {}
                max_col = -1
                nonempty_count = 0
                has_datetime = False
                for c in elem.findall(NS + "c"):
                    idx = _col_index(c.attrib.get("r", "A1"))
                    value = _cell_value(c, shared, date_styles)
                    if value not in (None, ""):
                        nonempty_count += 1
                        has_datetime = has_datetime or isinstance(value, datetime)
                    cells[idx] = value
                    max_col = max(max_col, idx)

                # Energinet rows contain several populated columns. Some exported files
                # accidentally fill the ID/customer column all the way to row 1,048,576;
                # those one-cell rows are a formatting tail, not meter data.
                rich_row = nonempty_count >= 2 or has_datetime
                if nonempty_count:
                    rows.append([cells.get(i) for i in range(max_col + 1)])
                if rich_row:
                    saw_meaningful = True
                    empty_run = 0
                elif saw_meaningful:
                    empty_run += 1
                    if empty_run >= empty_tail_limit:
                        # Remove the tail rows we temporarily appended.
                        del rows[-empty_run:]
                        elem.clear()
                        break
                elem.clear()
        return rows
