"""Buy & sell marketplace for used EV batteries: listings, health reports, checks, verification, interest & contact.

Principles (shown to users too):
  * a seller-submitted report, a partner-VERIFIED report and a professional safety assessment are different things;
    uploading a report never certifies a battery as safe or suitable;
  * 'Verification completed' only comes from a registered testing partner confirming the report ID and the SoH it
    measured (registry/testing_partners.json — demo partners for now);
  * every check gives its reason; a discrepancy is a reason to review, never an accusation of fraud;
  * contact details stay private until the seller accepts a buyer's interest; locations are city-level only;
  * files: type checked from their bytes, size-limited, stored outside the web root, served with safe headers.

Storage: SQLite (artifacts/marketplace.db) + files in artifacts/market_files/<listing id>/.
Sellers manage a listing with a secret token returned once at creation (only its hash is stored); buyers likewise.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import sqlite3
import time
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import config, report_extract
from .market import CITIES
from .sponsors import log_evidence
from .usage import applications as registry_apps

router = APIRouter(prefix="/api/listings")
DB = config.ARTIFACTS / "marketplace.db"
FILES = config.ARTIFACTS / "market_files"
PARTNERS_FILE = Path(__file__).parent / "registry" / "testing_partners.json"
DISCLAIMER = ("A health report or CELLFEE estimate is not a safety certification. Seller-submitted information is "
              "the seller's responsibility. Have the battery inspected by a qualified professional before buying or using it.")

VERIFICATION = {
    "draft": "Draft — not submitted",
    "report_uploaded": "Report uploaded — not yet verified",
    "awaiting_provider": "Awaiting provider verification",
    "mismatch": "Identity / report mismatch detected",
    "verified": "Verification completed",
    "more_testing": "Additional testing required",
    "held": "Held for review",
    "rejected": "Listing rejected",
}
LISTING = {"draft": "Draft", "listed": "Listed", "interest_received": "Interest received",
           "in_contact": "Buyer and seller in contact", "sold": "Sold", "withdrawn": "Withdrawn"}
PUBLIC_VERIFICATION = {"report_uploaded", "awaiting_provider", "verified", "more_testing"}
PHOTO_KINDS = {"exterior", "label", "connector", "condition"}


@lru_cache(maxsize=1)
def partners() -> dict:
    return json.loads(PARTNERS_FILE.read_text(encoding="utf-8"))


def policy() -> dict:
    return partners()["policy"]


# ----------------------------------------------------------------------------- storage
def db() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS listings (id TEXT PRIMARY KEY, created REAL, updated REAL, token_hash TEXT,
                   status TEXT, verification TEXT, doc TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS interests (id TEXT PRIMARY KEY, listing_id TEXT, created REAL, token_hash TEXT,
                   status TEXT, doc TEXT)""")
    return con


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _load(con, lid: str) -> sqlite3.Row:
    row = con.execute("SELECT * FROM listings WHERE id = ?", (lid,)).fetchone()
    if row is None:
        raise HTTPException(404, "listing not found")
    return row


def _owner(row, token: str | None):
    if not token or not secrets.compare_digest(_h(token), row["token_hash"]):
        raise HTTPException(403, "this listing belongs to another seller")


def _save(con, lid: str, doc: dict, status: str | None = None, verification: str | None = None):
    con.execute("UPDATE listings SET doc = ?, updated = ?, status = COALESCE(?, status), verification = COALESCE(?, verification) WHERE id = ?",
                (json.dumps(doc), time.time(), status, verification, lid))
    con.commit()


def _event(doc: dict, text: str):
    doc.setdefault("history", []).append({"at": datetime.now().isoformat(timespec="seconds"), "event": text})


def _store_file(lid: str, name: str, data: bytes) -> dict:
    d = FILES / lid
    d.mkdir(parents=True, exist_ok=True)
    kind = report_extract.sniff(name, data)
    safe = f"{secrets.token_hex(8)}.{ {'jpeg': 'jpg'}.get(kind, kind) }"
    (d / safe).write_bytes(data)
    return {"stored": safe, "original_name": re.sub(r"[^\w.\- ()]", "_", name)[:120], "kind": kind,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


# ----------------------------------------------------------------------------- checks & verification state
def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _norm(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def checks(lid: str, doc: dict, con) -> list[dict]:
    """Consistency checks. Each: {code, level (info|warning|blocking), message, reason}. Never an accusation."""
    out = []
    det, rep = doc.get("details", {}), doc.get("report", {})
    ext = (rep.get("extracted") or {})
    add = lambda code, level, msg, why: out.append({"code": code, "level": level, "message": msg, "reason": why})
    pol = policy()
    if not doc.get("report_file"):
        add("no_report", "blocking", "No health report uploaded",
            "A report from a testing provider is required before a listing can be submitted.")
    missing = [lbl for k, lbl in (("provider", "testing provider"), ("report_id", "report ID"), ("test_date", "test date"),
                                  ("soh_pct", "reported SoH")) if rep.get(k) in (None, "", "not_available")]
    if missing:
        add("missing_fields", "warning", "Report fields missing: " + ", ".join(missing),
            "Buyers and testing partners need these to check the report.")
    serial = det.get("serial")
    if serial not in (None, "", "not_available") and ext.get("serial") and _norm(ext["serial"]["value"]) != _norm(serial):
        add("id_mismatch", "blocking", "Battery ID in the report differs from the listing",
            f"Listing says {serial}; the report text shows {ext['serial']['value']} (\"{ext['serial']['snippet']}\").")
    if rep.get("soh_pct") not in (None, "") and ext.get("soh_pct"):
        d = abs(float(rep["soh_pct"]) - float(ext["soh_pct"]["value"]))
        if d > pol["soh_conflict_points"]:
            add("soh_conflict", "blocking", "Reported SoH differs from the report document",
                f"Entered {rep['soh_pct']}%; the document shows {ext['soh_pct']['value']}% (difference {d:.1f} points).")
    if rep.get("soh_pct") not in (None, "") and not 30 <= float(rep["soh_pct"]) <= 100:
        add("soh_implausible", "warning", "Reported SoH is outside 30–100%", "A state of health above 100% or below 30% is unusual for a used EV battery.")
    td = _parse_date(rep.get("test_date"))
    if rep.get("test_date") and td is None:
        add("date_unreadable", "warning", "Test date could not be read", f"\"{rep['test_date']}\" is not a recognised date.")
    if td and td > date.today():
        add("date_future", "blocking", "Test date is in the future", f"The report is dated {td.isoformat()}.")
    if td and (date.today() - td).days > pol["report_max_age_days"]:
        add("outdated", "warning", "Report is older than the policy allows",
            f"Tested {(date.today() - td).days} days ago; policy accepts reports up to {pol['report_max_age_days']} days old. A new test is needed.")
    rated, meas = det.get("rated_capacity_kwh"), rep.get("measured_capacity_kwh")
    if rated not in (None, "", "not_available") and meas not in (None, "", "not_available") and float(meas) > float(rated) * 1.05:
        add("capacity_inconsistent", "warning", "Measured capacity is above the rated capacity",
            f"Measured {meas} kWh vs rated {rated} kWh.")
    if rep.get("provider") and not any(_norm(p["name"]) == _norm(rep["provider"]) or _norm(p["id"]) == _norm(rep["provider"])
                                       for p in partners()["partners"]):
        add("unregistered_provider", "info", "Testing provider is not a registered partner",
            "The report can be shown as seller-submitted, but it cannot be verified until a registered partner tests the battery.")
    # duplicates and re-used documents across other listings
    for other in con.execute("SELECT id, doc FROM listings WHERE id != ? AND status != 'draft'", (lid,)):
        o = json.loads(other["doc"])
        if rep.get("report_id") and _norm(o.get("report", {}).get("report_id")) == _norm(rep["report_id"]):
            add("duplicate_report_id", "blocking", "This report ID is already used by another listing",
                f"Report ID {rep['report_id']} also appears on listing {other['id']}.")
        if serial not in (None, "", "not_available") and _norm(o.get("details", {}).get("serial")) == _norm(serial):
            add("duplicate_serial", "blocking", "This battery ID is already listed", f"Battery ID {serial} also appears on listing {other['id']}.")
        if doc.get("report_file") and o.get("report_file", {}).get("sha256") == doc["report_file"]["sha256"]:
            add("reused_document", "blocking", "The same report file is attached to another listing",
                f"An identical file is on listing {other['id']}; one report should describe one battery.")
    meta = (doc.get("report_file") or {}).get("meta") or {}
    if meta.get("modified") and meta.get("created") and meta["modified"][:16] != meta["created"][:16]:
        add("pdf_modified", "info", "The PDF was modified after it was created",
            "This is common (e.g. re-saving) and is not proof of alteration; a partner check confirms the values.")
    if doc.get("report_file", {}).get("readable") is False:
        add("report_unreadable", "info", "The report's text could not be read automatically",
            "The fields were entered by the seller; a partner check confirms them.")
    return out


def derive_verification(doc: dict, found: list[dict]) -> str:
    codes = {c["code"] for c in found}
    if doc.get("verification_override") in ("verified", "rejected", "held", "mismatch", "more_testing"):
        return doc["verification_override"]
    if codes & {"duplicate_report_id", "duplicate_serial", "reused_document"}:
        return "held"
    if codes & {"id_mismatch", "soh_conflict", "date_future"}:
        return "mismatch"
    if "outdated" in codes:
        return "more_testing"
    if "unregistered_provider" in codes or "missing_fields" in codes:
        return "report_uploaded"
    return "awaiting_provider"


# ----------------------------------------------------------------------------- public view & ranking
def compatible_uses(doc: dict) -> list[dict]:
    """Uses whose health floor the reported SoH meets and whose chemistry list allows it (deterministic)."""
    soh = doc.get("report", {}).get("soh_pct")
    chem = str(doc.get("details", {}).get("chemistry") or "").upper()
    if soh in (None, ""):
        return []
    out = []
    for a in registry_apps():
        if float(soh) / 100 >= a["min_soh"] and (chem in a["chemistries"] or chem in ("", "NOT_AVAILABLE")):
            out.append({"id": a["id"], "name": a["name"], "floor": a["min_soh"],
                        "basis": "chemistry not stated" if chem in ("", "NOT_AVAILABLE") else "reported SoH and chemistry"})
    return out


EVIDENCE_SCORE = {"verified": 1.0, "awaiting_provider": 0.6, "report_uploaded": 0.4, "more_testing": 0.2}


def rank_score(doc: dict, verification: str) -> dict:
    """Evidence first, not SoH alone: 40% verification, 20% measurements present, 15% report recency,
    15% reported SoH, 10% listing completeness."""
    rep, det = doc.get("report", {}), doc.get("details", {})
    meas = ["soh_pct", "measured_capacity_kwh", "internal_resistance_mohm", "test_date", "tests_performed"]
    m = sum(rep.get(k) not in (None, "", "not_available") for k in meas) / len(meas)
    td = _parse_date(rep.get("test_date"))
    rec = max(0.0, 1 - (date.today() - td).days / 365) if td else 0.0
    soh = float(rep["soh_pct"]) / 100 if rep.get("soh_pct") not in (None, "") else 0.0
    fields = ["manufacturer", "model", "chemistry", "vehicle", "age_years", "serial", "rated_capacity_kwh", "rated_voltage_v"]
    comp = sum(det.get(k) not in (None, "", "not_available") for k in fields) / len(fields)
    parts = {"verification": 0.40 * EVIDENCE_SCORE.get(verification, 0), "measurements": 0.20 * m,
             "recency": 0.15 * rec, "soh": 0.15 * soh, "completeness": 0.10 * comp}
    return {"score": round(sum(parts.values()), 4), "parts": {k: round(v, 4) for k, v in parts.items()}}


def public(row, con=None, owner: bool = False) -> dict:
    doc = json.loads(row["doc"])
    found = doc.get("checks", [])
    view = {"id": row["id"], "created": datetime.fromtimestamp(row["created"]).isoformat(timespec="minutes"),
            "status": row["status"], "status_label": LISTING.get(row["status"], row["status"]),
            "verification": row["verification"], "verification_label": VERIFICATION.get(row["verification"], row["verification"]),
            "details": doc.get("details", {}), "report": {k: v for k, v in doc.get("report", {}).items() if k != "extracted"},
            "extracted": doc.get("report", {}).get("extracted", {}),
            "report_file": {k: v for k, v in (doc.get("report_file") or {}).items() if k in ("original_name", "kind", "bytes", "readable", "notes")} or None,
            "sale": {k: v for k, v in doc.get("sale", {}).items() if k not in ("contact_value",)},
            "photos": [{"n": i, "kind": p["photo_kind"], "original_name": p["original_name"]} for i, p in enumerate(doc.get("photos", []))],
            "checks": found, "outstanding": [c for c in found if c["level"] in ("blocking", "warning")],
            "missing": [k for k, v in {**doc.get("details", {}), **doc.get("report", {})}.items() if v == "not_available"],
            "uses": compatible_uses(doc), "rank": rank_score(doc, row["verification"]), "disclaimer": DISCLAIMER,
            "demo": bool(doc.get("demo")), "seller": doc.get("seller"),
            "partner_confirmation": {k: v for k, v in (doc.get("partner_confirmation") or {}).items() if k in ("partner", "at", "outcome", "reason")} or None,
            "verification_note": "Verified means a registered testing partner confirmed this report's ID and SoH. It is not a safety certification."}
    if owner:
        view["sale"] = doc.get("sale", {})
        view["history"] = doc.get("history", [])
        if con is not None:
            view["interests"] = [{"id": i["id"], "created": datetime.fromtimestamp(i["created"]).isoformat(timespec="minutes"),
                                  "status": i["status"], **{k: v for k, v in json.loads(i["doc"]).items() if k in ("name", "message")},
                                  **({"contact": json.loads(i["doc"]).get("contact")} if i["status"] == "accepted" else {})}
                                 for i in con.execute("SELECT * FROM interests WHERE listing_id = ? ORDER BY created DESC", (row["id"],))]
    return view


# ----------------------------------------------------------------------------- API models
class Details(BaseModel):
    manufacturer: str | None = Field(None, max_length=80)
    model: str | None = Field(None, max_length=80)
    chemistry: str | None = Field(None, max_length=20)
    vehicle: str | None = Field(None, max_length=120)
    age_years: float | str | None = None
    usage_history: str | None = Field(None, max_length=600)
    serial: str | None = Field(None, max_length=60)
    rated_capacity_kwh: float | str | None = None
    rated_voltage_v: float | str | None = None
    city: str | None = Field(None, max_length=40)
    form: str | None = Field(None, max_length=10)          # pack | module
    reason: str | None = Field(None, max_length=300)


class ReportFields(BaseModel):
    provider: str | None = Field(None, max_length=120)
    report_id: str | None = Field(None, max_length=60)
    test_date: str | None = Field(None, max_length=30)
    soh_pct: float | str | None = None
    measured_capacity_kwh: float | str | None = None
    internal_resistance_mohm: float | str | None = None
    other_measurements: str | None = Field(None, max_length=600)
    tests_performed: str | None = Field(None, max_length=600)
    limitations: str | None = Field(None, max_length=600)
    issuer_reference: str | None = Field(None, max_length=200)


class Sale(BaseModel):
    price_inr: float | None = Field(None, ge=0, le=100_000_000)
    negotiable: bool = False
    condition: str | None = Field(None, max_length=1000)
    known_faults: str | None = Field(None, max_length=1000)
    warranty: str | None = Field(None, max_length=400)
    inspection_allowed: bool = True
    transport: str | None = Field(None, max_length=200)
    contact_method: str | None = Field(None, max_length=20)   # phone | email | whatsapp
    contact_value: str | None = Field(None, max_length=120)    # private until the seller accepts an interest


class Patch(BaseModel):
    token: str
    details: Details | None = None
    report: ReportFields | None = None
    sale: Sale | None = None


class FileIn(BaseModel):
    token: str
    filename: str = Field(..., max_length=200)
    content_b64: str = Field(..., max_length=14_000_000)
    kind: str | None = None                                   # photo kind


class TokenIn(BaseModel):
    token: str


class StatusIn(BaseModel):
    token: str
    status: str


class InterestIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    contact: str = Field(..., min_length=5, max_length=120)
    message: str | None = Field(None, max_length=1000)


class TokensIn(BaseModel):
    tokens: list[str] = Field(default_factory=list, max_length=50)


class PartnerIn(BaseModel):
    partner_code: str
    report_id: str
    measured_soh_pct: float = Field(..., ge=0, le=100)
    note: str | None = Field(None, max_length=400)


def _clean(d: dict) -> dict:
    """Keep 'not_available' as an explicit answer; numbers stay numbers."""
    out = {}
    for k, v in d.items():
        if isinstance(v, str):
            v = v.strip()
            if v.lower() in ("not available", "not_available", "n/a", "unknown"):
                v = "not_available"
            elif re.fullmatch(r"-?\d+(\.\d+)?", v) and k not in ("serial", "report_id", "model"):
                v = float(v)
        out[k] = v
    return out


# ----------------------------------------------------------------------------- seller endpoints
@router.post("")
def create():
    token = secrets.token_urlsafe(24)
    lid = f"L-{datetime.now():%y%m%d}-{secrets.token_hex(3).upper()}"
    con = db()
    doc = {"details": {}, "report": {}, "sale": {}, "photos": []}
    _event(doc, "draft created")
    con.execute("INSERT INTO listings VALUES (?,?,?,?,?,?,?)", (lid, time.time(), time.time(), _h(token), "draft", "draft", json.dumps(doc)))
    con.commit()
    return {"id": lid, "token": token, "note": "Keep this token: it is the only way to manage the listing (saved in this browser)."}


@router.patch("/{lid}")
def update(lid: str, body: Patch):
    con = db()
    row = _load(con, lid)
    _owner(row, body.token)
    if row["status"] not in ("draft", "listed"):
        raise HTTPException(409, "this listing can no longer be edited")
    doc = json.loads(row["doc"])
    for part in ("details", "report", "sale"):
        val = getattr(body, part)
        if val is not None:
            new = _clean(val.model_dump(exclude_unset=True))   # only the fields the seller sent
            if part == "details" and new.get("city") not in (None, "", "not_available") and new["city"] not in CITIES:
                raise HTTPException(422, "choose a city from the list")
            doc[part] = {**doc.get(part, {}), **new} if part != "report" else {**doc.get("report", {}), **new}
    doc["checks"] = checks(lid, doc, con)
    _save(con, lid, doc)
    return public(_load(con, lid), con, owner=True)


@router.post("/{lid}/report")
def upload_report(lid: str, body: FileIn):
    con = db()
    row = _load(con, lid)
    _owner(row, body.token)
    data = base64.b64decode(body.content_b64)
    if len(data) > policy()["max_report_bytes"]:
        raise HTTPException(413, "report larger than 10 MB")
    kind = report_extract.sniff(body.filename, data)
    if kind not in ("pdf", "jpeg", "png", "webp", "bmp", "tiff", "docx", "text"):
        raise HTTPException(415, "upload the report as a PDF, an image (JPEG / PNG / WEBP) or a Word document")
    doc = json.loads(row["doc"])
    read = report_extract.read_any(body.filename, data)
    extracted = report_extract.extract_fields(read["text"]) if read["text"] else {}
    stored = _store_file(lid, body.filename, data)
    doc["report_file"] = {**stored, "readable": read["readable"], "notes": read["notes"], "meta": read["meta"]}
    doc.setdefault("report", {})["extracted"] = extracted
    # pre-fill empty report fields from the document; the seller reviews and corrects them before submitting
    rep = doc["report"]
    for src, dst in (("provider", "provider"), ("report_id", "report_id"), ("test_date", "test_date"), ("soh_pct", "soh_pct"),
                     ("capacity_kwh", "measured_capacity_kwh"), ("ir_mohm", "internal_resistance_mohm"),
                     ("tests_performed", "tests_performed"), ("limitations", "limitations")):
        if src in extracted and rep.get(dst) in (None, ""):
            rep[dst] = extracted[src]["value"]
    det = doc.setdefault("details", {})
    for src, dst in (("serial", "serial"), ("chemistry", "chemistry"), ("rated_capacity_kwh", "rated_capacity_kwh"), ("voltage_v", "rated_voltage_v"),
                     ("manufacturer", "manufacturer"), ("model", "model"), ("vehicle", "vehicle"), ("age_years", "age_years"), ("form", "form"),
                     ("usage_history", "usage_history"), ("reason", "reason")):
        if src in extracted and det.get(dst) in (None, ""):
            det[dst] = extracted[src]["value"]
    # "Bengaluru, Karnataka, India", "Bangalore" -> Bengaluru
    raw_city = _norm(extracted.get("city", {}).get("value"))
    for old, new in report_extract.CITY_ALIASES.items():
        raw_city = raw_city.replace(_norm(old), _norm(new))
    city = next((c for c in sorted(CITIES, key=len, reverse=True) if raw_city and _norm(c) in raw_city), None)
    if city and det.get("city") in (None, ""):
        det["city"] = city
    # sale essentials written in the document (price, contact, condition...): pre-filled too, still checked by the seller
    sale = doc.setdefault("sale", {})
    for k in ("price_inr", "negotiable", "condition", "known_faults", "warranty", "transport", "inspection_allowed",
              "contact_method", "contact_value"):
        if k in extracted and sale.get(k) in (None, ""):
            sale[k] = extracted[k]["value"]
    _event(doc, f"report uploaded ({stored['kind'].upper()}, {len(extracted)} fields read automatically)")
    doc["checks"] = checks(lid, doc, con)
    _save(con, lid, doc)
    return public(_load(con, lid), con, owner=True)


@router.post("/{lid}/photos")
def upload_photo(lid: str, body: FileIn):
    con = db()
    row = _load(con, lid)
    _owner(row, body.token)
    data = base64.b64decode(body.content_b64)
    if len(data) > policy()["max_photo_bytes"]:
        raise HTTPException(413, "photo larger than 5 MB")
    if report_extract.sniff(body.filename, data) not in ("jpeg", "png", "webp"):
        raise HTTPException(415, "photos must be JPEG, PNG or WEBP")
    doc = json.loads(row["doc"])
    if len(doc.get("photos", [])) >= policy()["max_photos"]:
        raise HTTPException(409, f"at most {policy()['max_photos']} photos")
    doc.setdefault("photos", []).append({**_store_file(lid, body.filename, data), "photo_kind": body.kind if body.kind in PHOTO_KINDS else "condition"})
    _save(con, lid, doc)
    return public(_load(con, lid), con, owner=True)


@router.delete("/{lid}/photos/{n}")
def delete_photo(lid: str, n: int, token: str):
    con = db()
    row = _load(con, lid)
    _owner(row, token)
    doc = json.loads(row["doc"])
    if 0 <= n < len(doc.get("photos", [])):
        doc["photos"].pop(n)
    _save(con, lid, doc)
    return public(_load(con, lid), con, owner=True)


@router.post("/{lid}/preview")
def preview(lid: str, body: TokenIn):
    con = db()
    row = _load(con, lid)
    _owner(row, body.token)
    doc = json.loads(row["doc"])
    doc["checks"] = checks(lid, doc, con)
    _save(con, lid, doc)
    v = public(_load(con, lid), con, owner=True)
    v["would_be"] = {"verification": derive_verification(doc, doc["checks"]),
                     "verification_label": VERIFICATION[derive_verification(doc, doc["checks"])]}
    return v


@router.post("/{lid}/submit")
def submit(lid: str, body: TokenIn):
    con = db()
    row = _load(con, lid)
    _owner(row, body.token)
    doc = json.loads(row["doc"])
    found = checks(lid, doc, con)
    if any(c["code"] == "no_report" for c in found):
        raise HTTPException(422, "a health report is required. If you have none, book a test with a registered testing partner first.")
    s = doc.get("sale", {})
    if not s.get("price_inr") or not s.get("contact_method") or not s.get("contact_value"):
        raise HTTPException(422, "add an asking price and a contact method before submitting")
    if not doc.get("details", {}).get("city"):
        raise HTTPException(422, "add the battery's city")
    ver = derive_verification(doc, found)
    doc["checks"] = found
    _event(doc, f"submitted — {VERIFICATION[ver]}")
    status = "listed" if ver in PUBLIC_VERIFICATION else "draft"
    _save(con, lid, doc, status=status, verification=ver)
    log_evidence("marketplace_listing", {"backend": "CELLFEE marketplace checks", "listing": lid, "verification": ver,
                                         "checks": [{k: c[k] for k in ("code", "level", "reason")} for c in found],
                                         "summary": f"listing {lid} submitted: {VERIFICATION[ver]}"})
    return public(_load(con, lid), con, owner=True)


@router.post("/{lid}/status")
def set_status(lid: str, body: StatusIn):
    if body.status not in ("sold", "withdrawn", "listed"):
        raise HTTPException(422, "status must be sold, withdrawn or listed")
    con = db()
    row = _load(con, lid)
    _owner(row, body.token)
    doc = json.loads(row["doc"])
    _event(doc, f"marked {LISTING[body.status].lower()} by the seller")
    _save(con, lid, doc, status=body.status)
    return public(_load(con, lid), con, owner=True)


@router.post("/mine")
def mine(body: TokensIn):
    con = db()
    hashes = {_h(t) for t in body.tokens}
    return [public(r, con, owner=True) for r in con.execute("SELECT * FROM listings ORDER BY updated DESC") if r["token_hash"] in hashes]


@router.post("/{lid}/interests/{iid}/accept")
def accept(lid: str, iid: str, body: TokenIn):
    con = db()
    row = _load(con, lid)
    _owner(row, body.token)
    it = con.execute("SELECT * FROM interests WHERE id = ? AND listing_id = ?", (iid, lid)).fetchone()
    if it is None:
        raise HTTPException(404, "interest not found")
    if row["status"] in ("sold", "withdrawn"):
        raise HTTPException(409, "this listing is closed")
    con.execute("UPDATE interests SET status = 'accepted' WHERE id = ?", (iid,))
    doc = json.loads(row["doc"])
    _event(doc, f"seller accepted interest {iid}; contact details shared with both sides")
    _save(con, lid, doc, status="in_contact")
    return public(_load(con, lid), con, owner=True)


@router.post("/{lid}/interests/{iid}/decline")
def decline(lid: str, iid: str, body: TokenIn):
    con = db()
    row = _load(con, lid)
    _owner(row, body.token)
    con.execute("UPDATE interests SET status = 'declined' WHERE id = ? AND listing_id = ?", (iid, lid))
    con.commit()
    return public(_load(con, lid), con, owner=True)


# ----------------------------------------------------------------------------- buyer endpoints
@router.get("/sample/report.pdf")
def sample_report():
    """A SAMPLE health report (fictional values) for trying the quick listing; a fresh report ID each time."""
    from .market_seed import _pdf
    n = secrets.randbelow(900000) + 100000
    lines = ["BATTERY HEALTH REPORT - SAMPLE DOCUMENT (fictional, for trying CELLFEE's quick listing)",
             "Tested by: Demo Battery Test Lab (Pune)", f"Report ID: DBT-S{n}", f"Test date: {date.today().isoformat()}",
             f"Battery serial number: TAT-21-S{n}", "Manufacturer: Tata AutoComp", "Model: Nexon EV 30.2 kWh pack",
             "Vehicle: Tata Nexon EV (2021)", "Age: 4 years", "Type: complete pack", "Location: Pune", "Chemistry: LFP",
             "Measured capacity: 26.1 kWh", "State of Health: 86.5 %", "Rated capacity: 30.2 kWh", "Nominal voltage: 320 V",
             "Internal resistance: 38.5 mOhm", "Tests: capacity discharge at C/3, DCIR pulse, visual inspection, BMS read-out",
             "Limitations: cells not individually opened; thermal imaging not performed"]
    return Response(_pdf(lines), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="sample-battery-report-{n}.pdf"'})


@router.get("/sample/photo.png")
def sample_photo(kind: str = "exterior"):
    """A drawn SAMPLE photo (marked as an illustration) for trying the quick listing."""
    from .market_seed import _photo
    kind = kind if kind in ("exterior", "label") else "exterior"
    return Response(_photo(kind, "Tata Nexon EV 30.2 kWh pack", "LFP", 86.5, "TAT-21-SAMPLE", "pack"), media_type="image/png",
                    headers={"Content-Disposition": f'attachment; filename="sample-{kind}.png"'})


@router.get("")
def browse():
    con = db()
    rows = [public(r) for r in con.execute("SELECT * FROM listings WHERE status IN ('listed','interest_received','in_contact')")
            if r["verification"] in PUBLIC_VERIFICATION]
    rows.sort(key=lambda v: -v["rank"]["score"])
    return {"listings": rows, "cities": sorted(CITIES), "uses": [{"id": a["id"], "name": a["name"]} for a in registry_apps()],
            "partners": [{k: p[k] for k in ("id", "name", "city")} for p in partners()["partners"]],
            "verification_labels": VERIFICATION, "ranking": "40% verification, 20% measurements present, 15% report recency, 15% reported SoH, 10% listing completeness",
            "disclaimer": DISCLAIMER}


@router.get("/{lid}")
def detail(lid: str):
    con = db()
    row = _load(con, lid)
    if row["status"] == "draft" or row["verification"] not in PUBLIC_VERIFICATION:
        raise HTTPException(404, "listing not available")
    return public(row)


def _serve(path: Path, kind: str, name: str) -> Response:
    mime = {"pdf": "application/pdf", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "bmp": "image/bmp",
            "tiff": "image/tiff", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text": "text/plain"}.get(kind, "application/octet-stream")
    disp = "inline" if kind in ("pdf", "jpeg", "png", "webp") else "attachment"
    return Response(path.read_bytes(), media_type=mime, headers={
        "Content-Disposition": f'{disp}; filename="{name}"', "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox", "Cache-Control": "no-store"})


@router.get("/{lid}/report-file")
def report_file(lid: str, token: str | None = None):
    con = db()
    row = _load(con, lid)
    if not (row["status"] != "draft" and row["verification"] in PUBLIC_VERIFICATION):
        _owner(row, token)
    f = json.loads(row["doc"]).get("report_file")
    if not f:
        raise HTTPException(404)
    return _serve(FILES / lid / f["stored"], f["kind"], f["original_name"])


@router.get("/{lid}/photos/{n}")
def photo(lid: str, n: int, token: str | None = None):
    con = db()
    row = _load(con, lid)
    if not (row["status"] != "draft" and row["verification"] in PUBLIC_VERIFICATION):
        _owner(row, token)
    ps = json.loads(row["doc"]).get("photos", [])
    if not 0 <= n < len(ps):
        raise HTTPException(404)
    return _serve(FILES / lid / ps[n]["stored"], ps[n]["kind"], ps[n]["original_name"])


@router.post("/{lid}/interest")
def interest(lid: str, body: InterestIn):
    con = db()
    row = _load(con, lid)
    if row["status"] not in ("listed", "interest_received", "in_contact") or row["verification"] not in PUBLIC_VERIFICATION:
        raise HTTPException(409, "this listing is not open for interest")
    token = secrets.token_urlsafe(18)
    iid = f"I-{secrets.token_hex(3).upper()}"
    con.execute("INSERT INTO interests VALUES (?,?,?,?,?,?)", (iid, lid, time.time(), _h(token), "pending",
                                                               json.dumps(body.model_dump())))
    doc = json.loads(row["doc"])
    _event(doc, f"buyer interest {iid} received")
    _save(con, lid, doc, status="interest_received" if row["status"] == "listed" else None)
    return {"id": iid, "token": token, "status": "pending",
            "next": "The seller sees your name and message (not your contact). If they accept, you will both see each other's contact details here."}


@router.post("/interests/mine")
def my_interests(body: TokensIn):
    con = db()
    hashes = {_h(t) for t in body.tokens}
    out = []
    for it in con.execute("SELECT * FROM interests ORDER BY created DESC"):
        if it["token_hash"] not in hashes:
            continue
        row = con.execute("SELECT * FROM listings WHERE id = ?", (it["listing_id"],)).fetchone()
        doc = json.loads(row["doc"]) if row else {}
        rec = {"id": it["id"], "listing_id": it["listing_id"], "status": it["status"],
               "battery": " ".join(str(doc.get("details", {}).get(k) or "") for k in ("manufacturer", "model")).strip() or it["listing_id"],
               "listing_status": LISTING.get(row["status"]) if row else "removed"}
        if it["status"] == "accepted":
            s = doc.get("sale", {})
            rec["seller_contact"] = {"method": s.get("contact_method"), "value": s.get("contact_value")}
        out.append(rec)
    return out


# ----------------------------------------------------------------------------- testing partners (demo)
@router.get("/partners/list")
def partner_list():
    return {"partners": [{k: p[k] for k in ("id", "name", "city")} for p in partners()["partners"]],
            "demo_codes": {p["name"]: p["code"] for p in partners()["partners"] if p["code"].startswith("DEMO-")},
            "note": "Demo partners for exercising verification; in production a partner confirms through an authenticated API."}


@router.get("/partners/queue")
def partner_queue():
    """Public listings whose report names a registered partner and is not yet confirmed (what a partner would re-test)."""
    names = {_norm(p["name"]): p["name"] for p in partners()["partners"]}
    out = []
    for r in db().execute("SELECT * FROM listings WHERE status IN ('listed','interest_received','in_contact') AND verification = 'awaiting_provider' ORDER BY updated DESC"):
        doc = json.loads(r["doc"])
        rep, det = doc.get("report", {}), doc.get("details", {})
        if _norm(rep.get("provider")) in names:
            out.append({"id": r["id"], "battery": f"{det.get('manufacturer', '')} {det.get('model', '')}".strip(), "city": det.get("city"),
                        "provider": names[_norm(rep["provider"])], "report_id": rep.get("report_id"), "soh_pct": rep.get("soh_pct"),
                        "demo": bool(doc.get("demo"))})
    return {"queue": out}


@router.get("/demo/accounts")
def demo_accounts():
    """Keys of the two fictional demo personas created by `python -m cellfee.market_seed` (404 when not seeded)."""
    f = config.ARTIFACTS / "market_demo_accounts.json"
    if not f.exists():
        raise HTTPException(404, "no demo data: run python -m cellfee.market_seed")
    return json.loads(f.read_text(encoding="utf-8"))


@router.post("/{lid}/partner-confirm")
def partner_confirm(lid: str, body: PartnerIn):
    p = next((p for p in partners()["partners"] if secrets.compare_digest(p["code"], body.partner_code)), None)
    if p is None:
        raise HTTPException(403, "unknown partner code")
    con = db()
    row = _load(con, lid)
    doc = json.loads(row["doc"])
    rep = doc.get("report", {})
    found = checks(lid, doc, con)
    blocking = [c for c in found if c["level"] == "blocking"]
    if _norm(rep.get("report_id")) != _norm(body.report_id):
        outcome, why = "mismatch", f"{p['name']} has no report {body.report_id} for this listing's report ID {rep.get('report_id')}"
    elif rep.get("soh_pct") in (None, "") or abs(float(rep["soh_pct"]) - body.measured_soh_pct) > policy()["partner_soh_tolerance_points"]:
        outcome, why = "mismatch", f"{p['name']} measured {body.measured_soh_pct}% SoH; the listing reports {rep.get('soh_pct')}%"
    elif blocking:
        outcome, why = "held", "partner confirmed the report, but other checks still need review: " + "; ".join(c["message"] for c in blocking)
    else:
        outcome, why = "verified", f"{p['name']} confirmed report {body.report_id} and measured {body.measured_soh_pct}% SoH"
    doc["verification_override"] = outcome
    doc["partner_confirmation"] = {"partner": p["name"], "at": datetime.now().isoformat(timespec="seconds"), "outcome": outcome,
                                   "measured_soh_pct": body.measured_soh_pct, "note": body.note, "reason": why}
    _event(doc, f"partner check: {VERIFICATION[outcome]} — {why}")
    status = row["status"] if outcome in PUBLIC_VERIFICATION else row["status"]
    _save(con, lid, doc, status=status, verification=outcome)
    log_evidence("marketplace_verification", {"backend": "testing partner confirmation (demo)", "listing": lid,
                                              "partner": p["name"], "outcome": outcome, "reason": why,
                                              "summary": f"{lid}: {VERIFICATION[outcome]}"})
    return {"listing": lid, "verification": outcome, "label": VERIFICATION[outcome], "reason": why}
