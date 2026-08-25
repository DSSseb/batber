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
    # Excel's 1900 date system, including its historical leap-year quirk.
    return datetime(1899, 12, 30) + timedelta(days=float(value))


def _open_zip(source: str | Path | bytes | BinaryIO) -> ZipFile:
    if isinstance(source, (str, Path)):
        return ZipFile(source)
    if isinstance(source, bytes):
        return ZipFile(BytesIO(source))
    return ZipFile(source)


def read_first_sheet(source: str | Path | bytes | BinaryIO) -> list[list[object]]:
    """Read the first worksheet from a basic .xlsx file using only Python stdlib.

    Supports shared strings, inline strings, booleans, numeric values and Excel dates.
    This is intentionally small and tailored to tabular Energinet exports.
    """
    with _open_zip(source) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(NS + "si"):
                shared.append("".join(t.text or "" for t in si.iter(NS + "t")))

        date_styles: set[int] = set()
        if "xl/styles.xml" in z.namelist():
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

        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        relroot = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rels = {r.attrib["Id"]: r.attrib["Target"] for r in relroot.findall(PKGREL + "Relationship")}
        sheet = workbook.find(NS + "sheets").find(NS + "sheet")
        target = rels[sheet.attrib[REL + "id"]]
        if target.startswith("/"):
            sheet_path = target.lstrip("/")
        elif target.startswith("xl/"):
            sheet_path = target
        else:
            sheet_path = "xl/" + target

        root = ET.fromstring(z.read(sheet_path))
        sheet_data = root.find(NS + "sheetData")
        if sheet_data is None:
            return []

        rows: list[list[object]] = []
        for row in sheet_data.findall(NS + "row"):
            cells: dict[int, object] = {}
            max_col = -1
            for c in row.findall(NS + "c"):
                idx = _col_index(c.attrib["r"])
                max_col = max(max_col, idx)
                typ = c.attrib.get("t")
                style = int(c.attrib.get("s", "0"))
                v = c.find(NS + "v")

                if typ == "inlineStr":
                    inline = c.find(NS + "is")
                    value = "".join(t.text or "" for t in inline.iter(NS + "t")) if inline is not None else ""
                elif v is None:
                    value = None
                else:
                    raw = v.text or ""
                    if typ == "s":
                        value = shared[int(raw)]
                    elif typ == "b":
                        value = raw == "1"
                    elif typ in ("str", "e"):
                        value = raw
                    else:
                        try:
                            number = float(raw)
                            value = int(number) if number.is_integer() else number
                            if style in date_styles:
                                value = _excel_date(float(number))
                        except ValueError:
                            value = raw
                cells[idx] = value
            rows.append([cells.get(i) for i in range(max_col + 1)])
        return rows
