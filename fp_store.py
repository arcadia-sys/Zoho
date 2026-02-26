"""
fp_store.py — Fingerprint Template Storage & Matching
======================================================
Drop this file next to your main attendance script.

Features:
  • SQLite local database  (fp_templates.db) — fast offline matching
  • Zoho Creator backup    — synced with your All_Workers report
  • Auto-identify worker from fingerprint scan (no ID typing needed)
  • Enroll new workers via scanner
  • Verify identity during check-in / check-out

Integration points  (search for "# FP_STORE" in your main file):
  1. Import at top of main file
  2. Call fp_store.init() once at startup
  3. Replace manual ID entry with fp_store.identify_from_scanner()
  4. Call fp_store.enroll_worker() from an admin panel button

Depends on:  pyzkfp, sqlite3 (stdlib), requests, logging, threading
             — all already used by your main script.
"""

import os
import time
import sqlite3
import threading
import logging
import base64
from datetime import datetime
from typing import Optional

# ── Shared objects injected by the host script ───────────────────────────────
# Call fp_store.init(zk_instance, zoho_request_fn, auth_headers_fn,
#                   api_domain, app_owner, app_name, workers_report)
_zk              = None
_zoho_request    = None
_auth_headers    = None
_API_DOMAIN      = ""
_APP_OWNER       = ""
_APP_NAME        = ""
_WORKERS_REPORT  = ""

_log = logging.getLogger("fp_store")

# ── Database path ─────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "fp_templates.db")

# ── Thread safety ─────────────────────────────────────────────────────────────
_DB_LOCK = threading.Lock()

# ── Zoho field name that holds the base-64 template ──────────────────────────
# Update this to match your actual Zoho field name if different.
ZOHO_TEMPLATE_FIELD = "Fingerprint_Template"


# =============================================================================
# PUBLIC API
# =============================================================================

def init(zk_instance, zoho_request_fn, auth_headers_fn,
         api_domain: str, app_owner: str, app_name: str,
         workers_report: str = "All_Workers"):
    """
    Call once at application startup (before any scan operations).

    Parameters
    ----------
    zk_instance       : ZKFP2 instance from pyzkfp (already Init()-ed)
    zoho_request_fn   : your zoho_request(method, url, **kwargs) function
    auth_headers_fn   : your auth_headers() function
    api_domain        : e.g. "https://creator.zoho.com/api/v2"
    app_owner         : your Zoho app owner slug
    app_name          : your Zoho app name slug
    workers_report    : name of the Workers report (default "All_Workers")
    """
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
    _log.info("fp_store initialised — DB: %s", DB_PATH)


def enroll_worker(zoho_worker_id: str, worker_name: str,
                  zk_user_id: str,
                  samples: int = 3,
                  progress_cb=None) -> tuple[bool, str]:
    """
    Capture `samples` fingerprint scans, merge them into one template,
    store it locally and upload to Zoho.

    Parameters
    ----------
    zoho_worker_id  : Zoho record ID (worker.get("ID"))
    worker_name     : display name for logs / UI messages
    zk_user_id      : ZKTeco / attendance system numeric ID
    samples         : number of scans to merge (2 or 3 recommended)
    progress_cb     : optional callable(message: str) for live UI feedback

    Returns
    -------
    (True,  "Enrolled successfully")  or  (False, "error message")
    """
    def _progress(msg: str):
        _log.info("enroll [%s]: %s", worker_name, msg)
        if progress_cb:
            progress_cb(msg)

    if _zk is None:
        return False, "fp_store not initialised — call fp_store.init() first."

    if _zk.GetDeviceCount() == 0:
        return False, "Scanner not connected."

    _zk.OpenDevice(0)
    try:
        _progress(f"Starting enrollment for {worker_name} ({samples} scans needed)")
        raw_templates = []

        for scan_num in range(1, samples + 1):
            _progress(f"Scan {scan_num}/{samples} — place finger on scanner now…")
            capture = None
            for _ in range(150):  # 30-second timeout
                capture = _zk.AcquireFingerprint()
                if capture:
                    break
                time.sleep(0.2)

            if not capture:
                return False, f"Scan {scan_num} timed out. Try again."

            _progress(f"Scan {scan_num} captured ✔ — lift and re-place finger")
            raw_templates.append(capture)
            time.sleep(0.8)

        # Merge samples into one high-quality template
        _progress("Merging scans into final template…")
        template = _merge_templates(raw_templates)
        if not template:
            return False, "Template merge failed — try enrolling again."

        template_b64 = base64.b64encode(template).decode("utf-8")

        # Store locally
        _save_local(zoho_worker_id, zk_user_id, worker_name, template_b64)
        _progress("Saved to local database ✔")

        # Upload to Zoho (non-blocking — failure does not abort enrollment)
        _upload_to_zoho(zoho_worker_id, template_b64, worker_name)

        _progress(f"Enrollment complete for {worker_name} ✔")
        return True, f"{worker_name} enrolled successfully."

    except Exception as exc:
        _log.exception("enroll_worker error: %s", exc)
        return False, f"Enrollment error: {exc}"
    finally:
        try:
            _zk.CloseDevice()
        except Exception:
            pass


def identify_from_scanner(timeout_seconds: int = 30) -> Optional[dict]:
    """
    Capture a fingerprint and return the matching worker record, or None.

    The returned dict has at least:
        {
          "zoho_worker_id": str,
          "zk_user_id":     str,
          "worker_name":    str,
          "score":          int,   # match confidence 0-100
        }

    Typical usage (replaces the manual ID-entry flow):

        worker_info = fp_store.identify_from_scanner()
        if worker_info:
            uid        = worker_info["zk_user_id"]
            full_name  = worker_info["worker_name"]
            ...
        else:
            # no match — ask worker to type their ID
    """
    if _zk is None:
        _log.error("fp_store.identify_from_scanner: not initialised")
        return None

    if _zk.GetDeviceCount() == 0:
        _log.error("identify_from_scanner: scanner not connected")
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

        return _match_template(capture)

    except Exception as exc:
        _log.exception("identify_from_scanner error: %s", exc)
        return None
    finally:
        try:
            _zk.CloseDevice()
        except Exception:
            pass


def verify_worker(zk_user_id: str, timeout_seconds: int = 20) -> tuple[bool, int]:
    """
    1:1 verification — scan a finger and check it matches the stored
    template for the given worker ID.

    Returns (matched: bool, score: int).
    Use during check-in/out to confirm the correct person is at the terminal.
    """
    if _zk is None:
        return False, 0

    template_b64 = get_template(zk_user_id)
    if not template_b64:
        _log.warning("verify_worker: no template stored for ID %s", zk_user_id)
        return False, 0

    stored_template = base64.b64decode(template_b64)

    if _zk.GetDeviceCount() == 0:
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

        score = _zk.DBMatch(capture, stored_template)
        matched = score >= 50  # ZKTeco default threshold
        _log.info("verify_worker [%s]: score=%d matched=%s", zk_user_id, score, matched)
        return matched, score

    except Exception as exc:
        _log.exception("verify_worker error: %s", exc)
        return False, 0
    finally:
        try:
            _zk.CloseDevice()
        except Exception:
            pass


def get_template(zk_user_id: str) -> Optional[str]:
    """Return the base-64 template for a worker, or None if not enrolled."""
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


def delete_template(zk_user_id: str) -> bool:
    """Remove a stored template (e.g. when a worker leaves)."""
    with _DB_LOCK:
        conn = _open_db()
        try:
            conn.execute(
                "DELETE FROM fp_templates WHERE zk_user_id = ?",
                (str(zk_user_id),)
            )
            conn.commit()
            _log.info("Template deleted for ZK ID %s", zk_user_id)
            return True
        except Exception as exc:
            _log.error("delete_template error: %s", exc)
            return False
        finally:
            conn.close()


def list_enrolled() -> list[dict]:
    """Return all enrolled workers as a list of dicts."""
    with _DB_LOCK:
        conn = _open_db()
        try:
            rows = conn.execute(
                "SELECT zk_user_id, zoho_worker_id, worker_name, enrolled_at "
                "FROM fp_templates ORDER BY worker_name"
            ).fetchall()
            return [
                {
                    "zk_user_id":     r[0],
                    "zoho_worker_id": r[1],
                    "worker_name":    r[2],
                    "enrolled_at":    r[3],
                }
                for r in rows
            ]
        finally:
            conn.close()


def sync_from_zoho(progress_cb=None) -> tuple[int, int]:
    """
    Pull all fingerprint templates stored in Zoho down to the local DB.
    Useful after reinstalling the app or switching machines.

    Returns (imported_count, skipped_count).
    """
    def _progress(msg: str):
        _log.info("sync_from_zoho: %s", msg)
        if progress_cb:
            progress_cb(msg)

    if not _zoho_request or not _auth_headers:
        return 0, 0

    url  = f"{_API_DOMAIN}/{_APP_OWNER}/{_APP_NAME}/report/{_WORKERS_REPORT}"
    hdrs = _auth_headers()
    if not hdrs:
        _progress("No Zoho token — sync aborted.")
        return 0, 0

    _progress("Fetching worker list from Zoho…")
    r = _zoho_request("GET", url, headers=hdrs)
    if not r or r.status_code != 200:
        _progress(f"Zoho fetch failed: {r.status_code if r else 'timeout'}")
        return 0, 0

    workers    = r.json().get("data", [])
    imported   = 0
    skipped    = 0

    for w in workers:
        tmpl_b64 = w.get(ZOHO_TEMPLATE_FIELD, "")
        if not tmpl_b64:
            skipped += 1
            continue

        zk_id   = str(w.get("ZKTeco_User_ID2", w.get("Worker_ID", ""))).strip()
        zoho_id = str(w.get("ID", ""))
        name    = w.get("Full_Name", zoho_id)

        if not zk_id or zk_id in ("0", "None"):
            skipped += 1
            continue

        _save_local(zoho_id, zk_id, name, tmpl_b64)
        imported += 1

    _progress(f"Sync complete — {imported} imported, {skipped} skipped.")
    return imported, skipped


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _create_db():
    with _DB_LOCK:
        conn = _open_db()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fp_templates (
                zk_user_id      TEXT PRIMARY KEY,
                zoho_worker_id  TEXT NOT NULL,
                worker_name     TEXT NOT NULL,
                template_b64    TEXT NOT NULL,
                enrolled_at     TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_zoho_id
            ON fp_templates(zoho_worker_id)
        """)
        conn.commit()
        conn.close()


def _save_local(zoho_worker_id: str, zk_user_id: str,
                worker_name: str, template_b64: str):
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
                  worker_name, template_b64, now, now))
            conn.commit()
            _log.info("Template saved locally for %s (ZK ID: %s)", worker_name, zk_user_id)
        except Exception as exc:
            _log.error("_save_local error: %s", exc)
        finally:
            conn.close()


def _upload_to_zoho(zoho_worker_id: str, template_b64: str, worker_name: str):
    """Upload template to Zoho in a background thread."""
    def _do():
        if not _zoho_request or not _auth_headers:
            return
        hdrs = _auth_headers()
        if not hdrs:
            _log.error("_upload_to_zoho: no token for %s", worker_name)
            return
        url = (f"{_API_DOMAIN}/{_APP_OWNER}/{_APP_NAME}"
               f"/report/{_WORKERS_REPORT}/{zoho_worker_id}")
        r = _zoho_request("PATCH", url, headers=hdrs,
                          json={"data": {ZOHO_TEMPLATE_FIELD: template_b64}})
        if r and r.status_code == 200 and r.json().get("code") == 3000:
            _log.info("Template uploaded to Zoho for %s ✔", worker_name)
        else:
            code = r.status_code if r else "timeout"
            _log.warning("Zoho template upload failed for %s — HTTP %s", worker_name, code)

    threading.Thread(target=_do, daemon=True).start()


def _merge_templates(raw_list: list) -> Optional[bytes]:
    """
    Use ZKFP2.DBMerge to combine multiple raw captures into one template.
    Falls back to the first sample if merge is unavailable.
    """
    if not raw_list:
        return None
    if len(raw_list) == 1:
        return raw_list[0]
    try:
        # DBMerge(temp1, temp2, temp3) — pass same sample twice if only 2 scans
        t1 = raw_list[0]
        t2 = raw_list[1]
        t3 = raw_list[2] if len(raw_list) >= 3 else raw_list[1]
        merged = _zk.DBMerge(t1, t2, t3)
        return merged if merged else raw_list[0]
    except Exception as exc:
        _log.warning("DBMerge not available (%s) — using first sample", exc)
        return raw_list[0]


def _match_template(capture) -> Optional[dict]:
    """
    1:N identification — compare capture against all stored templates.
    Returns the best match above threshold or None.
    """
    enrolled = list_enrolled()
    if not enrolled:
        _log.info("_match_template: no templates enrolled yet")
        return None

    best_score  = 0
    best_worker = None

    for worker in enrolled:
        try:
            stored = base64.b64decode(worker["template_b64"]
                                      if "template_b64" in worker
                                      else _get_template_raw(worker["zk_user_id"]))
            if not stored:
                continue
            score = _zk.DBMatch(capture, stored)
            if score > best_score:
                best_score  = score
                best_worker = worker
        except Exception as exc:
            _log.debug("match error for %s: %s", worker["zk_user_id"], exc)

    THRESHOLD = 50  # ZKTeco recommended minimum
    if best_worker and best_score >= THRESHOLD:
        _log.info("Identified: %s (score=%d)", best_worker["worker_name"], best_score)
        return {
            "zoho_worker_id": best_worker["zoho_worker_id"],
            "zk_user_id":     best_worker["zk_user_id"],
            "worker_name":    best_worker["worker_name"],
            "score":          best_score,
        }
    _log.info("No match above threshold (best score=%d)", best_score)
    return None


def _get_template_raw(zk_user_id: str) -> Optional[bytes]:
    """Return decoded bytes for a template, or None."""
    b64 = get_template(zk_user_id)
    return base64.b64decode(b64) if b64 else None


# =============================================================================
# QUICK SELF-TEST  (python fp_store.py)
# =============================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    # Simulate init without a real ZK device
    class _FakeZK:
        def GetDeviceCount(self):  return 0
        def DBMatch(self, a, b):   return 0

    init(_FakeZK(), None, None, "", "", "")
    print("DB created at:", DB_PATH)

    # Insert a dummy record
    _save_local("zoho-001", "42", "Test Worker",
                base64.b64encode(b"fake_template_data").decode())

    workers = list_enrolled()
    print("Enrolled:", workers)

    tmpl = get_template("42")
    print("Template (first 30 chars):", tmpl[:30] if tmpl else None)

    deleted = delete_template("42")
    print("Deleted:", deleted)
    print("After delete:", list_enrolled())