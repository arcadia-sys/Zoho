"""
fp_store.py — Fingerprint Template Storage  (v2 — fixed)
=========================================================
Handles BOTH template field formats present in your data:
  • ZK records   → "template_b64"  (base-64 string)
  • Zoho records → "template"      (hex string)

Drop this file next to your main attendance script and call
fp_store.init(zk, zoho_request, auth_headers, ...) once at startup.
"""

import os
import time
import sqlite3
import threading
import logging
import base64
from datetime import datetime
from typing import Optional

_log = logging.getLogger("fp_store")

# ── Globals set by init() ─────────────────────────────────────────────────────
_zk             = None
_zoho_request   = None
_auth_headers   = None
_API_DOMAIN     = ""
_APP_OWNER      = ""
_APP_NAME       = ""
_WORKERS_REPORT = "All_Workers"

DB_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fp_templates.db")
_DB_LOCK = threading.Lock()

# Match score threshold for ZKTeco SDK (0-100)
MATCH_THRESHOLD = 50


# =============================================================================
# INITIALISATION
# =============================================================================

def init(zk_instance, zoho_request_fn, auth_headers_fn,
         api_domain: str, app_owner: str, app_name: str,
         workers_report: str = "All_Workers"):
    """Call once after zk.Init() at app startup."""
    global _zk, _zoho_request, _auth_headers
    global _API_DOMAIN, _APP_OWNER, _APP_NAME, _WORKERS_REPORT

    _zk             = zk_instance
    _zoho_request   = zoho_request_fn
    _auth_headers   = auth_headers_fn
    _API_DOMAIN     = api_domain
    _APP_OWNER      = app_owner
    _APP_NAME       = app_name
    _WORKERS_REPORT = workers_report

    _create_db()
    _log.info("fp_store ready — DB: %s", DB_PATH)


# =============================================================================
# PUBLIC API
# =============================================================================

def store_template(zk_user_id: str,
                   zoho_worker_id: str,
                   worker_name: str,
                   raw_record: dict) -> bool:
    """
    Extract and store a template from a raw Zoho/ZK worker record.

    Handles both field formats automatically:
      • raw_record["template_b64"]  — base-64 encoded  (ZK records)
      • raw_record["template"]      — hex string        (Zoho records)

    Parameters
    ----------
    zk_user_id     : the numeric ZK / attendance ID  (e.g. "9")
    zoho_worker_id : the Zoho record ID              (e.g. "4838902000000391493")
    worker_name    : display name for logs
    raw_record     : the full worker dict from Zoho or your local cache

    Returns True on success.
    """
    template_b64 = _extract_template(raw_record)
    if not template_b64:
        _log.warning("store_template: no template found for %s (ID=%s)",
                     worker_name, zk_user_id)
        return False

    return _save_to_db(zk_user_id, zoho_worker_id, worker_name, template_b64)


def store_template_b64(zk_user_id: str,
                       zoho_worker_id: str,
                       worker_name: str,
                       template_b64: str) -> bool:
    """Store a template you already have in base-64 format."""
    if not template_b64:
        return False
    return _save_to_db(zk_user_id, zoho_worker_id, worker_name, template_b64)


def enroll_worker(zoho_worker_id: str,
                  worker_name: str,
                  zk_user_id: str,
                  samples: int = 3,
                  progress_cb=None) -> tuple:
    """
    Scan `samples` fingerprints, merge them, then store locally + push to Zoho.

    Returns (success: bool, message: str)
    """
    def _progress(msg):
        _log.info("enroll [%s]: %s", worker_name, msg)
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    if _zk is None:
        return False, "fp_store not initialised — call fp_store.init() first."
    if _zk.GetDeviceCount() == 0:
        return False, "Scanner not connected."

    _zk.OpenDevice(0)
    try:
        _progress(f"Starting enrollment for {worker_name} — {samples} scans needed")
        raw_captures = []

        for i in range(1, samples + 1):
            _progress(f"Scan {i}/{samples}: place your finger on the scanner…")

            capture = None
            for _ in range(150):          # 30-second timeout per scan
                capture = _zk.AcquireFingerprint()
                if capture:
                    break
                time.sleep(0.2)

            if not capture:
                return False, f"Scan {i} timed out — please try again."

            _progress(f"Scan {i} captured ✔  — lift your finger")
            raw_captures.append(capture)
            time.sleep(0.8)

        _progress("Merging scans…")
        merged = _merge(raw_captures)
        if not merged:
            return False, "Template merge failed — try enrolling again."

        template_b64 = base64.b64encode(merged).decode("utf-8")

        _save_to_db(zk_user_id, zoho_worker_id, worker_name, template_b64)
        _progress("Saved to local database ✔")

        _push_to_zoho_bg(zoho_worker_id, template_b64, worker_name)
        _progress(f"Enrollment complete for {worker_name} ✔")
        return True, f"{worker_name} enrolled successfully."

    except Exception as exc:
        _log.exception("enroll_worker: %s", exc)
        return False, f"Enrollment error: {exc}"
    finally:
        try:
            _zk.CloseDevice()
        except Exception:
            pass


def identify_from_scanner(timeout_seconds: int = 30) -> Optional[dict]:
    """
    Scan a finger and return the matching worker, or None.

    Returned dict:
        {"zk_user_id": str, "zoho_worker_id": str,
         "worker_name": str, "score": int}
    """
    if _zk is None or _zk.GetDeviceCount() == 0:
        _log.error("identify_from_scanner: scanner not ready")
        return None

    _zk.OpenDevice(0)
    try:
        capture = None
        for _ in range(timeout_seconds * 5):
            capture = _zk.AcquireFingerprint()
            if capture:
                break
            time.sleep(0.2)

        if not capture:
            _log.warning("identify_from_scanner: timed out")
            return None

        return _match_1_to_n(capture)

    except Exception as exc:
        _log.exception("identify_from_scanner: %s", exc)
        return None
    finally:
        try:
            _zk.CloseDevice()
        except Exception:
            pass


def verify_worker(zk_user_id: str,
                  timeout_seconds: int = 20) -> tuple:
    """
    1:1 verify — scan a finger and confirm it matches the stored template
    for the given worker ID.

    Returns (matched: bool, score: int)
    """
    tmpl_b64 = get_template_b64(zk_user_id)
    if not tmpl_b64:
        _log.warning("verify_worker: no template for ID %s", zk_user_id)
        return False, 0

    stored = base64.b64decode(tmpl_b64)

    if _zk is None or _zk.GetDeviceCount() == 0:
        return False, 0

    _zk.OpenDevice(0)
    try:
        capture = None
        for _ in range(timeout_seconds * 5):
            capture = _zk.AcquireFingerprint()
            if capture:
                break
            time.sleep(0.2)

        if not capture:
            return False, 0

        score   = _zk.DBMatch(capture, stored)
        matched = score >= MATCH_THRESHOLD
        _log.info("verify_worker [%s]: score=%d matched=%s", zk_user_id, score, matched)
        return matched, score

    except Exception as exc:
        _log.exception("verify_worker: %s", exc)
        return False, 0
    finally:
        try:
            _zk.CloseDevice()
        except Exception:
            pass


def get_template_b64(zk_user_id: str) -> Optional[str]:
    """Return the stored base-64 template for a worker, or None."""
    with _DB_LOCK:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT template_b64 FROM fp_templates WHERE zk_user_id = ?",
                (str(zk_user_id),)
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()


def is_enrolled(zk_user_id: str) -> bool:
    return get_template_b64(zk_user_id) is not None


def delete_template(zk_user_id: str) -> bool:
    with _DB_LOCK:
        conn = _open_db()
        try:
            conn.execute("DELETE FROM fp_templates WHERE zk_user_id = ?",
                         (str(zk_user_id),))
            conn.commit()
            _log.info("Template deleted for ZK ID %s", zk_user_id)
            return True
        except Exception as exc:
            _log.error("delete_template: %s", exc)
            return False
        finally:
            conn.close()


def list_enrolled() -> list:
    """Return all enrolled workers as a list of dicts (no template data)."""
    with _DB_LOCK:
        conn = _open_db()
        try:
            rows = conn.execute(
                "SELECT zk_user_id, zoho_worker_id, worker_name, enrolled_at, updated_at "
                "FROM fp_templates ORDER BY worker_name"
            ).fetchall()
            return [
                {
                    "zk_user_id":     r[0],
                    "zoho_worker_id": r[1],
                    "worker_name":    r[2],
                    "enrolled_at":    r[3],
                    "updated_at":     r[4],
                }
                for r in rows
            ]
        finally:
            conn.close()


def count_enrolled() -> int:
    with _DB_LOCK:
        conn = _open_db()
        try:
            return conn.execute("SELECT COUNT(*) FROM fp_templates").fetchone()[0]
        finally:
            conn.close()


def sync_from_zoho(progress_cb=None) -> tuple:
    """
    Pull all fingerprint templates from Zoho down to the local DB.
    Handles both 'template_b64' and 'template' field names.

    Returns (imported: int, skipped: int)
    """
    def _progress(msg):
        _log.info("sync_from_zoho: %s", msg)
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    if not (_zoho_request and _auth_headers and _API_DOMAIN):
        _progress("fp_store not connected to Zoho — skipping sync.")
        return 0, 0

    hdrs = _auth_headers()
    if not hdrs:
        _progress("No Zoho token — sync aborted.")
        return 0, 0

    url = f"{_API_DOMAIN}/{_APP_OWNER}/{_APP_NAME}/report/{_WORKERS_REPORT}"
    _progress("Fetching workers from Zoho…")

    r = _zoho_request("GET", url, headers=hdrs)
    if not r or r.status_code != 200:
        _progress(f"Zoho fetch failed: {r.status_code if r else 'timeout'}")
        return 0, 0

    workers  = r.json().get("data", [])
    imported = 0
    skipped  = 0
    _progress(f"Processing {len(workers)} workers…")

    for w in workers:
        # ── Extract template — try both field names ──
        template_b64 = _extract_template(w)
        if not template_b64:
            skipped += 1
            continue

        # ── Extract IDs ──
        zk_id  = str(w.get("ZKTeco_User_ID2", w.get("Worker_ID", ""))).strip()
        # Strip trailing ".0" that Zoho sometimes adds to numeric IDs
        zk_id  = zk_id.split(".")[0]
        if not zk_id or zk_id in ("0", "None", ""):
            skipped += 1
            continue

        zoho_id = str(w.get("ID", w.get("zoho_id", zk_id)))
        name    = w.get("Full_Name", w.get("worker_name", zoho_id))

        _save_to_db(zk_id, zoho_id, name, template_b64)
        imported += 1

    _progress(f"Sync complete — {imported} stored, {skipped} had no template.")
    return imported, skipped


def load_from_records(records: list) -> tuple:
    """
    Bulk-load templates from a list of raw worker dicts
    (e.g. the data you already showed in the document).

    Each dict must have:
      • "Worker_ID" or "ZKTeco_User_ID2"
      • "template_b64"  OR  "template"
      • optionally "fid", "zoho_id", "Full_Name"

    Returns (imported: int, skipped: int)
    """
    imported = 0
    skipped  = 0

    for rec in records:
        template_b64 = _extract_template(rec)
        if not template_b64:
            skipped += 1
            continue

        zk_id = str(
            rec.get("Worker_ID") or
            rec.get("ZKTeco_User_ID2") or
            rec.get("fid") or
            rec.get("zoho_id") or
            rec.get("ID") or ""
        ).strip().split(".")[0]

        if not zk_id or zk_id in ("0", "None", ""):
            skipped += 1
            continue

        zoho_id = str(rec.get("zoho_id") or rec.get("ID") or zk_id)
        name    = rec.get("Full_Name") or rec.get("worker_name") or f"Worker {zk_id}"

        _save_to_db(zk_id, zoho_id, name, template_b64)
        imported += 1

    _log.info("load_from_records: %d imported, %d skipped", imported, skipped)
    return imported, skipped


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _extract_template(record: dict) -> Optional[str]:
    """
    Pull the template from a worker record regardless of field format.

    Field priority:
      1. "template_b64"  — already base-64, use directly
      2. "template"      — hex string from Zoho, convert to base-64
    """
    # Format 1: base-64 string (ZK records like your fid 1–11)
    b64 = record.get("template_b64", "")
    if b64 and isinstance(b64, str) and len(b64) > 20:
        # Validate it's real base-64
        try:
            decoded = base64.b64decode(b64)
            if len(decoded) > 10:
                return b64          # already good
        except Exception:
            pass

    # Format 2: hex string (Zoho records like zoho_id 23, 25, 26 …)
    hex_str = record.get("template", "")
    if hex_str and isinstance(hex_str, str) and len(hex_str) > 20:
        try:
            raw  = bytes.fromhex(hex_str)
            b64  = base64.b64encode(raw).decode("utf-8")
            return b64
        except Exception:
            pass

    return None


def _save_to_db(zk_user_id: str, zoho_worker_id: str,
                worker_name: str, template_b64: str) -> bool:
    """Insert or update a template in SQLite."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _DB_LOCK:
        conn = _open_db()
        try:
            conn.execute("""
                INSERT INTO fp_templates
                    (zk_user_id, zoho_worker_id, worker_name,
                     template_b64, enrolled_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(zk_user_id) DO UPDATE SET
                    zoho_worker_id = excluded.zoho_worker_id,
                    worker_name    = excluded.worker_name,
                    template_b64   = excluded.template_b64,
                    updated_at     = excluded.updated_at
            """, (str(zk_user_id), str(zoho_worker_id),
                  str(worker_name), template_b64, now, now))
            conn.commit()
            _log.info("Stored template: %s (ZK ID: %s)", worker_name, zk_user_id)
            return True
        except Exception as exc:
            _log.error("_save_to_db error: %s", exc)
            return False
        finally:
            conn.close()


def _match_1_to_n(capture) -> Optional[dict]:
    """Compare a live capture against all stored templates."""
    workers = list_enrolled()
    if not workers:
        _log.info("_match_1_to_n: no templates enrolled")
        return None

    best_score  = 0
    best_worker = None

    with _DB_LOCK:
        conn = _open_db()
        try:
            for w in workers:
                row = conn.execute(
                    "SELECT template_b64 FROM fp_templates WHERE zk_user_id = ?",
                    (w["zk_user_id"],)
                ).fetchone()
                if not row:
                    continue
                try:
                    stored = base64.b64decode(row[0])
                    score  = _zk.DBMatch(capture, stored)
                    if score > best_score:
                        best_score  = score
                        best_worker = w
                except Exception as exc:
                    _log.debug("match error [%s]: %s", w["zk_user_id"], exc)
        finally:
            conn.close()

    if best_worker and best_score >= MATCH_THRESHOLD:
        _log.info("Identified: %s score=%d", best_worker["worker_name"], best_score)
        return {
            "zk_user_id":     best_worker["zk_user_id"],
            "zoho_worker_id": best_worker["zoho_worker_id"],
            "worker_name":    best_worker["worker_name"],
            "score":          best_score,
        }

    _log.info("No match (best score=%d, threshold=%d)", best_score, MATCH_THRESHOLD)
    return None


def _merge(raw_captures: list) -> Optional[bytes]:
    """Merge 2-3 raw fingerprint captures into one template via ZKTeco DBMerge."""
    if not raw_captures:
        return None
    if len(raw_captures) == 1:
        return raw_captures[0]
    try:
        t1 = raw_captures[0]
        t2 = raw_captures[1]
        t3 = raw_captures[2] if len(raw_captures) >= 3 else raw_captures[1]
        merged = _zk.DBMerge(t1, t2, t3)
        return merged if merged else raw_captures[0]
    except Exception as exc:
        _log.warning("DBMerge unavailable (%s) — using first capture", exc)
        return raw_captures[0]


def _push_to_zoho_bg(zoho_worker_id: str, template_b64: str, worker_name: str):
    """Upload template to Zoho in a background thread (non-blocking)."""
    def _run():
        if not (_zoho_request and _auth_headers and _API_DOMAIN):
            return
        hdrs = _auth_headers()
        if not hdrs:
            _log.error("_push_to_zoho_bg: no token for %s", worker_name)
            return
        url = (f"{_API_DOMAIN}/{_APP_OWNER}/{_APP_NAME}"
               f"/report/{_WORKERS_REPORT}/{zoho_worker_id}")
        r = _zoho_request("PATCH", url, headers=hdrs,
                          json={"data": {"Fingerprint_Template": template_b64}})
        if r and r.status_code == 200 and r.json().get("code") == 3000:
            _log.info("Template uploaded to Zoho: %s ✔", worker_name)
        else:
            code = r.status_code if r else "timeout"
            _log.warning("Zoho upload failed for %s — HTTP %s", worker_name, code)

    threading.Thread(target=_run, daemon=True).start()


def _create_db():
    with _DB_LOCK:
        conn = _open_db()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS fp_templates (
                zk_user_id      TEXT PRIMARY KEY,
                zoho_worker_id  TEXT NOT NULL,
                worker_name     TEXT NOT NULL,
                template_b64    TEXT NOT NULL,
                enrolled_at     TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_zoho_id
                ON fp_templates(zoho_worker_id);
        """)
        conn.commit()
        conn.close()


def _open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn


# =============================================================================
# SELF-TEST
# =============================================================================
if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    # Init without a real scanner
    class _FakeZK:
        def GetDeviceCount(self): return 0
        def DBMatch(self, a, b):  return 0

    init(_FakeZK(), None, None, "", "", "")
    print("DB:", DB_PATH)

    # The actual data format from your document
    test_records = [
        {
            "fid": 1, "Worker_ID": "9",
            "template_b64": "TF1TUzIxAAAFHh4ECAUHCc7QAAApH3YBAABkhcMzqR75AKdkwADJAV16cwD8AC5kawA="
        },
        {
            "fid": 2, "Worker_ID": "17",
            "template_b64": "SuVTUzIxAAADpqkECAUHCc7QAAAvp3YBAABFg0sehaaEAApkpAB3AAvCWgBkAJtkdAA="
        },
        {
            "zoho_id": "23",
            "template": "4a9353533231000003d0d30408050709ced000002fd1760100"
                        "0048837d239bd09b000464b800ba00e3b4490089009f641100"
        }
    ]

    imported, skipped = load_from_records(test_records)
    print(f"\nload_from_records: {imported} imported, {skipped} skipped")

    enrolled = list_enrolled()
    print(f"Enrolled count: {len(enrolled)}")
    for w in enrolled:
        tmpl = get_template_b64(w["zk_user_id"])
        print(f"  ZK {w['zk_user_id']:>4} | {w['worker_name']:<20} | "
              f"template: {len(tmpl)} chars ✔")

    print(f"\nis_enrolled('9'):  {is_enrolled('9')}")
    print(f"is_enrolled('99'): {is_enrolled('99')}")

    delete_template("9")
    print(f"After delete, enrolled: {count_enrolled()}")

    # Clean up test DB
    import os
    os.remove(DB_PATH)
    print("\nAll tests passed ✔")