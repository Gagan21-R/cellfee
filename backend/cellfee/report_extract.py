"""Read any uploaded document — PDF, image, Excel, Word, CSV, JSON, text — into text, tables and battery fields.

Used by the Assess & upload tab (test results) and by the marketplace (seller health reports).
  * the real type is detected from the file's bytes (magic numbers), not trusted from its name;
  * PDF: text layer via pypdf (+ creation / modification metadata for the marketplace checks); a scanned PDF with no
    text layer is reported as such;
  * images (JPEG, PNG, WEBP, BMP, TIFF): OCR with RapidOCR (ONNX) when it is available on this machine;
  * Excel (.xlsx): first sheet via openpyxl; Word (.docx): paragraphs and tables from the document XML;
  * battery fields are pulled out with documented patterns and always returned with the text they came from;
    anything not found is reported as missing — never guessed.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from functools import lru_cache
from xml.etree import ElementTree as ET

IMAGE_KINDS = {"jpeg", "png", "webp", "bmp", "tiff", "gif"}


def sniff(name: str, data: bytes) -> str:
    head = data[:16]
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\x89PNG"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"BM"):
        return "bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return "unknown"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        if any(n.startswith("word/") for n in names):
            return "docx"
        return "zip"
    try:
        text = data[:4096].decode("utf-8-sig")
    except UnicodeDecodeError:
        return "unknown"
    t = text.lstrip()
    if t[:1] in "[{":
        return "json"
    return "csv" if name.lower().endswith((".csv", ".tsv")) or ("," in text or ";" in text or "\t" in text) else "text"


@lru_cache(maxsize=1)
def _ocr():
    try:
        from rapidocr_onnxruntime import RapidOCR
        return RapidOCR()
    except Exception:
        return None


def ocr_available() -> bool:
    return _ocr() is not None


def _pdf(data: bytes) -> tuple[str, dict]:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    text = "\n".join((p.extract_text() or "") for p in r.pages)
    meta = {}
    try:
        m = r.metadata or {}
        meta = {"producer": str(m.get("/Producer", "") or ""), "creator": str(m.get("/Creator", "") or ""),
                "created": str(m.get("/CreationDate", "") or ""), "modified": str(m.get("/ModDate", "") or ""),
                "pages": len(r.pages)}
    except Exception:
        pass
    return text, meta


def _image(data: bytes) -> str | None:
    eng = _ocr()
    if eng is None:
        return None
    import numpy as np
    from PIL import Image
    img = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
    res, _ = eng(img)
    if not res:
        return ""
    # keep reading order: top-to-bottom, then left-to-right; group boxes on the same line
    boxes = sorted(((b[0][0][1], b[0][0][0], b[1]) for b in res), key=lambda t: (round(t[0] / 12), t[1]))
    lines, cur, y0 = [], [], None
    for y, x, txt in boxes:
        if y0 is not None and abs(y - y0) > 12:
            lines.append("  ".join(cur)); cur = []
        cur.append(txt); y0 = y
    if cur:
        lines.append("  ".join(cur))
    return "\n".join(lines)


def _xlsx(data: bytes) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    buf = io.StringIO()
    w = csv.writer(buf)
    for row in ws.iter_rows(values_only=True):
        if row and any(v is not None for v in row):
            w.writerow(["" if v is None else v for v in row])
    return buf.getvalue()


def _docx(data: bytes) -> tuple[str, str | None]:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml"))
    paras = ["".join(t.text or "" for t in p.iter(f"{{{ns['w']}}}t")) for p in root.iter(f"{{{ns['w']}}}p")]
    table_csv = None
    tbl = root.find(".//w:tbl", ns)
    if tbl is not None:
        buf = io.StringIO()
        w = csv.writer(buf)
        for tr in tbl.findall("w:tr", ns):
            w.writerow(["".join(t.text or "" for t in tc.iter(f"{{{ns['w']}}}t")) for tc in tr.findall("w:tc", ns)])
        table_csv = buf.getvalue()
    return "\n".join(p for p in paras if p.strip()), table_csv


def read_any(name: str, data: bytes) -> dict:
    """-> {kind, text, table_csv (if a table was found), meta, notes, readable}"""
    kind = sniff(name, data)
    out = {"kind": kind, "text": "", "table_csv": None, "meta": {}, "notes": [], "readable": True}
    try:
        if kind == "pdf":
            out["text"], out["meta"] = _pdf(data)
            if not out["text"].strip():
                out["readable"] = False
                out["notes"].append("this PDF has no text layer (it is a scan); upload the pages as images (JPEG / PNG) so they can be read with OCR, or type the values")
        elif kind in IMAGE_KINDS:
            text = _image(data)
            if text is None:
                out["readable"] = False
                out["notes"].append("image text reading (OCR) is not available on this server; please type the values")
            else:
                out["text"] = text
                out["notes"].append("read with OCR — please check every value")
                if not text.strip():
                    out["readable"] = False
                    out["notes"].append("no text could be read from this image")
        elif kind == "xlsx":
            out["table_csv"] = _xlsx(data)
            out["text"] = out["table_csv"]
        elif kind == "docx":
            out["text"], out["table_csv"] = _docx(data)
        elif kind in ("csv", "json", "text"):
            out["text"] = data.decode("utf-8-sig", errors="replace")
            if kind == "csv":
                out["table_csv"] = out["text"]
        else:
            out["readable"] = False
            out["notes"].append("this file type cannot be read")
    except Exception as exc:
        out["readable"] = False
        out["notes"].append(f"the file could not be read ({str(exc)[:120]})")
    if out["text"] and out["table_csv"] is None:
        out["table_csv"] = table_from_text(out["text"])
    return out


# ----------------------------------------------------------------------------- tables inside PDF / OCR text
HEADER_WORDS = ("cycle", "capacity", "resistance", "ir", "temp", "charge", "soh", "health", "battery")


def table_from_text(text: str) -> str | None:
    """A whitespace / separator table in extracted text (header row with known words + numeric rows) -> CSV."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        cells = [c for c in re.split(r"\s{2,}|\t|,|;|\|", line) if c.strip()]
        low = line.lower()
        if len(cells) >= 3 and sum(w in low for w in HEADER_WORDS) >= 2:
            rows = [cells]
            for nxt in lines[i + 1:]:
                vals = [c for c in re.split(r"\s{2,}|\t|,|;|\||\s", nxt) if c.strip()]
                nums = sum(bool(re.fullmatch(r"-?\d+(\.\d+)?", v)) for v in vals)
                if len(vals) >= len(cells) - 1 and nums >= len(cells) - 2:
                    rows.append(vals[-len(cells):] if len(vals) > len(cells) else vals)
                elif len(rows) > 1:
                    break
            if len(rows) >= 3:
                buf = io.StringIO()
                csv.writer(buf).writerows(rows)
                return buf.getvalue()
    return None


# ----------------------------------------------------------------------------- battery fields from free text
NUM = r"(\d{1,6}(?:[.,]\d+)?)"
PATTERNS = {
    "soh_pct": [rf"(?:state\s*of\s*health|\bsoh\b|health)\D{{0,25}}?{NUM}\s*%"],
    "capacity_kwh": [rf"(?:capacity|energy)\D{{0,25}}?{NUM}\s*kwh"],
    "capacity_ah": [rf"(?:capacity)\D{{0,25}}?{NUM}\s*a\s?h\b"],
    "rated_capacity_kwh": [rf"(?:rated|nominal)\s*(?:capacity|energy)\D{{0,15}}?{NUM}\s*kwh"],
    "voltage_v": [rf"(?:rated|nominal|pack)?\s*voltage\D{{0,15}}?{NUM}\s*v\b"],
    "ir_mohm": [rf"(?:internal\s*resistance|\bdcir\b|\bir\b)\D{{0,25}}?{NUM}\s*(?:m\s?Ω|mohm|milli\s?ohm|mΩ)"],
    "ir_ohm": [rf"(?:internal\s*resistance|\bdcir\b|\bir\b)\D{{0,25}}?{NUM}\s*(?:Ω|ohm)\b"],
    "cycles": [rf"(?:cycle\s*count|cycles\s*(?:done|completed|used)?|charge\s*cycles)\D{{0,15}}?{NUM}"],
    "temp_max_c": [rf"(?:max(?:imum)?\s*temp(?:erature)?|peak\s*temp(?:erature)?)\D{{0,15}}?{NUM}\s*°?\s*c\b"],
    "charge_time_min": [rf"(?:charge|charging)\s*time\D{{0,15}}?{NUM}\s*min"],
    "report_id": [r"(?:report|certificate|test)\s*(?:id|no\.?|number|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/]{3,30})"],
    "serial": [r"(?:serial\s*(?:number|no\.?)?|s/n|battery\s*id|pack\s*id|vin)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{4,30})"],
    "test_date": [r"(?:test(?:ed)?\s*(?:date|on)|date\s*of\s*test|report\s*date|date)\s*[:\-]?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})"],
    # "Tested by X" or "Testing lab: X" (a colon is required after the noun forms, so prose is never taken as a lab name)
    "provider": [r"(?:tested\s*by\s*[:\-]?|(?:testing\s*(?:centre|center|lab(?:oratory)?)|test\s*lab|provider|issued\s*by)\s*:)\s*([A-Za-z0-9&.,()' \-]{3,60})"],
    "chemistry": [r"\b(LFP|LiFePO4|NMC|NCA|LMO|LCO|LTO)\b"],
    # battery identity, read only from "Label: value" lines so free text is never mistaken for a name
    "manufacturer": [r"(?:^|\n)\s*(?:battery\s*)?(?:manufacturer|make|brand|oem)\s*[:\-]\s*([A-Za-z0-9&.' \-]{2,40})"],
    "model": [r"(?:^|\n)\s*(?:battery\s*|pack\s*)?model\s*[:\-]\s*([A-Za-z0-9&.'+/ \-]{1,40})"],
    "vehicle": [r"(?:^|\n)\s*(?:original\s*|source\s*)?vehicle\s*[:\-]\s*([A-Za-z0-9&.'+/() \-]{2,60})"],
    "age_years": [rf"(?:^|\n)\s*(?:battery\s*)?age\s*[:\-]?\s*{NUM}\s*(?:years?|yrs?)\b"],
    "city": [r"(?:^|\n)\s*(?:location|city|battery\s*location)\s*[:\-]\s*([A-Za-z .\-]{3,30})"],
    "form": [r"(?:^|\n)\s*(?:type|form|unit)\s*[:\-]\s*(?:complete\s*|full\s*|battery\s*)?(pack|module)\b"],
}
TEXT_FIELDS = ("report_id", "serial", "test_date", "provider", "chemistry", "manufacturer", "model", "vehicle", "city", "form")


# ----------------------------------------------------------------------------- label / value pairs (forms and tables)
# A report laid out as a form or a two-column table comes out of a PDF / OCR as "Label" on one line and its value on
# the next (or "Label: value" on one line, or a "field_key  value" inventory). Labels are matched against these aliases
# after normalising (lower case, underscores and punctuation to spaces, units and "(required)" removed).
LABELS = {
    "manufacturer": ["manufacturer", "battery manufacturer", "make", "brand", "oem"],
    "model": ["model", "battery model", "pack model", "model number"],
    "vehicle": ["original vehicle", "vehicle", "source vehicle", "vehicle model", "original vehicle make and model"],
    "chemistry": ["chemistry", "cell chemistry", "battery chemistry", "battery type"],
    "serial": ["serial number", "serial no", "serial", "battery serial number", "battery id", "pack id", "battery identifier",
               "battery serial number identifier", "serial number identifier", "s n", "vin"],
    "age_years": ["age", "battery age", "approximate age", "age years"],
    "rated_capacity": ["rated capacity", "nominal capacity", "rated energy", "nominal energy", "design capacity"],
    "voltage_v": ["rated voltage", "nominal voltage", "pack voltage", "voltage"],
    "city": ["city", "location", "battery location", "city where the battery is"],
    "form": ["complete pack or module", "pack or module", "form", "unit type", "pack module"],
    "provider": ["testing lab", "test lab", "testing laboratory", "testing shop", "testing shop provider", "testing provider",
                 "provider", "tested by", "laboratory", "issued by", "testing centre", "testing center"],
    "report_id": ["report id", "report no", "report number", "certificate id", "certificate number", "test report id"],
    "test_date": ["test date", "date of test", "tested on", "report date", "date tested"],
    "soh_pct": ["state of health", "soh", "state of health soh", "health", "reported state of health"],
    "measured_capacity": ["measured capacity", "capacity measured", "remaining capacity", "usable capacity", "actual capacity"],
    "ir_mohm": ["internal resistance", "dcir", "ir", "resistance", "re now", "ohmic resistance"],
    "cycles": ["cycle count", "cycles", "charge cycles", "cycles done", "cycles completed"],
    "temp_max_c": ["max temperature", "maximum temperature", "peak temperature", "operating temperature", "temperature"],
    "tests_performed": ["tests performed", "tests", "tests done", "test type", "test procedure"],
    "limitations": ["known limitations", "limitations", "known limitations of the test", "test limitations"],
    "usage_history": ["usage history", "usage", "duty"],
    "reason": ["reason for selling", "reason"],
    "price_inr": ["asking price", "price", "asking price inr", "sale price", "selling price"],
    "negotiable": ["price negotiable", "negotiable"],
    "condition": ["condition", "battery condition", "physical condition"],
    "known_faults": ["known faults", "faults", "known issues"],
    "warranty": ["warranty", "warranty refurbishment", "warranty or refurbishment"],
    "transport": ["transport", "shipping", "delivery"],
    "inspection_allowed": ["inspection allowed", "inspection allowed before purchase", "inspection"],
    "contact_method": ["preferred contact", "preferred contact method", "contact method"],
    # (no bare "phone" / "email": those are common *values* of "Preferred contact")
    "contact_value": ["your contact", "contact", "seller contact", "contact number", "phone number", "mobile number",
                      "email address", "contact details"],
}
UNIT_WORDS = {"kwh": "kwh", "wh": "wh", "ah": "ah", "mah": "mah", "v": "v", "volts": "v", "mohm": "mohm", "milliohm": "mohm",
              "mω": "mohm", "ohm": "ohm", "ω": "ohm", "percent": "%", "pct": "%", "%": "%", "inr": "inr", "rs": "inr", "₹": "inr",
              "years": "years", "yrs": "years", "km": "km", "c": "c", "°c": "c"}
_ALIAS = {a: f for f, al in LABELS.items() for a in al}
_MISSING = {"", "-", "—", "–", "n/a", "na", "none", "blank", "(blank)", "not available", "not supplied", "unknown", "nil"}
_TEXT_LONG = {"tests_performed", "limitations", "usage_history", "reason", "condition", "known_faults", "warranty", "transport"}
CITY_ALIASES = {"bangalore": "Bengaluru", "bombay": "Mumbai", "madras": "Chennai", "calcutta": "Kolkata", "gurgaon": "Gurugram"}


def _label(line: str) -> tuple[str | None, str | None]:
    """(field, unit) when the whole line is a known label, else (None, None)."""
    low = line.strip().lower().replace("_", " ")
    units = [UNIT_WORDS[u] for u in re.findall(r"\(([^)]{1,12})\)", low) if u.strip() in UNIT_WORDS]
    low = re.sub(r"\([^)]*\)", " ", low)                        # "(kWh)", "(required)", "(resistance)"
    low = re.sub(r"\([^)]*$", " ", low)                          # a note wrapped onto the next line: "(private until you"
    toks = re.sub(r"[^a-z0-9%₹ ]+", " ", low).split()
    while toks and toks[-1] in UNIT_WORDS:                       # "measured capacity kwh", "age years"
        units.append(UNIT_WORDS[toks.pop()])
    key = " ".join(toks)
    f = _ALIAS.get(key)
    return (f, units[0] if units else None) if f else (None, None)


def _num(v: str) -> float | None:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", v.replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _unit_in(v: str) -> str | None:
    low = v.lower()
    for pat, u in ((r"\bkwh\b", "kwh"), (r"\bmah\b", "mah"), (r"\bwh\b", "wh"), (r"\bah\b", "ah"), (r"m\s?ω|mohm|milli\s?ohm", "mohm"),
                   (r"ω|\bohms?\b", "ohm"), (r"%", "%"), (r"\bv\b|volt", "v")):
        if re.search(pat, low):
            return u
    return None


def _clean_text(v: str) -> str:
    v = re.sub(r"\s*\((?:fictional|synthetic|sample|demo|example|test)[^)]*\)", "", v, flags=re.I)
    return re.sub(r"\s+", " ", v).strip(" .;,")


def _iso_date(v: str) -> str:
    v = v.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%d-%b-%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            continue
    return v


def label_value_pairs(text: str) -> dict:
    """Fields from form / table layouts: {field: {"value", "snippet", "unit"}}; the first occurrence of a field wins."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out: dict = {}
    for i, line in enumerate(lines):
        field, unit, value = None, None, None
        m = re.match(r"^(.{2,60}?)\s*(?::|\t|\s{2,})\s*(.+)$", line)           # "Label: value" on one line
        if m:
            f, u = _label(m.group(1))
            if f:
                field, unit, value = f, u, m.group(2)
        if field is None:
            field, unit = _label(line)
            j = i + 1
            if field is not None and "(" in line and ")" not in line.split("(")[-1] and j < len(lines) and ")" in lines[j] \
                    and "(" not in lines[j].split(")")[0]:
                j += 1                                                # skip the rest of the label's wrapped note
            if field is None or j >= len(lines) or _label(lines[j])[0]:
                continue
            value = lines[j]
            if field in _TEXT_LONG:                                   # wrapped text: lines that continue the sentence
                for nxt in lines[j + 1:j + 4]:
                    if _label(nxt)[0] or not (nxt[:1].islower() or value.rstrip().endswith((",", ";", "-", " and", " or"))):
                        break
                    value += " " + nxt
        if field in out or value is None:
            continue
        value = value.strip()
        if _clean_text(value).lower() in _MISSING:
            continue
        out[field] = {"value": value, "unit": unit or _unit_in(value), "snippet": f"{line} → {value}"[:160] if not m else line[:160]}
    return out


def _from_pairs(p: dict) -> dict:
    """Typed, normalised values from label_value_pairs()."""
    out = {}
    put = lambda k, v, src, note="": out.__setitem__(k, {"value": v, "snippet": (src["snippet"] + note)[:200]})
    for f in ("manufacturer", "model", "vehicle", "provider", "report_id", "serial", "tests_performed", "limitations",
              "usage_history", "reason", "condition", "known_faults", "warranty", "transport"):
        if f in p:
            v = _clean_text(p[f]["value"])
            if f in ("report_id", "serial"):
                v = v.split()[0] if v else v
            if v:
                put(f, v, p[f])
    if "chemistry" in p:
        v = p["chemistry"]["value"]
        m = re.search(r"\b(LFP|LiFePO4|NMC|NCA|LMO|LCO|LTO)\b", v, re.I)
        chem = ("LFP" if m.group(1).lower() == "lifepo4" else m.group(1).upper()) if m else \
            ("LFP" if re.search(r"iron\s*phosphate", v, re.I) else None)
        if chem:
            put("chemistry", chem, p["chemistry"])
    if "test_date" in p:
        put("test_date", _iso_date(_clean_text(p["test_date"]["value"])), p["test_date"])
    for f in ("age_years", "cycles", "temp_max_c"):
        if f in p and (n := _num(p[f]["value"])) is not None:
            put(f, n, p[f])
    if "soh_pct" in p and (n := _num(p["soh_pct"]["value"])) is not None:
        put("soh_pct", n * 100 if n <= 1.0 and p["soh_pct"]["unit"] != "%" else n, p["soh_pct"])
    if "voltage_v" in p and (n := _num(p["voltage_v"]["value"])) is not None:
        put("voltage_v", n, p["voltage_v"])
    volt = out.get("voltage_v", {}).get("value")
    for f, kwh_key, ah_key in (("rated_capacity", "rated_capacity_kwh", "rated_capacity_ah"), ("measured_capacity", "capacity_kwh", "capacity_ah")):
        if f in p and (n := _num(p[f]["value"])) is not None:
            u = p[f]["unit"]
            if u == "wh":
                put(kwh_key, round(n / 1000, 4), p[f])
            elif u in ("ah", "mah"):
                ah = n / 1000 if u == "mah" else n
                put(ah_key, ah, p[f])
                if volt:
                    put(kwh_key, round(ah * volt / 1000, 4), p[f], f" (= {ah:g} Ah × {volt:g} V)")
            else:
                put(kwh_key, n, p[f])
    if "ir_mohm" in p and (n := _num(p["ir_mohm"]["value"])) is not None:
        u = p["ir_mohm"]["unit"]
        put("ir_mohm", round(n * 1000, 3) if u == "ohm" or (u is None and n < 1) else n, p["ir_mohm"])
    if "city" in p:
        put("city", _clean_text(p["city"]["value"]), p["city"])
    if "form" in p:
        v = p["form"]["value"].lower()
        if "module" in v or "pack" in v:
            put("form", "module" if "module" in v and "pack" not in v else "pack", p["form"])
    if "price_inr" in p and (n := _num(p["price_inr"]["value"])) is not None:
        low = p["price_inr"]["value"].lower()
        put("price_inr", n * (1e5 if re.search(r"lakh|lac", low) else 1e3 if re.search(r"\d\s*k\b", low) else 1), p["price_inr"])
    for f in ("negotiable", "inspection_allowed"):
        if f in p:
            v = p[f]["value"].strip().lower()
            if v.startswith(("yes", "y ", "true", "allowed")) or v in ("y", "ok"):
                put(f, True, p[f])
            elif v.startswith(("no", "false", "not")):
                put(f, False, p[f])
    if "contact_method" in p:
        v = p["contact_method"]["value"].lower()
        meth = "whatsapp" if "whatsapp" in v else "email" if "mail" in v else "phone" if re.search(r"phone|call|mobile", v) else None
        if meth:
            put("contact_method", meth, p["contact_method"])
    if "contact_value" in p:
        v = p["contact_value"]["value"]
        m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", v) or re.search(r"\+?\d[\d\s\-()]{7,}\d", v)
        if m:
            put("contact_value", m.group(0).strip(), p["contact_value"])
    return out


def extract_fields(text: str) -> dict:
    """{field: {"value": ..., "snippet": "...the text it came from..."}}; fields not found are absent.
    Form / table layouts (label and value on separate lines) are read first; free-text patterns fill the rest."""
    out = _from_pairs(label_value_pairs(text))
    for k, v in _regex_fields(text).items():
        out.setdefault(k, v)
    return out


def _regex_fields(text: str) -> dict:
    out = {}
    flat = re.sub(r"[ \t]+", " ", text)
    for field, pats in PATTERNS.items():
        for pat in pats:
            m = re.search(pat, flat, flags=re.I)
            if not m:
                continue
            raw = m.group(1).strip().rstrip(".,")
            val = raw
            if field not in TEXT_FIELDS:
                try:
                    val = float(raw.replace(",", "."))
                except ValueError:
                    continue
            if field == "chemistry":
                val = "LFP" if raw.lower() == "lifepo4" else raw.upper()
            if field in ("manufacturer", "model", "vehicle", "city"):
                val = raw.strip()
            if field == "form":
                val = raw.lower()
            if field == "provider":
                val = re.split(r"\s{2,}|\n| (?:on|date)\b", raw)[0].strip()
            s, e = max(0, m.start() - 30), min(len(flat), m.end() + 30)
            out[field] = {"value": val, "snippet": flat[s:e].replace("\n", " ").strip()}
            break
    if "ir_mohm" not in out and "ir_ohm" in out:
        v = out["ir_ohm"]["value"]
        out["ir_mohm"] = {"value": v * 1000 if v < 1 else v, "snippet": out["ir_ohm"]["snippet"]}
    out.pop("ir_ohm", None)
    return out
