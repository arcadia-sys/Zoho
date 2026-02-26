# import os, time, json, csv, requests, threading, math, queue, logging
# from datetime import datetime, timedelta
# from dotenv import load_dotenv
# from pyzkfp import ZKFP2
# import tkinter as tk
# from tkinter import ttk, messagebox
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry

# # ===========================================================
# # LOGGING
# # ===========================================================
# logging.basicConfig(
#     filename="attendance.log",
#     level=logging.INFO,
#     format="%(asctime)s [%(levelname)s] %(message)s",
#     datefmt="%Y-%m-%d %H:%M:%S")
# _log = logging.getLogger(__name__)

# # ===========================================================
# # CONFIGURATION
# # ===========================================================
# load_dotenv()

# ZOHO_DOMAIN    = os.getenv("ZOHO_DOMAIN",    "zoho.com")
# APP_OWNER      = os.getenv("APP_OWNER",      "wavemarkpropertieslimited")
# APP_NAME       = os.getenv("APP_NAME",       "real-estate-wages-system")
# CLIENT_ID      = os.getenv("ZOHO_CLIENT_ID")
# CLIENT_SECRET  = os.getenv("ZOHO_CLIENT_SECRET")
# REFRESH_TOKEN  = os.getenv("ZOHO_REFRESH_TOKEN")

# WORKERS_REPORT    = "All_Workers"
# ATTENDANCE_FORM   = "Daily_Attendance"
# ATTENDANCE_REPORT = "Daily_Attendance_Report"
# DEFAULT_PROJECT_ID = "4838902000000391493"

# TOKEN_CACHE  = {"token": None, "expires_at": 0}
# _TOKEN_LOCK  = threading.Lock()

# # Derive the TLD from ZOHO_DOMAIN so EU/IN accounts work too
# _ZOHO_TLD   = ZOHO_DOMAIN.split(".")[-1]          # "com", "eu", "in" …
# ACCOUNTS_URL = f"https://accounts.zoho.{_ZOHO_TLD}"
# API_DOMAIN   = f"https://creator.zoho.{_ZOHO_TLD}/api/v2"

# CHECKIN_LOCK_FILE = "checkin_today.json"

# # ── Shift policy ─────────────────────────────────────────
# SHIFT_START_H   = 7
# SHIFT_START_M   = 00
# SHIFT_HOURS     = 8
# GRACE_MINUTES   = 60
# EARLY_CHECKOUT_H = 17
# EARLY_CHECKOUT_M = 0
# AUTO_CHECKOUT_H  = 19
# AUTO_CHECKOUT_M  = 0

# # ── Performance constants ────────────────────────────────
# WORKER_CACHE_TTL = 3600
# MAX_POOL_SIZE    = 20
# ZOHO_TIMEOUT     = 30
# STATS_REFRESH_MS = 8000
# LOG_MAX_LINES    = 500
# LOCK_WRITE_LOCK  = threading.Lock()

# # ===========================================================
# # GLOBAL SDK
# # ===========================================================
# zk = ZKFP2()
# try:
#     zk.Init()
# except Exception as e:
#     _log.error(f"Fingerprint SDK Init Error: {e}")
#     print(f"Fingerprint SDK Init Error: {e}")

# # ===========================================================
# # HTTP SESSION — connection pooling + automatic retry
# # ===========================================================
# def _make_session():
#     s = requests.Session()
#     retry = Retry(
#         total=3, backoff_factor=1,
#         status_forcelist=[429, 500, 502, 503, 504],
#         allowed_methods=["GET", "POST", "PATCH"])
#     adapter = HTTPAdapter(
#         max_retries=retry,
#         pool_connections=MAX_POOL_SIZE,
#         pool_maxsize=MAX_POOL_SIZE,
#         pool_block=False)
#     s.mount("https://", adapter)
#     s.mount("http://",  adapter)
#     return s

# _SESSION = _make_session()

# def zoho_request(method, url, retries=3, **kwargs):
#     kwargs.setdefault("timeout", ZOHO_TIMEOUT)
#     for attempt in range(1, retries + 1):
#         try:
#             return _SESSION.request(method, url, **kwargs)
#         except (requests.exceptions.Timeout,
#                 requests.exceptions.ConnectionError, OSError) as exc:
#             _log.warning(f"zoho_request attempt {attempt}: {exc}")
#             if attempt < retries:
#                 time.sleep(min(2 ** attempt, 8))
#     return None


# # ===========================================================
# # AUTHENTICATION — thread-safe token refresh
# # ===========================================================
# def _validate_env():
#     """Check that required .env variables are present before attempting auth."""
#     missing = [k for k, v in {
#         "ZOHO_CLIENT_ID":     CLIENT_ID,
#         "ZOHO_CLIENT_SECRET": CLIENT_SECRET,
#         "ZOHO_REFRESH_TOKEN": REFRESH_TOKEN,
#     }.items() if not v]
#     if missing:
#         _log.error(f"Missing .env variables: {', '.join(missing)}")
#         return False
#     return True

# def get_access_token():
#     if not _validate_env():
#         return None

#     now = time.time()
#     with _TOKEN_LOCK:
#         if TOKEN_CACHE["token"] and now < TOKEN_CACHE["expires_at"] - 120:
#             return TOKEN_CACHE["token"]
#         TOKEN_CACHE["token"] = None

#     url = f"{ACCOUNTS_URL}/oauth/v2/token"
#     data = {
#         "refresh_token": REFRESH_TOKEN,
#         "client_id":     CLIENT_ID,
#         "client_secret": CLIENT_SECRET,
#         "grant_type":    "refresh_token",
#     }

#     for attempt in range(3):
#         r = zoho_request("POST", url, data=data, retries=1)
#         if r is None:
#             _log.error(f"Token refresh attempt {attempt+1}: no response / timeout")
#             time.sleep(3)
#             continue

#         if r.status_code == 200:
#             res = r.json()
#             if "access_token" in res:
#                 with _TOKEN_LOCK:
#                     TOKEN_CACHE["token"]      = res["access_token"]
#                     TOKEN_CACHE["expires_at"] = now + int(res.get("expires_in", 3600))
#                 _log.info("Zoho token refreshed OK")
#                 return TOKEN_CACHE["token"]
#             else:
#                 err = res.get("error", "unknown")
#                 _log.error(f"Token refresh attempt {attempt+1} HTTP 200 but error={err!r}. "
#                            f"Full response: {res}")
#                 if err == "invalid_client":
#                     _log.error(
#                         ">>> invalid_client: Your CLIENT_ID or CLIENT_SECRET is wrong, "
#                         "or the OAuth client was deleted/deauthorised in Zoho API Console "
#                         "(https://api-console.zoho.com). Re-generate credentials and update .env.")
#                     return None          # no point retrying
#                 if err in ("invalid_code", "access_denied"):
#                     _log.error(
#                         ">>> Refresh token revoked or expired. Re-authorise the app and "
#                         "generate a new ZOHO_REFRESH_TOKEN.")
#                     return None
#         else:
#             _log.error(f"Token refresh attempt {attempt+1} HTTP {r.status_code}: {r.text[:300]}")

#         time.sleep(3)

#     _log.error("Failed to refresh Zoho token after 3 attempts — "
#                "check REFRESH_TOKEN / CLIENT_ID / CLIENT_SECRET in .env")
#     return None

# def auth_headers():
#     token = get_access_token()
#     if not token:
#         _log.error("auth_headers: no token available — all Zoho calls will fail")
#         return {}
#     return {"Authorization": f"Zoho-oauthtoken {token}"}

# # ===========================================================
# # LOCAL STATE — in-memory cache + safe file persistence
# # ===========================================================
# _LOCK_MEM: dict = {}
# _LOCK_MEM_DATE: str = ""

# def load_lock() -> dict:
#     global _LOCK_MEM, _LOCK_MEM_DATE
#     today = datetime.now().strftime("%Y-%m-%d")
#     if _LOCK_MEM_DATE == today and _LOCK_MEM:
#         return _LOCK_MEM

#     if os.path.exists(CHECKIN_LOCK_FILE):
#         try:
#             with open(CHECKIN_LOCK_FILE, "r", encoding="utf-8") as f:
#                 data = json.load(f)
#             if data.get("date") == today:
#                 for key in ("checked_in", "checked_out"):
#                     if not isinstance(data.get(key), dict):
#                         data[key] = {}
#                     data[key] = {k: v for k, v in data[key].items()
#                                  if isinstance(v, dict)}
#                 _LOCK_MEM      = data
#                 _LOCK_MEM_DATE = today
#                 return _LOCK_MEM
#         except Exception as exc:
#             _log.warning(f"load_lock read error: {exc}")

#     fresh = {"date": today, "checked_in": {}, "checked_out": {}}
#     _LOCK_MEM      = fresh
#     _LOCK_MEM_DATE = today
#     save_lock(fresh)
#     return _LOCK_MEM

# def save_lock(data: dict):
#     global _LOCK_MEM, _LOCK_MEM_DATE
#     _LOCK_MEM      = data
#     _LOCK_MEM_DATE = data.get("date", "")
#     tmp = CHECKIN_LOCK_FILE + ".tmp"
#     with LOCK_WRITE_LOCK:
#         try:
#             with open(tmp, "w", encoding="utf-8") as f:
#                 json.dump(data, f, indent=2)
#             os.replace(tmp, CHECKIN_LOCK_FILE)
#         except Exception as exc:
#             _log.error(f"save_lock error: {exc}")

# def get_worker_status(zk_id: str) -> str:
#     lock = load_lock()
#     key  = str(zk_id)
#     if key in lock["checked_out"]:  return "done"
#     if key in lock["checked_in"]:   return "checked_in"
#     return "none"

# def count_early_checkouts(lock=None) -> int:
#     if lock is None:
#         lock = load_lock()
#     now         = datetime.now()
#     early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                               second=0, microsecond=0)
#     count = 0
#     for info in lock.get("checked_out", {}).values():
#         if not isinstance(info, dict):
#             continue
#         try:
#             co_dt = datetime.strptime(info.get("time", ""), "%H:%M:%S").replace(
#                 year=now.year, month=now.month, day=now.day)
#             if co_dt < early_limit:
#                 count += 1
#         except Exception:
#             pass
#     return count

# # ===========================================================
# # WORKER CACHE — TTL-based, evicts oldest when full
# # ===========================================================
# _WORKER_STORE: dict = {}
# _WORKER_LOCK  = threading.Lock()

# def _wcache_get(uid: str):
#     with _WORKER_LOCK:
#         e = _WORKER_STORE.get(str(uid))
#         if e and (time.time() - e["ts"]) < WORKER_CACHE_TTL:
#             return e["worker"]
#     return None

# def _wcache_set(uid: str, worker: dict):
#     with _WORKER_LOCK:
#         if len(_WORKER_STORE) >= 2000:
#             oldest = sorted(_WORKER_STORE, key=lambda k: _WORKER_STORE[k]["ts"])
#             for old_k in oldest[:200]:
#                 del _WORKER_STORE[old_k]
#         _WORKER_STORE[str(uid)] = {"worker": worker, "ts": time.time()}

# def _wcache_invalidate(uid: str):
#     with _WORKER_LOCK:
#         _WORKER_STORE.pop(str(uid), None)

# # ===========================================================
# # SHIFT HELPERS
# # ===========================================================
# def is_late(checkin_dt: datetime) -> bool:
#     cutoff = checkin_dt.replace(
#         hour=SHIFT_START_H, minute=SHIFT_START_M, second=0, microsecond=0
#     ) + timedelta(minutes=GRACE_MINUTES)
#     return checkin_dt > cutoff

# def late_by_str(checkin_dt: datetime) -> str:
#     shift_start = checkin_dt.replace(
#         hour=SHIFT_START_H, minute=SHIFT_START_M, second=0, microsecond=0)
#     delta = max((checkin_dt - shift_start).total_seconds(), 0)
#     mins  = int(delta // 60)
#     return f"{mins} min late" if mins else "on time"

# def overtime_hours(total_hours: float) -> float:
#     return max(round(total_hours - SHIFT_HOURS, 4), 0)

# # ===========================================================
# # ZOHO API
# # ===========================================================
# def find_worker(zk_user_id, force_refresh: bool = False):
#     """
#     Look up a worker in Zoho by their ZKTeco User ID.
#     Tries multiple criteria formats before falling back to a full-list scan.
#     """
#     uid = str(zk_user_id).strip()

#     if not force_refresh:
#         cached = _wcache_get(uid)
#         if cached:
#             _log.debug(f"find_worker({uid}): cache hit")
#             return cached

#     hdrs = auth_headers()
#     if not hdrs:
#         _log.error(f"find_worker({uid}): aborting — no valid Zoho token. "
#                    "Check REFRESH_TOKEN / CLIENT_ID / CLIENT_SECRET in .env")
#         return None

#     url = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/report/{WORKERS_REPORT}"

#     try:
#         int_id = int(uid)
#     except ValueError:
#         int_id = None

#     criteria_attempts = []
#     if int_id is not None:
#         criteria_attempts += [
#             f"(ZKTeco_User_ID2 == {int_id})",
#             f'(ZKTeco_User_ID2 == "{int_id}")',
#             f"(Worker_ID == {int_id})",
#             f'(Worker_ID == "{int_id}")',
#         ]
#     criteria_attempts += [
#         f'(ZKTeco_User_ID2 == "{uid}")',
#         f'(Worker_ID == "{uid}")',
#     ]

#     for criteria in criteria_attempts:
#         _log.info(f"find_worker({uid}): trying criteria={criteria!r}")
#         r = zoho_request("GET", url, headers=hdrs, params={"criteria": criteria})
#         if not r:
#             _log.error(f"find_worker({uid}): request timed out on criteria={criteria!r}")
#             continue
#         if r.status_code == 401:
#             _log.warning(f"find_worker: HTTP 401 for criteria: {criteria}")
#             with _TOKEN_LOCK:
#                 TOKEN_CACHE["token"]      = None
#                 TOKEN_CACHE["expires_at"] = 0
#             hdrs = auth_headers()         # try refreshing once
#             if not hdrs:
#                 _log.error(f"find_worker({uid}): token refresh failed, aborting")
#                 return None
#             r = zoho_request("GET", url, headers=hdrs, params={"criteria": criteria})
#             if not r or r.status_code != 200:
#                 _log.warning(f"find_worker: criteria failed for ID '{uid}', trying full fetch…")
#                 continue
#         if r.status_code != 200:
#             _log.error(f"find_worker({uid}): HTTP {r.status_code} — {r.text[:300]}")
#             continue

#         data = r.json().get("data", [])
#         if data:
#             _log.info(f"find_worker({uid}): found via criteria={criteria!r}")
#             _wcache_set(uid, data[0])
#             return data[0]

#     # ── Last resort: fetch ALL workers and match manually ──
#     _log.warning(f"find_worker({uid}): all criteria failed — attempting full worker scan")
#     r = zoho_request("GET", url, headers=hdrs)
#     if r and r.status_code == 200:
#         all_workers = r.json().get("data", [])
#         _log.info(f"find_worker({uid}): full scan returned {len(all_workers)} worker(s)")
#         for w in all_workers:
#             zk_val  = str(w.get("ZKTeco_User_ID2", "")).strip()
#             wid_val = str(w.get("Worker_ID",       "")).strip()
#             zk_val_clean  = zk_val.split(".")[0]
#             wid_val_clean = wid_val.split(".")[0]
#             if uid in (zk_val, wid_val, zk_val_clean, wid_val_clean):
#                 _log.info(f"find_worker({uid}): matched via full scan "
#                           f"(ZKTeco_User_ID2={zk_val!r}, Worker_ID={wid_val!r})")
#                 _wcache_set(uid, w)
#                 return w
#     else:
#         _log.error(f"find_worker({uid}): full scan HTTP "
#                    f"{r.status_code if r else 'timeout'}")

#     _log.error(f"find_worker({uid}): worker NOT found after all attempts. "
#                f"Verify ZKTeco_User_ID2 / Worker_ID field in Zoho for ID={uid}")
#     return None


# def search_workers_by_name(name_query: str) -> list:
#     """Search Zoho for workers whose Full_Name contains the query string."""
#     url   = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/report/{WORKERS_REPORT}"
#     hdrs  = auth_headers()
#     results = []

#     for criteria in [
#         f'(Full_Name contains "{name_query}")',
#         f'(Full_Name starts_with "{name_query}")',
#     ]:
#         r = zoho_request("GET", url, headers=hdrs, params={"criteria": criteria})
#         if r and r.status_code == 200:
#             results = r.json().get("data", [])
#         if results:
#             return results

#     # Fallback: full scan
#     r = zoho_request("GET", url, headers=hdrs)
#     if r and r.status_code == 200:
#         q = name_query.lower()
#         results = [w for w in r.json().get("data", [])
#                    if q in str(w.get("Full_Name", "")).lower()]
#     return results


# def _extract_zoho_id(res_json):
#     data = res_json.get("data")
#     if isinstance(data, dict):
#         return data.get("ID") or data.get("id")
#     if isinstance(data, list) and data:
#         return data[0].get("ID") or data[0].get("id")
#     return res_json.get("ID") or res_json.get("id")


# def _find_record_in_zoho(worker_id, today_display, today_iso, hdrs, _log_fn=None):
#     def dbg(msg):
#         _log.debug(f"[ZOHO SEARCH] {msg}")
#         if _log_fn:
#             _log_fn(f"[search] {msg}", "warn")

#     report_url   = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/report/{ATTENDANCE_REPORT}"
#     criteria_list = [
#         f'(Worker_Name == "{worker_id}" && Date == "{today_display}")',
#         f'(Worker_Name == "{worker_id}" && Date == "{today_iso}")',
#         f'(Worker_ID_Lookup == "{worker_id}" && Date == "{today_display}")',
#         f'(Worker_ID_Lookup == "{worker_id}" && Date == "{today_iso}")',
#         f'(Worker_Name == "{worker_id}")',
#         f'(Worker_ID_Lookup == "{worker_id}")',
#     ]

#     for crit in criteria_list:
#         r = zoho_request("GET", report_url, headers=hdrs, params={"criteria": crit})
#         if not r or r.status_code != 200:
#             continue
#         recs = r.json().get("data", [])
#         if not recs:
#             continue
#         for rec in recs:
#             d = str(rec.get("Date", rec.get("Date_field", ""))).strip()
#             if d in (today_display, today_iso):
#                 return rec["ID"]
#         if len(recs) == 1:
#             return recs[0]["ID"]

#     for date_val in (today_display, today_iso):
#         r = zoho_request("GET", report_url, headers=hdrs,
#                          params={"criteria": f'(Date == "{date_val}")'})
#         if not r or r.status_code != 200:
#             continue
#         for rec in r.json().get("data", []):
#             for field in ("Worker_Name", "Worker_ID_Lookup", "Worker",
#                           "Worker_Name.ID", "Worker_ID"):
#                 val = rec.get(field)
#                 if isinstance(val, dict):
#                     val = val.get("ID") or val.get("id") or val.get("display_value", "")
#                 if str(val).strip() == str(worker_id).strip():
#                     return rec["ID"]

#     dbg("All strategies exhausted — not found.")
#     return None

# # ===========================================================
# # ATTENDANCE LOGIC
# # ===========================================================
# def log_attendance(worker_id, zk_id, project_id, full_name, action, _log_fn=None):
#     now     = datetime.now()
#     zk_key  = str(zk_id)
#     today_display = now.strftime("%d-%b-%Y")
#     today_iso     = now.strftime("%Y-%m-%d")

#     if action == "checkin":
#         form_url     = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/form/{ATTENDANCE_FORM}"
#         checkin_time = now.strftime("%d-%b-%Y %H:%M:%S")
#         hdrs         = auth_headers()
#         if not hdrs:
#             return False, "Could not refresh Zoho token."

#         worker_late = is_late(now)
#         late_note   = late_by_str(now)
#         late_mins   = int(max(
#             (now - now.replace(hour=SHIFT_START_H, minute=SHIFT_START_M,
#                                second=0, microsecond=0)).total_seconds() // 60, 0
#         )) if worker_late else 0

#         payload = {"data": {
#             "Worker_Name":      worker_id,
#             "Projects":         project_id,
#             "Date":             today_display,
#             "First_In":         checkin_time,
#             "Worker_Full_Name": full_name,
#             "Is_Late":          "true" if worker_late else "false",
#             "Late_By_Minutes":  late_mins,
#         }}

#         r = zoho_request("POST", form_url, headers=hdrs, json=payload)
#         if r and r.status_code in (200, 201):
#             res          = r.json()
#             zoho_rec_id  = _extract_zoho_id(res)
#             if not zoho_rec_id:
#                 zoho_rec_id = _find_record_in_zoho(
#                     worker_id, today_display, today_iso, auth_headers(), _log_fn)

#             lock = load_lock()
#             lock["checked_in"][zk_key] = {
#                 "time":      checkin_time,
#                 "zoho_id":   zoho_rec_id,
#                 "worker_id": worker_id,
#                 "name":      full_name,
#                 "is_late":   worker_late,
#                 "late_note": late_note,
#             }
#             save_lock(lock)
#             _log.info(f"CHECKIN OK: {full_name} late={worker_late}")
#             status_line = f"⚠ {late_note}" if worker_late else "✓ On time"
#             return True, (f"✅ {full_name} checked IN at {now.strftime('%H:%M')}\n"
#                           f"   {status_line}")

#         err = r.text[:200] if r else "Timeout"
#         _log.error(f"CHECKIN FAIL: {full_name}: {err}")
#         return False, f"Check-in failed: {err}"

#     elif action == "checkout":
#         lock = load_lock()
#         info = lock["checked_in"].get(zk_key)
#         if not info:
#             return False, "No check-in record found for today."

#         hdrs = auth_headers()
#         if not hdrs:
#             return False, "Could not refresh Zoho token."

#         att_record_id  = info.get("zoho_id")
#         stored_worker  = info.get("worker_id", worker_id)

#         def dbg(msg):
#             _log.debug(f"[CHECKOUT] {msg}")
#             if _log_fn:
#                 _log_fn(f"[checkout] {msg}", "warn")

#         if att_record_id:
#             direct_url = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
#                           f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
#             r_chk = zoho_request("GET", direct_url, headers=hdrs)
#             if not (r_chk and r_chk.status_code == 200):
#                 dbg("stored ID invalid — searching...")
#                 att_record_id = None

#         if not att_record_id:
#             att_record_id = _find_record_in_zoho(
#                 stored_worker, today_display, today_iso, hdrs, _log_fn)
#             if att_record_id:
#                 lock["checked_in"][zk_key]["zoho_id"] = att_record_id
#                 save_lock(lock)

#         if not att_record_id:
#             form_index_url = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/form/{ATTENDANCE_FORM}"
#             for date_val in (today_display, today_iso):
#                 crit = f'(Worker_Name == "{stored_worker}" && Date == "{date_val}")'
#                 r_f  = zoho_request("GET", form_index_url, headers=hdrs,
#                                     params={"criteria": crit})
#                 if r_f and r_f.status_code == 200:
#                     frecs = r_f.json().get("data", [])
#                     if frecs:
#                         att_record_id = frecs[0].get("ID")
#                         lock["checked_in"][zk_key]["zoho_id"] = att_record_id
#                         save_lock(lock)
#                         break

#         if not att_record_id:
#             return False, (f"Could not locate attendance record in Zoho.\n"
#                            f"Worker: {full_name}  Date: {today_display}\n"
#                            "Check the log for [checkout] diagnostics.")

#         try:
#             dt_in = datetime.strptime(info.get("time", ""), "%d-%b-%Y %H:%M:%S")
#         except Exception:
#             dt_in = now

#         total_hours = max((now - dt_in).total_seconds() / 3600, 0.01)
#         ot_hours    = overtime_hours(total_hours)
#         total_str   = f"{int(total_hours)}h {int((total_hours % 1) * 60)}m"
#         ot_str      = f"{int(ot_hours)}h {int((ot_hours % 1) * 60)}m" if ot_hours else "None"
#         total_hours_rounded = round(total_hours, 2)
#         ot_hours_rounded    = round(ot_hours, 2)

#         update_url = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
#                       f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
#         r_u = zoho_request("PATCH", update_url, headers=hdrs, json={"data": {
#             "Last_Out":       now.strftime("%d-%b-%Y %H:%M:%S"),
#             "Total_Hours":    total_hours_rounded,
#             "Overtime_Hours": ot_hours_rounded,
#         }})

#         http_code = r_u.status_code if r_u else "timeout"
#         body_raw  = r_u.text[:300]  if r_u else "No response"

#         if r_u and r_u.status_code == 200:
#             body = r_u.json()
#             code = body.get("code")
#             if code == 3000:
#                 checkout_hms = now.strftime("%H:%M:%S")
#                 lock["checked_in"].pop(zk_key, None)
#                 lock["checked_out"][zk_key] = {
#                     "time":           checkout_hms,
#                     "name":           full_name,
#                     "total_hours":    total_hours_rounded,
#                     "overtime_hours": ot_hours_rounded,
#                     "is_late":        info.get("is_late", False),
#                     "late_note":      info.get("late_note", ""),
#                     "checkin_time":   info.get("time", ""),
#                 }
#                 save_lock(lock)
#                 _log.info(f"CHECKOUT OK: {full_name} hours={total_hours_rounded}")
#                 ot_line     = f"   Overtime: {ot_str}" if ot_hours else ""
#                 early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                                           second=0, microsecond=0)
#                 early_note  = (f"\n   ⚠ Early checkout "
#                                f"(before {EARLY_CHECKOUT_H:02d}:{EARLY_CHECKOUT_M:02d})"
#                                if now < early_limit else "")
#                 return True, (f"🚪 {full_name} checked OUT at {now.strftime('%H:%M')}\n"
#                               f"   Total time: {total_str}\n{ot_line}{early_note}")

#             errors = body.get("error", body.get("message", ""))
#             return False, (f"Zoho rejected update (code {code}).\nError: {errors}\n"
#                            f"Worker: {full_name}  Hours: {total_hours_rounded}")

#         _log.error(f"CHECKOUT FAIL: {full_name} HTTP {http_code}: {body_raw}")
#         return False, f"Check-out PATCH failed (HTTP {http_code}): {body_raw}"

#     return False, "Unknown action."

# # ===========================================================
# # AUTO-CHECKOUT — concurrent batch processing
# # ===========================================================
# def run_auto_checkout(gui_log_fn=None, done_cb=None):
#     now           = datetime.now()
#     today_display = now.strftime("%d-%b-%Y")
#     today_iso     = now.strftime("%Y-%m-%d")
#     checkout_ts   = now.strftime("%d-%b-%Y %H:%M:%S")
#     checkout_hms  = now.strftime("%H:%M:%S")

#     lock    = load_lock()
#     pending = {k: v for k, v in lock.get("checked_in", {}).items()
#                if isinstance(v, dict)}

#     if not pending:
#         if done_cb:
#             done_cb([], [])
#         return

#     def info(msg):
#         _log.info(msg)
#         if gui_log_fn:
#             gui_log_fn(msg, "warn")

#     info(f"AUTO-CHECKOUT: {len(pending)} worker(s) at {now.strftime('%H:%M')}")

#     success_names, fail_names = [], []
#     result_lock = threading.Lock()
#     sem         = threading.Semaphore(8)

#     def _checkout_one(zk_key, winfo):
#         with sem:
#             full_name = winfo.get("name",      zk_key)
#             worker_id = winfo.get("worker_id", zk_key)
#             att_record_id = winfo.get("zoho_id")
#             hdrs = auth_headers()

#             if att_record_id:
#                 du = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
#                       f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
#                 rc = zoho_request("GET", du, headers=hdrs)
#                 if not (rc and rc.status_code == 200):
#                     att_record_id = None

#             if not att_record_id:
#                 att_record_id = _find_record_in_zoho(
#                     worker_id, today_display, today_iso, hdrs)

#             if not att_record_id:
#                 info(f"  SKIP {full_name}: no Zoho record")
#                 with result_lock:
#                     fail_names.append(full_name)
#                 return

#             try:
#                 dt_in = datetime.strptime(winfo.get("time", ""), "%d-%b-%Y %H:%M:%S")
#             except Exception:
#                 dt_in = now

#             total_h = max((now - dt_in).total_seconds() / 3600, 0.01)
#             ot_h    = overtime_hours(total_h)

#             uu = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
#                   f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
#             ru = zoho_request("PATCH", uu, headers=hdrs, json={"data": {
#                 "Last_Out":       checkout_ts,
#                 "Total_Hours":    round(total_h, 2),
#                 "Overtime_Hours": round(ot_h, 2),
#             }})

#             if ru and ru.status_code == 200 and ru.json().get("code") == 3000:
#                 lk = load_lock()
#                 lk["checked_in"].pop(zk_key, None)
#                 lk["checked_out"][zk_key] = {
#                     "time":           checkout_hms,
#                     "name":           full_name,
#                     "total_hours":    round(total_h, 2),
#                     "overtime_hours": round(ot_h, 2),
#                     "is_late":        winfo.get("is_late", False),
#                     "late_note":      winfo.get("late_note", ""),
#                     "checkin_time":   winfo.get("time", ""),
#                     "auto_checkout":  True,
#                 }
#                 save_lock(lk)
#                 h_str = f"{int(total_h)}h {int((total_h % 1) * 60)}m"
#                 info(f"  OK {full_name} -- {h_str}")
#                 with result_lock:
#                     success_names.append(full_name)
#             else:
#                 code = ru.status_code if ru else "timeout"
#                 info(f"  FAIL {full_name} HTTP {code}")
#                 with result_lock:
#                     fail_names.append(full_name)

#     threads = [threading.Thread(target=_checkout_one, args=(k, v), daemon=True)
#                for k, v in pending.items()]
#     for t in threads: t.start()
#     for t in threads: t.join()

#     info(f"AUTO-CHECKOUT done: {len(success_names)} OK, {len(fail_names)} failed")
#     if done_cb:
#         done_cb(success_names, fail_names)

# # ===========================================================
# # DAILY SUMMARY EXPORT
# # ===========================================================
# def export_daily_summary():
#     lock     = load_lock()
#     today    = lock.get("date", datetime.now().strftime("%Y-%m-%d"))
#     filename = f"attendance_{today}.csv"
#     rows     = []
#     now      = datetime.now()
#     early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                               second=0, microsecond=0)

#     for zk_id, info in lock.get("checked_out", {}).items():
#         if not isinstance(info, dict):
#             continue
#         co_str   = info.get("time", "")
#         is_early = False
#         try:
#             co_dt    = datetime.strptime(co_str, "%H:%M:%S").replace(
#                 year=now.year, month=now.month, day=now.day)
#             is_early = co_dt < early_limit
#         except Exception:
#             pass
#         rows.append({
#             "ZK_ID":          zk_id,
#             "Name":           info.get("name", ""),
#             "Check-In":       info.get("checkin_time", ""),
#             "Check-Out":      co_str,
#             "Total Hours":    info.get("total_hours", ""),
#             "Overtime Hours": info.get("overtime_hours", 0),
#             "Late?":          "Yes" if info.get("is_late") else "No",
#             "Late Note":      info.get("late_note", ""),
#             "Early Checkout?":"Yes" if is_early else "No",
#             "Auto Checkout?": "Yes" if info.get("auto_checkout") else "No",
#             "Status":         "Complete",
#         })

#     for zk_id, info in lock.get("checked_in", {}).items():
#         if not isinstance(info, dict):
#             continue
#         rows.append({
#             "ZK_ID":          zk_id,
#             "Name":           info.get("name", ""),
#             "Check-In":       info.get("time", ""),
#             "Check-Out":      "---",
#             "Total Hours":    "---",
#             "Overtime Hours": "---",
#             "Late?":          "Yes" if info.get("is_late") else "No",
#             "Late Note":      info.get("late_note", ""),
#             "Early Checkout?":"---",
#             "Auto Checkout?": "---",
#             "Status":         "Still In",
#         })

#     if not rows:
#         return None

#     fieldnames = ["ZK_ID", "Name", "Check-In", "Check-Out", "Total Hours",
#                   "Overtime Hours", "Late?", "Late Note", "Early Checkout?",
#                   "Auto Checkout?", "Status"]
#     with open(filename, "w", newline="", encoding="utf-8") as f:
#         writer = csv.DictWriter(f, fieldnames=fieldnames)
#         writer.writeheader()
#         writer.writerows(rows)

#     _log.info(f"CSV exported: {filename} ({len(rows)} rows)")
#     return filename

# # ===========================================================
# # COLOUR PALETTE
# # ===========================================================
# BG      = "#07090f"; CARD    = "#0c1018"; CARD2   = "#10151f"
# BORDER  = "#1c2438"; BORDER2 = "#243048"
# ACCENT  = "#3b82f6"; ACCENT_DIM = "#172554"; ACCENT2 = "#60a5fa"
# GREEN   = "#10b981"; GREEN2  = "#34d399"; GREEN_DIM  = "#052e1c"
# RED     = "#f43f5e"; RED2    = "#fb7185"; RED_DIM    = "#4c0519"
# ORANGE  = "#f59e0b"; ORANGE2 = "#fbbf24"; ORANGE_DIM = "#3d1f00"
# CYAN2   = "#67e8f9"; CYAN_DIM = "#083344"
# TEXT    = "#e2e8f0"; TEXT2   = "#94a3b8"; MUTED   = "#3d4f69"
# WHITE   = "#ffffff"; GOLD    = "#f59e0b"; GOLD2   = "#fde68a"
# PURPLE  = "#a78bfa"; PURPLE_DIM = "#2e1065"
# TEAL    = "#2dd4bf"; TEAL_DIM   = "#042f2e"

# # ===========================================================
# # UI HELPERS
# # ===========================================================
# def _btn_hover(btn, bg_on, fg_on, bg_off, fg_off):
#     btn.bind("<Enter>", lambda _: btn.config(bg=bg_on,  fg=fg_on))
#     btn.bind("<Leave>", lambda _: btn.config(bg=bg_off, fg=fg_off))

# def _make_sep(parent, color=BORDER, height=1):
#     tk.Frame(parent, bg=color, height=height).pack(fill=tk.X)

# def _initials(name: str) -> str:
#     parts = name.strip().split()
#     if not parts:      return "??"
#     if len(parts) == 1: return parts[0][:2].upper()
#     return (parts[0][0] + parts[-1][0]).upper()

# # ===========================================================
# # FORGOTTEN ID DIALOG
# # ===========================================================
# class ForgottenIDDialog(tk.Toplevel):
#     def __init__(self, parent, on_select):
#         super().__init__(parent)
#         self.on_select  = on_select
#         self._results   = []
#         self._search_job = None
#         self.title("Find Worker by Name")
#         self.configure(bg=BG)
#         self.resizable(False, False)
#         self.grab_set()
#         self.focus_force()
#         W, H = 520, 460
#         sw, sh = parent.winfo_screenwidth(), parent.winfo_screenheight()
#         self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
#         self._build()
#         self.name_entry.focus_set()

#     def _build(self):
#         tk.Frame(self, bg=TEAL, height=3).pack(fill=tk.X)
#         hdr = tk.Frame(self, bg=CARD, padx=20, pady=14); hdr.pack(fill=tk.X)
#         tk.Label(hdr, text="🔍 FORGOTTEN ID LOOKUP",
#                  font=("Courier", 11, "bold"), bg=CARD, fg=TEAL).pack(anchor="w")
#         tk.Label(hdr, text="Type your name below — matching workers will appear instantly",
#                  font=("Courier", 8), bg=CARD, fg=TEXT2).pack(anchor="w", pady=(3, 0))
#         _make_sep(self, BORDER2)

#         sf = tk.Frame(self, bg=BG, padx=20, pady=14); sf.pack(fill=tk.X)
#         tk.Label(sf, text="NAME", font=("Courier", 8, "bold"),
#                  bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 5))
#         eb = tk.Frame(sf, bg=TEAL, padx=2, pady=2); eb.pack(fill=tk.X)
#         ei = tk.Frame(eb, bg=CARD2); ei.pack(fill=tk.X)
#         self._name_var = tk.StringVar()
#         self._name_var.trace_add("write", lambda *_: self._on_type())
#         self.name_entry = tk.Entry(ei, textvariable=self._name_var,
#                                    font=("Courier", 16, "bold"),
#                                    bg=CARD2, fg=WHITE, insertbackground=TEAL,
#                                    bd=0, width=28)
#         self.name_entry.pack(padx=12, pady=10)
#         self.name_entry.bind("<Escape>", lambda _: self.destroy())
#         self.name_entry.bind("<Down>",   self._focus_list)

#         self._status_lbl = tk.Label(sf, text="Start typing to search…",
#                                     font=("Courier", 8), bg=BG, fg=MUTED)
#         self._status_lbl.pack(anchor="w", pady=(6, 0))
#         _make_sep(self, BORDER)

#         lf = tk.Frame(self, bg=BG, padx=20, pady=10); lf.pack(fill=tk.BOTH, expand=True)
#         tk.Label(lf, text="RESULTS — click a name to load their ID",
#                  font=("Courier", 7, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 6))

#         style = ttk.Style(self); style.theme_use("default")
#         style.configure("FID.Treeview", background=CARD2, foreground=TEXT,
#                          fieldbackground=CARD2, rowheight=34,
#                          font=("Courier", 10), borderwidth=0)
#         style.configure("FID.Treeview.Heading", background=CARD,
#                          foreground=TEAL, font=("Courier", 8, "bold"), relief="flat")
#         style.map("FID.Treeview",
#                   background=[("selected", TEAL_DIM)],
#                   foreground=[("selected", TEAL)])

#         cols = ("Name", "ZK ID", "Status")
#         self._tree = ttk.Treeview(lf, columns=cols, show="headings",
#                                   style="FID.Treeview", selectmode="browse", height=6)
#         self._tree.heading("Name",   text="FULL NAME")
#         self._tree.heading("ZK ID",  text="WORKER ID")
#         self._tree.heading("Status", text="TODAY")
#         self._tree.column("Name",   width=270, anchor="w",      stretch=True)
#         self._tree.column("ZK ID",  width=90,  anchor="center")
#         self._tree.column("Status", width=110, anchor="center")
#         for tag, col in [("in", ORANGE2), ("out", GREEN2), ("none", ACCENT2)]:
#             self._tree.tag_configure(tag, foreground=col)

#         vsb = ttk.Scrollbar(lf, orient="vertical", command=self._tree.yview)
#         self._tree.configure(yscrollcommand=vsb.set)
#         self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         vsb.pack(side=tk.RIGHT, fill=tk.Y)
#         self._tree.bind("<Double-1>",   self._on_select)
#         self._tree.bind("<Return>",     self._on_select)
#         self._tree.bind("<Up>",         self._up_to_entry)
#         _make_sep(self, BORDER2)

#         ft = tk.Frame(self, bg=CARD, padx=20, pady=10); ft.pack(fill=tk.X)
#         btn_sel = tk.Button(ft, text="✔ USE SELECTED ID",
#                             font=("Courier", 9, "bold"), relief=tk.FLAT,
#                             bg=TEAL_DIM, fg=TEAL,
#                             activebackground=TEAL, activeforeground=BG,
#                             cursor="hand2", padx=14, pady=6, command=self._on_select)
#         btn_sel.pack(side=tk.LEFT)
#         _btn_hover(btn_sel, TEAL, BG, TEAL_DIM, TEAL)

#         btn_cancel = tk.Button(ft, text="✕ CANCEL",
#                                font=("Courier", 9, "bold"), relief=tk.FLAT,
#                                bg=BORDER, fg=TEXT2,
#                                activebackground=RED_DIM, activeforeground=RED,
#                                cursor="hand2", padx=14, pady=6, command=self.destroy)
#         btn_cancel.pack(side=tk.RIGHT)
#         _btn_hover(btn_cancel, RED_DIM, RED, BORDER, TEXT2)

#     def _focus_list(self, _=None):
#         children = self._tree.get_children()
#         if children:
#             self._tree.focus(children[0])
#             self._tree.selection_set(children[0])
#             self._tree.focus_set()

#     def _up_to_entry(self, _=None):
#         idx = self._tree.index(self._tree.focus())
#         if idx == 0:
#             self.name_entry.focus_set()

#     def _on_type(self):
#         if self._search_job:
#             self.after_cancel(self._search_job)
#         query = self._name_var.get().strip()
#         if len(query) < 2:
#             self._status_lbl.config(text="Type at least 2 characters…", fg=MUTED)
#             self._tree.delete(*self._tree.get_children())
#             return
#         self._status_lbl.config(text="Searching…", fg=ORANGE2)
#         self._search_job = self.after(
#             500, lambda: threading.Thread(
#                 target=self._do_search, args=(query,), daemon=True).start())

#     def _do_search(self, query: str):
#         workers = search_workers_by_name(query)
#         self.after(0, lambda: self._populate(query, workers))

#     def _populate(self, query: str, workers: list):
#         if not self.winfo_exists():
#             return
#         self._results = workers
#         self._tree.delete(*self._tree.get_children())
#         if not workers:
#             self._status_lbl.config(
#                 text=f'No workers found matching "{query}"', fg=RED2)
#             return
#         for w in workers:
#             name    = w.get("Full_Name", "—")
#             zk_id   = str(w.get("ZKTeco_User_ID2", "—"))
#             status  = get_worker_status(zk_id)
#             labels  = {"checked_in": "⏱ IN", "done": "✔ OUT", "none": "— —"}
#             tag     = {"checked_in": "in", "done": "out", "none": "none"}.get(status, "none")
#             self._tree.insert("", tk.END,
#                               values=(name, zk_id, labels.get(status, "—")),
#                               tags=(tag,), iid=zk_id)
#         count = len(workers)
#         if count == 1 and query == self._name_var.get().strip():
#             self._status_lbl.config(text="✔ 1 match found — filling ID automatically…", fg=TEAL)
#             first = self._tree.get_children()[0]
#             self._tree.selection_set(first)
#             self._tree.focus(first)
#             self.after(600, self._on_select)
#             return
#         self._status_lbl.config(
#             text=f"Found {count} worker{'s' if count != 1 else ''} — double-click or Enter to select",
#             fg=TEAL)

#     def _on_select(self, _=None):
#         sel = self._tree.selection()
#         if not sel:
#             return
#         zk_id = sel[0]
#         if zk_id and zk_id != "—":
#             self.destroy()
#             self.on_select(zk_id)

# # ===========================================================
# # FINGERPRINT CANVAS
# # ===========================================================
# class FingerprintCanvas(tk.Canvas):
#     SIZE = 140
#     def __init__(self, parent, **kwargs):
#         super().__init__(parent, width=self.SIZE, height=self.SIZE,
#                          bg=CARD2, highlightthickness=0, **kwargs)
#         self._cx = self._cy = self.SIZE // 2
#         self._angle = 0; self._state = "idle"; self._phase = 0
#         self._arc_items = []
#         self._draw_base(); self._animate()

#     def _draw_base(self):
#         cx, cy = self._cx, self._cy
#         self.delete("fp")
#         self.create_oval(cx-64, cy-64, cx+64, cy+64,
#                          outline=BORDER2, width=1, tags="fp")
#         arc_defs = [(10,0,300,2),(18,20,280,2),(26,30,270,1),
#                     (34,15,290,1),(42,25,265,1),(50,10,285,1),(58,35,250,1)]
#         self._arc_items = []
#         for r, start, extent, w in arc_defs:
#             item = self.create_arc(cx-r, cy-r, cx+r, cy+r,
#                                    start=start, extent=extent,
#                                    outline=MUTED, width=w,
#                                    style="arc", tags="fp")
#             self._arc_items.append(item)
#         self._centre = self.create_oval(cx-5, cy-5, cx+5, cy+5,
#                                         fill=MUTED, outline="", tags="fp")
#         self._spin = self.create_arc(cx-58, cy-58, cx+58, cy+58,
#                                      start=0, extent=0,
#                                      outline=ACCENT, width=3,
#                                      style="arc", tags="fp")

#     def start(self):    self._state = "scanning"
#     def stop_ok(self):
#         self._state = "ok"
#         for item in self._arc_items: self.itemconfig(item, outline=GREEN2)
#         self.itemconfig(self._centre, fill=GREEN2)
#         self.itemconfig(self._spin, extent=0)
#     def stop_err(self, _=""):
#         self._state = "error"
#         for item in self._arc_items: self.itemconfig(item, outline=RED2)
#         self.itemconfig(self._centre, fill=RED2)
#         self.itemconfig(self._spin, extent=0)
#     def reset(self):
#         self._state = "idle"; self._angle = 0; self._draw_base()

#     def _animate(self):
#         self._phase = (self._phase + 1) % 120
#         if self._state == "scanning":
#             self._angle = (self._angle + 6) % 360
#             sweep = int(200 * abs(math.sin(math.radians(self._angle))))
#             self.itemconfig(self._spin, start=self._angle, extent=sweep, outline=ACCENT)
#             for i, item in enumerate(self._arc_items):
#                 a  = 0.3 + 0.7 * abs(math.sin(math.radians((self._phase + i*10) * 4)))
#                 rv = int(int(ACCENT[1:3], 16) * a)
#                 gv = int(int(ACCENT[3:5], 16) * a)
#                 bv = int(int(ACCENT[5:7], 16) * a)
#                 self.itemconfig(item, outline=f"#{rv:02x}{gv:02x}{bv:02x}")
#             a2 = 0.4 + 0.6 * abs(math.sin(math.radians(self._phase * 3)))
#             rv = int(int(ACCENT[1:3], 16) * a2)
#             gv = int(int(ACCENT[3:5], 16) * a2)
#             bv = int(int(ACCENT[5:7], 16) * a2)
#             self.itemconfig(self._centre, fill=f"#{rv:02x}{gv:02x}{bv:02x}")
#         elif self._state == "ok":
#             a  = 0.6 + 0.4 * abs(math.sin(math.radians(self._phase * 2)))
#             rv = int(int(GREEN2[1:3], 16) * a)
#             gv = int(int(GREEN2[3:5], 16) * a)
#             bv = int(int(GREEN2[5:7], 16) * a)
#             col = f"#{rv:02x}{gv:02x}{bv:02x}"
#             for item in self._arc_items: self.itemconfig(item, outline=col)
#             self.itemconfig(self._centre, fill=col)
#         elif self._state == "error":
#             a  = 0.4 + 0.6 * abs(math.sin(math.radians(self._phase * 6)))
#             rv = int(int(RED2[1:3], 16) * a)
#             gv = int(int(RED2[3:5], 16) * a)
#             bv = int(int(RED2[5:7], 16) * a)
#             col = f"#{rv:02x}{gv:02x}{bv:02x}"
#             for item in self._arc_items: self.itemconfig(item, outline=col)
#             self.itemconfig(self._centre, fill=col)
#         else:
#             a  = 0.25 + 0.20 * abs(math.sin(math.radians(self._phase * 1.5)))
#             rv = min(int(int(MUTED[1:3], 16) * a * 2.5), 255)
#             gv = min(int(int(MUTED[3:5], 16) * a * 2.5), 255)
#             bv = min(int(int(MUTED[5:7], 16) * a * 2.5), 255)
#             col = f"#{rv:02x}{gv:02x}{bv:02x}"
#             for item in self._arc_items: self.itemconfig(item, outline=col)
#             self.itemconfig(self._spin, extent=0)
#         self.after(30, self._animate)

# # ===========================================================
# # PULSING LED
# # ===========================================================
# class PulseLED(tk.Canvas):
#     SIZE = 12
#     def __init__(self, parent, color=ACCENT):
#         super().__init__(parent, width=self.SIZE, height=self.SIZE,
#                          bg=parent.cget("bg"), highlightthickness=0)
#         r = self.SIZE // 2
#         self._dot   = self.create_oval(2, 2, r*2-2, r*2-2, fill=color, outline="")
#         self._color = color; self._phase = 0
#         self._pulse()

#     def set_color(self, c):
#         self._color = c
#         self.itemconfig(self._dot, fill=c)

#     def _pulse(self):
#         self._phase = (self._phase + 1) % 60
#         a = 0.55 + 0.45 * abs((self._phase % 60) - 30) / 30
#         c = self._color
#         try:
#             rv = int(int(c[1:3], 16) * a)
#             gv = int(int(c[3:5], 16) * a)
#             bv = int(int(c[5:7], 16) * a)
#             self.itemconfig(self._dot, fill=f"#{rv:02x}{gv:02x}{bv:02x}")
#         except Exception:
#             pass
#         self.after(50, self._pulse)

# # ===========================================================
# # DONUT RING
# # ===========================================================
# class DonutRing(tk.Canvas):
#     SIZE = 80
#     def __init__(self, parent, **kwargs):
#         super().__init__(parent, width=self.SIZE, height=self.SIZE,
#                          bg=CARD2, highlightthickness=0, **kwargs)
#         self._val = 0.0; self._color = GREEN2; self._phase = 0
#         self._draw(0); self._tick()

#     def set_value(self, fraction, color=GREEN2):
#         self._val = max(0.0, min(1.0, fraction)); self._color = color

#     def _draw(self, fraction):
#         self.delete("all")
#         cx = cy = self.SIZE // 2; r = cx - 6
#         self.create_arc(cx-r, cy-r, cx+r, cy+r,
#                         start=0, extent=359.9, outline=BORDER2, width=10, style="arc")
#         if fraction > 0:
#             self.create_arc(cx-r, cy-r, cx+r, cy+r,
#                             start=90, extent=-(fraction * 359.9),
#                             outline=self._color, width=10, style="arc")
#         self.create_text(cx, cy, text=f"{int(fraction*100)}%",
#                          font=("Courier", 11, "bold"),
#                          fill=self._color if fraction > 0 else MUTED)

#     def _tick(self):
#         self._phase += 1; self._draw(self._val); self.after(150, self._tick)

# # ===========================================================
# # ADMIN PANEL  (includes Daily Report tab)
# # ===========================================================
# class AdminPanel(tk.Toplevel):
#     def __init__(self, parent):
#         super().__init__(parent)
#         self.title("Attendance Command Center")
#         self.configure(bg=BG); self.resizable(True, True)
#         sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
#         W, H   = min(sw, 1200), min(sh, 760)
#         self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
#         self._all_rows  = []; self._sort_col = None; self._sort_asc = True
#         self._build(); self.refresh()

#     def _build(self):
#         # ── header ──────────────────────────────────────────────────
#         hdr = tk.Frame(self, bg=CARD); hdr.pack(fill=tk.X)
#         tk.Frame(hdr, bg=PURPLE, height=2).pack(fill=tk.X)
#         hi  = tk.Frame(hdr, bg=CARD, padx=24, pady=14); hi.pack(fill=tk.X)
#         lf  = tk.Frame(hi, bg=CARD); lf.pack(side=tk.LEFT)
#         tk.Label(lf, text="ATTENDANCE COMMAND CENTER",
#                  font=("Courier", 13, "bold"), bg=CARD, fg=PURPLE).pack(anchor="w")
#         self.sub_lbl = tk.Label(lf, text="", font=("Courier", 8), bg=CARD, fg=TEXT2)
#         self.sub_lbl.pack(anchor="w", pady=(2, 0))
#         rf = tk.Frame(hi, bg=CARD); rf.pack(side=tk.RIGHT)
#         for txt, cmd, bg_, fg_ in [
#             ("↻ REFRESH",   self.refresh,  ACCENT_DIM, ACCENT2),
#             ("⬇ EXPORT CSV", self._export,  GREEN_DIM,  GREEN2),
#             ("✕ CLOSE",     self.destroy,  BORDER,     TEXT2)]:
#             b = tk.Button(rf, text=txt, font=("Courier", 9, "bold"), relief=tk.FLAT,
#                           bg=bg_, fg=fg_, cursor="hand2", padx=14, pady=6, command=cmd)
#             b.pack(side=tk.LEFT, padx=(0, 6))

#         # ── notebook tabs ────────────────────────────────────────────
#         style = ttk.Style(self); style.theme_use("default")
#         style.configure("Admin.TNotebook",        background=BG,   borderwidth=0)
#         style.configure("Admin.TNotebook.Tab",    background=CARD, foreground=TEXT2,
#                         font=("Courier", 9, "bold"), padding=[18, 8])
#         style.map("Admin.TNotebook.Tab",
#                   background=[("selected", PURPLE_DIM)],
#                   foreground=[("selected", PURPLE)])

#         nb = ttk.Notebook(self, style="Admin.TNotebook")
#         nb.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

#         # Tab 1 — All Records
#         self._tab_records = tk.Frame(nb, bg=BG)
#         nb.add(self._tab_records, text="⚙  ALL RECORDS")

#         # Tab 2 — Daily Report
#         self._tab_report = tk.Frame(nb, bg=BG)
#         nb.add(self._tab_report, text="📋  DAILY REPORT")

#         self._build_records_tab(self._tab_records)
#         self._build_report_tab(self._tab_report)

#     # ================================================================
#     #  TAB 1 — ALL RECORDS
#     # ================================================================
#     def _build_records_tab(self, parent):
#         sf = tk.Frame(parent, bg=BG, padx=20, pady=8); sf.pack(fill=tk.X)
#         tk.Label(sf, text="SEARCH:", font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(side=tk.LEFT)
#         self._search_var = tk.StringVar()
#         self._search_var.trace_add("write", lambda *_: self._apply_filter())
#         tk.Entry(sf, textvariable=self._search_var, font=("Courier", 10),
#                  bg=CARD2, fg=WHITE, insertbackground=GOLD, bd=0, width=30
#                  ).pack(side=tk.LEFT, padx=(8, 0), ipady=4)
#         self._count_lbl = tk.Label(sf, text="", font=("Courier", 8), bg=BG, fg=MUTED)
#         self._count_lbl.pack(side=tk.RIGHT)

#         self.kpi_fr = tk.Frame(parent, bg=BG, padx=20, pady=10); self.kpi_fr.pack(fill=tk.X)
#         _make_sep(parent, BORDER2)

#         tw = tk.Frame(parent, bg=BG, padx=20, pady=10); tw.pack(fill=tk.BOTH, expand=True)
#         style = ttk.Style(self); style.theme_use("default")
#         style.configure("Cmd.Treeview", background=CARD2, foreground=TEXT,
#                          fieldbackground=CARD2, rowheight=28,
#                          font=("Courier", 9), borderwidth=0)
#         style.configure("Cmd.Treeview.Heading", background=CARD,
#                          foreground=GOLD, font=("Courier", 9, "bold"),
#                          relief="flat", borderwidth=0)
#         style.map("Cmd.Treeview",
#                   background=[("selected", ACCENT_DIM)],
#                   foreground=[("selected", ACCENT2)])

#         cols    = ("Init", "Name", "Check-In", "Check-Out", "Hours", "OT", "Early?", "Late", "Status")
#         widths  = (50, 190, 110, 110, 75, 80, 70, 80, 95)
#         anchors = ("center", "w", "center", "center", "center",
#                    "center", "center", "center", "center")
#         self.tree = ttk.Treeview(tw, columns=cols, show="headings",
#                                   style="Cmd.Treeview", selectmode="browse")
#         for col, w, a in zip(cols, widths, anchors):
#             self.tree.heading(col, text=col.upper(),
#                               command=lambda c=col: self._sort_by(c))
#             self.tree.column(col, width=w, anchor=a, stretch=(col == "Name"))
#         for tag, col in [("late", ORANGE2), ("ot", PURPLE), ("complete", GREEN2),
#                          ("still_in", ACCENT2), ("early", CYAN2),
#                          ("auto", "#c4b5fd"), ("alt", "#0e1320")]:
#             self.tree.tag_configure(
#                 tag,
#                 foreground=col if tag != "alt" else TEXT,
#                 background="#0e1320" if tag == "alt" else "")

#         vsb = ttk.Scrollbar(tw, orient="vertical", command=self.tree.yview)
#         self.tree.configure(yscrollcommand=vsb.set)
#         self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         vsb.pack(side=tk.RIGHT, fill=tk.Y)

#     # ================================================================
#     #  TAB 2 — DAILY REPORT  (Late Arrivals & Early Checkouts)
#     # ================================================================
#     def _build_report_tab(self, parent):
#         # sub-header with refresh
#         hdr = tk.Frame(parent, bg=CARD, padx=20, pady=10); hdr.pack(fill=tk.X)
#         tk.Frame(hdr, bg=GOLD, height=2).pack(fill=tk.X, side=tk.TOP)
#         hi = tk.Frame(hdr, bg=CARD); hi.pack(fill=tk.X, pady=(6, 0))
#         lf = tk.Frame(hi, bg=CARD); lf.pack(side=tk.LEFT)
#         tk.Label(lf, text="📋 DAILY REPORT — Late Arrivals & Early Checkouts",
#                  font=("Courier", 11, "bold"), bg=CARD, fg=GOLD).pack(anchor="w")
#         self._report_sub_lbl = tk.Label(lf, text="", font=("Courier", 8), bg=CARD, fg=TEXT2)
#         self._report_sub_lbl.pack(anchor="w", pady=(2, 0))
#         rf = tk.Frame(hi, bg=CARD); rf.pack(side=tk.RIGHT)
#         b = tk.Button(rf, text="↻ REFRESH REPORT", font=("Courier", 9, "bold"),
#                       relief=tk.FLAT, bg=ACCENT_DIM, fg=ACCENT2, cursor="hand2",
#                       padx=14, pady=6, command=self._refresh_report)
#         b.pack()
#         _btn_hover(b, ACCENT2, BG, ACCENT_DIM, ACCENT2)

#         # KPI strip
#         self._report_kpi_fr = tk.Frame(parent, bg=BG, padx=20, pady=10)
#         self._report_kpi_fr.pack(fill=tk.X)
#         tk.Frame(parent, bg=BORDER2, height=1).pack(fill=tk.X)

#         # scrollable body
#         body_wrap = tk.Frame(parent, bg=BG); body_wrap.pack(fill=tk.BOTH, expand=True)
#         self._report_canvas = tk.Canvas(body_wrap, bg=BG, highlightthickness=0)
#         vsb = ttk.Scrollbar(body_wrap, orient="vertical",
#                              command=self._report_canvas.yview)
#         self._report_canvas.configure(yscrollcommand=vsb.set)
#         vsb.pack(side=tk.RIGHT, fill=tk.Y)
#         self._report_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         self._report_body     = tk.Frame(self._report_canvas, bg=BG)
#         self._report_body_win = self._report_canvas.create_window(
#             (0, 0), window=self._report_body, anchor="nw")
#         self._report_body.bind("<Configure>",   self._on_report_body_resize)
#         self._report_canvas.bind("<Configure>", self._on_report_canvas_resize)
#         self._report_canvas.bind_all("<MouseWheel>",
#             lambda e: self._report_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
#         self._report_canvas.bind_all("<Button-4>",
#             lambda e: self._report_canvas.yview_scroll(-1, "units"))
#         self._report_canvas.bind_all("<Button-5>",
#             lambda e: self._report_canvas.yview_scroll( 1, "units"))

#     def _on_report_body_resize(self, _=None):
#         self._report_canvas.configure(
#             scrollregion=self._report_canvas.bbox("all"))

#     def _on_report_canvas_resize(self, event):
#         self._report_canvas.itemconfig(self._report_body_win, width=event.width)

#     def _make_report_section(self, parent, title, accent, icon, rows, col_defs):
#         sec_hdr = tk.Frame(parent, bg=CARD2); sec_hdr.pack(fill=tk.X)
#         tk.Frame(sec_hdr, bg=accent, width=6).pack(side=tk.LEFT, fill=tk.Y)
#         inner_hdr = tk.Frame(sec_hdr, bg=CARD2, padx=24, pady=14)
#         inner_hdr.pack(side=tk.LEFT, fill=tk.X, expand=True)
#         tk.Label(inner_hdr, text=f"{icon} {title}",
#                  font=("Courier", 14, "bold"), bg=CARD2, fg=accent).pack(anchor="w")
#         self._report_count_labels[title] = tk.Label(
#             inner_hdr, text="", font=("Courier", 9), bg=CARD2, fg=TEXT2)
#         self._report_count_labels[title].pack(anchor="w", pady=(2, 0))
#         tk.Frame(parent, bg=accent, height=2).pack(fill=tk.X)

#         grid_wrap = tk.Frame(parent, bg=BG); grid_wrap.pack(fill=tk.X)
#         grid_wrap.columnconfigure(0, minsize=6)
#         for ci, (_, _, minw, wt) in enumerate(col_defs):
#             grid_wrap.columnconfigure(ci+1, minsize=minw, weight=wt)

#         tk.Frame(grid_wrap, bg=accent, width=6).grid(row=0, column=0, sticky="nsew")
#         for ci, (lbl, _, _, _) in enumerate(col_defs):
#             cell = tk.Frame(grid_wrap, bg=CARD, padx=14, pady=9)
#             cell.grid(row=0, column=ci+1, sticky="nsew")
#             tk.Label(cell, text=lbl, font=("Courier", 9, "bold"),
#                      bg=CARD, fg=accent, anchor="w").pack(fill=tk.X)
#         tk.Frame(grid_wrap, bg=accent, height=1).grid(
#             row=1, column=0, columnspan=len(col_defs)+1, sticky="ew")

#         if not rows:
#             empty = tk.Frame(grid_wrap, bg=BG)
#             empty.grid(row=2, column=0, columnspan=len(col_defs)+1, sticky="ew")
#             tk.Label(empty, text=f"  No {title.lower()} recorded today.",
#                      font=("Courier", 11), bg=BG, fg=MUTED, pady=20
#                      ).pack(anchor="w", padx=24)
#         else:
#             for ri, row in enumerate(rows):
#                 grid_row = ri + 2
#                 row_bg   = CARD2 if ri % 2 == 0 else CARD
#                 tk.Frame(grid_wrap, bg=accent, width=6).grid(
#                     row=grid_row, column=0, sticky="nsew")
#                 for ci, (_, key, _, _) in enumerate(col_defs):
#                     val  = str(row.get(key, "—"))
#                     fg_  = TEXT
#                     if key == "zk_id":  fg_ = GOLD
#                     if key == "name":   fg_ = WHITE
#                     if key == "status": fg_ = accent
#                     bold = key in ("zk_id", "name")
#                     cell = tk.Frame(grid_wrap, bg=row_bg, padx=14, pady=11)
#                     cell.grid(row=grid_row, column=ci+1, sticky="nsew")
#                     tk.Label(cell, text=val,
#                              font=("Courier", 11, "bold" if bold else "normal"),
#                              bg=row_bg, fg=fg_, anchor="w").pack(fill=tk.X)
#                 tk.Frame(grid_wrap, bg=BORDER, height=1).grid(
#                     row=grid_row, column=0, columnspan=len(col_defs)+1, sticky="sew")

#         tk.Frame(parent, bg=BORDER2, height=1).pack(fill=tk.X)
#         tk.Frame(parent, bg=BG, height=24).pack()

#     def _refresh_report(self):
#         for w in self._report_body.winfo_children(): w.destroy()
#         self._report_count_labels = {}
#         lock  = load_lock()
#         now   = datetime.now()
#         cin   = lock.get("checked_in",  {})
#         cout  = lock.get("checked_out", {})
#         early_limit  = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                                    second=0, microsecond=0)
#         late_rows  = []
#         early_rows = []
#         all_workers = {**cin, **cout}

#         for zk_id, info in sorted(all_workers.items(),
#             key=lambda x: (x[1].get("time","") or x[1].get("checkin_time",""))
#                           if isinstance(x[1], dict) else ""):
#             if not isinstance(info, dict): continue
#             if not info.get("is_late", False): continue
#             name   = info.get("name", zk_id)
#             ci_raw = info.get("time","") or info.get("checkin_time","")
#             is_out = zk_id in cout
#             try:
#                 ci_disp = datetime.strptime(ci_raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M:%S")
#             except Exception:
#                 ci_disp = ci_raw[-8:] if len(ci_raw) >= 8 else ci_raw or "—"
#             status = "✔ OUT" if is_out else "● ACTIVE"
#             late_rows.append({"zk_id": zk_id, "name": name,
#                               "checkin": ci_disp,
#                               "late_note": info.get("late_note",""),
#                               "status": status})

#         for zk_id, info in sorted(cout.items(),
#             key=lambda x: x[1].get("time","") if isinstance(x[1], dict) else ""):
#             if not isinstance(info, dict): continue
#             co_raw = info.get("time","")
#             try:
#                 co_dt    = datetime.strptime(co_raw, "%H:%M:%S").replace(
#                     year=now.year, month=now.month, day=now.day)
#                 is_early = co_dt < early_limit
#             except Exception:
#                 is_early = False
#             if not is_early: continue
#             name   = info.get("name", zk_id)
#             ci_raw = info.get("checkin_time","")
#             try:
#                 ci_disp = datetime.strptime(ci_raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M:%S")
#             except Exception:
#                 ci_disp = ci_raw[-8:] if len(ci_raw) >= 8 else ci_raw or "—"
#             hrs   = info.get("total_hours", 0)
#             h_str = (f"{int(hrs)}h {int((hrs%1)*60):02d}m"
#                      if isinstance(hrs, (int, float)) else "—")
#             early_rows.append({"zk_id": zk_id, "name": name,
#                                 "checkin": ci_disp, "checkout": co_raw or "—",
#                                 "hours": h_str, "status": "⚡ LEFT EARLY"})

#         # KPI tiles
#         for w in self._report_kpi_fr.winfo_children(): w.destroy()
#         total_in = len(cin) + len(cout)
#         for label, val, fg, border in [
#             ("TOTAL IN TODAY",   total_in,        WHITE,   BORDER2),
#             ("STILL ON-SITE",    len(cin),         ACCENT2, "#0d1f3f"),
#             ("CHECKED OUT",      len(cout),        GREEN2,  "#0a2e17"),
#             ("LATE ARRIVALS",    len(late_rows),   ORANGE2, "#3d1f00"),
#             ("EARLY CHECKOUTS",  len(early_rows),  CYAN2,   "#083344"),
#         ]:
#             tile = tk.Frame(self._report_kpi_fr, bg=CARD2, padx=20, pady=10,
#                             highlightbackground=border, highlightthickness=1)
#             tile.pack(side=tk.LEFT, padx=(0, 10), fill=tk.Y)
#             tk.Label(tile, text=str(val),
#                      font=("Courier", 28, "bold"), bg=CARD2, fg=fg).pack()
#             tk.Label(tile, text=label,
#                      font=("Courier", 7, "bold"),  bg=CARD2, fg=TEXT2).pack()

#         self._make_report_section(
#             self._report_body, title="LATE ARRIVALS",
#             accent=ORANGE2, icon="⚠", rows=late_rows,
#             col_defs=[("ZK ID","zk_id",80,0),("FULL NAME","name",260,1),
#                       ("CHECKED IN","checkin",120,0),
#                       ("LATE BY","late_note",160,0),
#                       ("STATUS","status",120,0)])
#         self._make_report_section(
#             self._report_body, title="EARLY CHECKOUTS",
#             accent=CYAN2, icon="⚡", rows=early_rows,
#             col_defs=[("ZK ID","zk_id",80,0),("FULL NAME","name",260,1),
#                       ("CHECKED IN","checkin",120,0),
#                       ("CHECKED OUT","checkout",120,0),
#                       ("HOURS","hours",100,0),
#                       ("STATUS","status",140,0)])

#         now_str = now.strftime("%H:%M:%S")
#         self._report_sub_lbl.config(text=(
#             f"Date: {lock.get('date', now.strftime('%Y-%m-%d'))}  "
#             f"Shift start: {SHIFT_START_H:02d}:{SHIFT_START_M:02d}  "
#             f"Early threshold: before {EARLY_CHECKOUT_H:02d}:{EARLY_CHECKOUT_M:02d}  "
#             f"Last refresh: {now_str}"))

#         if "LATE ARRIVALS" in self._report_count_labels:
#             self._report_count_labels["LATE ARRIVALS"].config(
#                 text=f"{len(late_rows)} worker{'s' if len(late_rows)!=1 else ''} arrived late today")
#         if "EARLY CHECKOUTS" in self._report_count_labels:
#             self._report_count_labels["EARLY CHECKOUTS"].config(
#                 text=f"{len(early_rows)} worker{'s' if len(early_rows)!=1 else ''} "
#                      f"left before {EARLY_CHECKOUT_H:02d}:{EARLY_CHECKOUT_M:02d}")

#         self._report_canvas.update_idletasks()
#         self._report_canvas.configure(
#             scrollregion=self._report_canvas.bbox("all"))

#     # ================================================================
#     #  SHARED RECORDS TAB METHODS
#     # ================================================================
#     def _sort_by(self, col):
#         self._sort_asc = not self._sort_asc if self._sort_col == col else True
#         self._sort_col = col; self._apply_filter()

#     def _apply_filter(self):
#         q = self._search_var.get().strip().lower()
#         visible = [r for r in self._all_rows
#                    if not q or any(q in str(v).lower() for v in r["values"])]
#         if self._sort_col:
#             cols = ["Init", "Name", "Check-In", "Check-Out",
#                     "Hours", "OT", "Early?", "Late", "Status"]
#             idx  = cols.index(self._sort_col) if self._sort_col in cols else 0
#             visible.sort(key=lambda r: str(r["values"][idx]),
#                          reverse=not self._sort_asc)
#         self.tree.delete(*self.tree.get_children())
#         for i, r in enumerate(visible):
#             tags = list(r["tags"]) + ["alt"] if i % 2 == 1 else list(r["tags"])
#             self.tree.insert("", tk.END, values=r["values"], tags=tuple(tags))
#         self._count_lbl.config(text=f"{len(visible)}/{len(self._all_rows)} records")

#     def refresh(self):
#         self._all_rows = []
#         lock  = load_lock()
#         cin   = lock.get("checked_in",  {})
#         cout  = lock.get("checked_out", {})
#         late_count = ot_count = early_count = auto_count = 0
#         now   = datetime.now()
#         early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                                   second=0, microsecond=0)

#         for zk_id, info in sorted(cout.items(),
#             key=lambda x: x[1].get("checkin_time", "") if isinstance(x[1], dict) else ""):
#             if not isinstance(info, dict): continue
#             name  = info.get("name", zk_id)
#             ci    = info.get("checkin_time", "---"); ci_s = ci[-8:] if len(ci) > 8 else ci
#             co    = info.get("time", "---")
#             hrs   = info.get("total_hours",    0)
#             ot    = info.get("overtime_hours", 0)
#             late  = info.get("is_late",  False)
#             auto  = info.get("auto_checkout", False)
#             h_str = (f"{int(hrs)}h {int((hrs%1)*60):02d}m"
#                      if isinstance(hrs, (int, float)) else str(hrs))
#             o_str = (f"{int(ot)}h {int((ot%1)*60):02d}m" if ot else "---")
#             is_early = False
#             try:
#                 co_dt    = datetime.strptime(co, "%H:%M:%S").replace(
#                     year=now.year, month=now.month, day=now.day)
#                 is_early = co_dt < early_limit
#             except Exception: pass
#             if late:     late_count  += 1
#             if ot > 0:   ot_count    += 1
#             if is_early: early_count += 1
#             if auto:     auto_count  += 1
#             tags = []
#             if late:     tags.append("late")
#             if ot > 0:   tags.append("ot")
#             if is_early: tags.append("early")
#             if auto:     tags.append("auto")
#             tags.append("complete")
#             self._all_rows.append({"values": (
#                 _initials(name), name, ci_s, co, h_str, o_str,
#                 "⚡ YES" if is_early else "---",
#                 "⚠ LATE" if late else "---",
#                 "AUTO" if auto else "✔ DONE"), "tags": tags})

#         for zk_id, info in sorted(cin.items(),
#             key=lambda x: x[1].get("time", "") if isinstance(x[1], dict) else ""):
#             if not isinstance(info, dict): continue
#             name = info.get("name", zk_id)
#             ci   = info.get("time", "---"); late = info.get("is_late", False)
#             try:
#                 dt_in   = datetime.strptime(ci, "%d-%b-%Y %H:%M:%S")
#                 elapsed = (now - dt_in).total_seconds() / 3600
#                 h_str   = f"{int(elapsed)}h {int((elapsed%1)*60):02d}m"
#             except Exception:
#                 h_str = "---"
#             ci_s = ci[-8:] if len(ci) > 8 else ci
#             if late: late_count += 1
#             tags = ["late"] if late else []
#             tags.append("still_in")
#             self._all_rows.append({"values": (
#                 _initials(name), name, ci_s, "---", h_str, "---", "---",
#                 "⚠ LATE" if late else "---", "● ACTIVE"), "tags": tags})

#         self._apply_filter()
#         for w in self.kpi_fr.winfo_children(): w.destroy()
#         total = len(cin) + len(cout)
#         for label, val, fg, border in [
#             ("TOTAL",       total,       WHITE,   BORDER2),
#             ("CHECKED IN",  total,       ACCENT2, "#0d1f3f"),
#             ("CHECKED OUT", len(cout),   GREEN2,  "#0a3321"),
#             ("AUTO-OUT",    auto_count,  "#c4b5fd","#1e0a40"),
#             ("EARLY OUT",   early_count, CYAN2,   "#083344"),
#             ("LATE",        late_count,  ORANGE2, "#3d1f00"),
#             ("OVERTIME",    ot_count,    PURPLE,  "#1e0a40")]:
#             tile = tk.Frame(self.kpi_fr, bg=CARD2, padx=13, pady=8,
#                             highlightbackground=border, highlightthickness=1)
#             tile.pack(side=tk.LEFT, padx=(0, 8), fill=tk.Y)
#             tk.Label(tile, text=str(val), font=("Courier", 20, "bold"),
#                      bg=CARD2, fg=fg).pack()
#             tk.Label(tile, text=label, font=("Courier", 6, "bold"),
#                      bg=CARD2, fg=TEXT2).pack()

#         self.sub_lbl.config(text=(
#             f"Date:{lock.get('date','')}  "
#             f"Shift:{SHIFT_START_H:02d}:{SHIFT_START_M:02d}  "
#             f"Std:{SHIFT_HOURS}h  Grace:{GRACE_MINUTES}min  "
#             f"Auto-out:{AUTO_CHECKOUT_H:02d}:00  "
#             f"Refreshed:{datetime.now().strftime('%H:%M:%S')}"))

#         # also refresh the report tab data
#         self._refresh_report()

#     def _export(self):
#         fname = export_daily_summary()
#         if fname:
#             messagebox.showinfo("Exported", f"Saved:\n{os.path.abspath(fname)}", parent=self)
#         else:
#             messagebox.showwarning("Nothing to Export", "No records for today.", parent=self)


# # ===========================================================
# # MAIN GUI
# # ===========================================================
# class FingerprintGUI:
#     def __init__(self, root):
#         self.root   = root
#         self.root.title("Wavemark Properties — Attendance Terminal")
#         self.root.configure(bg=BG)
#         self.root.resizable(False, False)
#         self._busy         = False
#         self._debounce_job = None
#         self._log_lines    = 0
#         self._gui_q: queue.Queue = queue.Queue()
#         sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
#         W, H   = min(sw, 980), min(sh, 800)
#         self.root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
#         self._build_ui()
#         self._tick_clock()
#         self._tick_stats()
#         self._tick_autocheckout()
#         self._drain_q()
#         self.root.protocol("WM_DELETE_WINDOW", self._on_close)

#         # Startup check — warn user immediately if .env is broken
#         self.root.after(1500, self._startup_token_check)

#     def _startup_token_check(self):
#         def _check():
#             token = get_access_token()
#             if not token:
#                 self._gui(lambda: self.log(
#                     "⚠ WARNING: Could not connect to Zoho — "
#                     "check CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN in .env\n"
#                     "  Visit https://api-console.zoho.com to regenerate credentials.", "err"))
#         threading.Thread(target=_check, daemon=True).start()

#     def _drain_q(self):
#         try:
#             while True: self._gui_q.get_nowait()()
#         except queue.Empty: pass
#         self.root.after(50, self._drain_q)

#     def _gui(self, fn):
#         self._gui_q.put(fn)

#     # ------ UI BUILD ------
#     def _build_ui(self):
#         self._build_header(); self._build_body()
#         self._build_footer(); self._build_flash()

#     def _build_header(self):
#         hdr = tk.Frame(self.root, bg=CARD); hdr.pack(fill=tk.X)
#         tk.Frame(hdr, bg=GOLD, height=3).pack(fill=tk.X)
#         hi  = tk.Frame(hdr, bg=CARD, padx=28, pady=14); hi.pack(fill=tk.X)
#         lf  = tk.Frame(hi, bg=CARD); lf.pack(side=tk.LEFT)
#         tk.Label(lf, text="WAVEMARK PROPERTIES LIMITED",
#                  font=("Courier", 11, "bold"), bg=CARD, fg=GOLD).pack(anchor="w")
#         tk.Label(lf, text="Biometric Attendance Terminal · v5.3 · 2000-user edition",
#                  font=("Courier", 8), bg=CARD, fg=MUTED).pack(anchor="w", pady=(1, 0))
#         rf = tk.Frame(hi, bg=CARD); rf.pack(side=tk.RIGHT)
#         btn_admin = tk.Button(rf, text="⚙ ADMIN PANEL",
#                               font=("Courier", 8, "bold"), relief=tk.FLAT,
#                               bg=PURPLE_DIM, fg=PURPLE,
#                               activebackground=PURPLE, activeforeground=WHITE,
#                               cursor="hand2", padx=10, pady=5,
#                               command=self._open_admin)
#         btn_admin.pack(anchor="e", pady=(0, 6))
#         _btn_hover(btn_admin, PURPLE, WHITE, PURPLE_DIM, PURPLE)
#         self.date_lbl  = tk.Label(rf, text="", font=("Courier", 8),  bg=CARD, fg=TEXT2)
#         self.date_lbl.pack(anchor="e")
#         self.clock_lbl = tk.Label(rf, text="", font=("Courier", 24, "bold"), bg=CARD, fg=WHITE)
#         self.clock_lbl.pack(anchor="e")
#         _make_sep(self.root, BORDER2)
#         sbar = tk.Frame(self.root, bg=CARD2, padx=28, pady=6); sbar.pack(fill=tk.X)
#         tk.Label(sbar, text=(f"SHIFT {SHIFT_START_H:02d}:{SHIFT_START_M:02d} · "
#                              f"STD {SHIFT_HOURS}H · GRACE {GRACE_MINUTES}MIN · "
#                              f"EARLY<{EARLY_CHECKOUT_H:02d}:00 · AUTO@{AUTO_CHECKOUT_H:02d}:00"),
#                  font=("Courier", 8), bg=CARD2, fg=MUTED).pack(side=tk.LEFT)
#         tk.Label(sbar, text="ENTER → auto-action   ESC → clear",
#                  font=("Courier", 8), bg=CARD2, fg=MUTED).pack(side=tk.RIGHT)

#     def _build_body(self):
#         body = tk.Frame(self.root, bg=BG, padx=24, pady=14)
#         body.pack(fill=tk.BOTH, expand=True)
#         cols = tk.Frame(body, bg=BG); cols.pack(fill=tk.BOTH, expand=True)
#         left  = tk.Frame(cols, bg=BG); left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         tk.Frame(cols, bg=BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y, padx=16)
#         right = tk.Frame(cols, bg=BG, width=300); right.pack(side=tk.LEFT, fill=tk.Y)
#         self._build_left(left); self._build_right(right)

#     def _build_left(self, parent):
#         id_card = tk.Frame(parent, bg=CARD2, highlightbackground=BORDER2, highlightthickness=1)
#         id_card.pack(fill=tk.X, pady=(0, 12))
#         ch = tk.Frame(id_card, bg=CARD, padx=18, pady=10); ch.pack(fill=tk.X)
#         tk.Label(ch, text="WORKER IDENTIFICATION",
#                  font=("Courier", 8, "bold"), bg=CARD, fg=TEXT2).pack(side=tk.LEFT)
#         self._led = PulseLED(ch, MUTED); self._led.pack(side=tk.RIGHT, padx=(0, 2))
#         _make_sep(id_card, BORDER)
#         ci = tk.Frame(id_card, bg=CARD2, padx=18, pady=14); ci.pack(fill=tk.X)
#         er = tk.Frame(ci, bg=CARD2); er.pack(fill=tk.X)
#         tk.Label(er, text="ID", font=("Courier", 8, "bold"),
#                  bg=CARD2, fg=MUTED, width=3, anchor="w").pack(side=tk.LEFT)
#         eb = tk.Frame(er, bg=GOLD, padx=1, pady=1); eb.pack(side=tk.LEFT, padx=(6, 0))
#         ei = tk.Frame(eb, bg="#09101a"); ei.pack()
#         self.user_entry = tk.Entry(ei, font=("Courier", 28, "bold"), width=9, bd=0,
#                                    bg="#09101a", fg=WHITE, insertbackground=GOLD,
#                                    selectbackground=GOLD2, selectforeground=BG)
#         self.user_entry.pack(padx=14, pady=8)
#         self.user_entry.bind("<KeyRelease>", self._on_key)
#         self.user_entry.bind("<Return>",     self._on_enter)
#         self.user_entry.bind("<Escape>",     lambda _: self._reset_ui())
#         self.user_entry.focus_set()
#         btn_clr = tk.Button(er, text="✕", font=("Courier", 10, "bold"), relief=tk.FLAT,
#                             bg=BORDER, fg=MUTED,
#                             activebackground=RED_DIM, activeforeground=RED,
#                             cursor="hand2", padx=8, pady=4, command=self._reset_ui)
#         btn_clr.pack(side=tk.LEFT, padx=(10, 0))
#         _btn_hover(btn_clr, RED_DIM, RED, BORDER, MUTED)

#         idf = tk.Frame(ci, bg=CARD2); idf.pack(fill=tk.X, pady=(12, 0))
#         self._avatar_cv = tk.Canvas(idf, width=48, height=48,
#                                     bg=CARD2, highlightthickness=0)
#         self._avatar_cv.pack(side=tk.LEFT, padx=(0, 12))
#         self._avatar_circle = self._avatar_cv.create_oval(2, 2, 46, 46,
#                                                            fill=BORDER, outline="")
#         self._avatar_text   = self._avatar_cv.create_text(24, 24, text="",
#                                                            font=("Courier", 13, "bold"),
#                                                            fill=MUTED)
#         info_col = tk.Frame(idf, bg=CARD2); info_col.pack(side=tk.LEFT, fill=tk.X)
#         self.name_lbl = tk.Label(info_col, text="—",
#                                   font=("Courier", 16, "bold"), bg=CARD2, fg=MUTED)
#         self.name_lbl.pack(anchor="w")
#         self.hint_lbl = tk.Label(info_col, text="Enter a Worker ID above",
#                                   font=("Courier", 9), bg=CARD2, fg=MUTED)
#         self.hint_lbl.pack(anchor="w", pady=(2, 0))

#         self.sf = tk.Frame(parent, bg=ACCENT_DIM,
#                            highlightbackground=ACCENT, highlightthickness=1)
#         self.sf.pack(fill=tk.X, pady=(0, 12))
#         sb_inner = tk.Frame(self.sf, bg=ACCENT_DIM); sb_inner.pack(fill=tk.X, padx=16, pady=10)
#         self._status_led = PulseLED(sb_inner, ACCENT)
#         self._status_led.pack(side=tk.LEFT, padx=(0, 8))
#         self.sl = tk.Label(sb_inner, text="Awaiting Worker ID",
#                            font=("Courier", 10, "bold"),
#                            bg=ACCENT_DIM, fg=ACCENT, anchor="w")
#         self.sl.pack(side=tk.LEFT, fill=tk.X)

#         # ── action buttons (Daily Report button REMOVED) ──
#         br = tk.Frame(parent, bg=BG); br.pack(fill=tk.X, pady=(0, 12))
#         self.btn_in = tk.Button(br, text="▶ CHECK IN",
#                                 font=("Courier", 12, "bold"), width=13,
#                                 relief=tk.FLAT, bg=GREEN_DIM, fg=MUTED,
#                                 activebackground=GREEN, activeforeground=BG,
#                                 cursor="hand2", state=tk.DISABLED,
#                                 command=lambda: self._trigger("checkin"))
#         self.btn_in.pack(side=tk.LEFT, ipady=12, padx=(0, 6))

#         self.btn_forgot = tk.Button(br, text="🔍 FORGOT ID",
#                                     font=("Courier", 9, "bold"), relief=tk.FLAT,
#                                     bg=TEAL_DIM, fg=TEAL,
#                                     activebackground=TEAL, activeforeground=BG,
#                                     cursor="hand2", padx=10,
#                                     command=self._open_forgotten_id)
#         self.btn_forgot.pack(side=tk.LEFT, ipady=12, padx=(0, 6))
#         _btn_hover(self.btn_forgot, TEAL, BG, TEAL_DIM, TEAL)

#         self.btn_out = tk.Button(br, text="■ CHECK OUT",
#                                  font=("Courier", 12, "bold"), width=13,
#                                  relief=tk.FLAT, bg=RED_DIM, fg=MUTED,
#                                  activebackground=RED, activeforeground=WHITE,
#                                  cursor="hand2", state=tk.DISABLED,
#                                  command=lambda: self._trigger("checkout"))
#         self.btn_out.pack(side=tk.LEFT, ipady=12, padx=(0, 6))

#         btn_exp = tk.Button(br, text="⬇ CSV", font=("Courier", 9, "bold"), relief=tk.FLAT,
#                             bg=BORDER, fg=TEXT2, cursor="hand2", padx=10,
#                             command=self._quick_export)
#         btn_exp.pack(side=tk.RIGHT, ipady=12)
#         _btn_hover(btn_exp, GREEN_DIM, GREEN2, BORDER, TEXT2)

#         _make_sep(parent, BORDER); tk.Frame(parent, bg=BG, height=8).pack()
#         lh = tk.Frame(parent, bg=BG); lh.pack(fill=tk.X, pady=(0, 6))
#         tk.Label(lh, text="ACTIVITY LOG",
#                  font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(side=tk.LEFT)
#         self._log_count_lbl = tk.Label(lh, text="", font=("Courier", 7), bg=BG, fg=MUTED)
#         self._log_count_lbl.pack(side=tk.LEFT, padx=(8, 0))
#         btn_clrlog = tk.Button(lh, text="CLEAR", font=("Courier", 7, "bold"),
#                                relief=tk.FLAT, bg=BORDER, fg=MUTED,
#                                padx=8, pady=2, cursor="hand2",
#                                command=self._clear_log)
#         btn_clrlog.pack(side=tk.RIGHT)
#         _btn_hover(btn_clrlog, BORDER2, TEXT2, BORDER, MUTED)

#         lw = tk.Frame(parent, bg=CARD, highlightbackground=BORDER2, highlightthickness=1)
#         lw.pack(fill=tk.BOTH, expand=True)
#         sb = tk.Scrollbar(lw, bg=BORDER, troughcolor=CARD); sb.pack(side=tk.RIGHT, fill=tk.Y)
#         self.log_box = tk.Text(lw, font=("Courier", 9), bg=CARD, fg=TEXT2, relief=tk.FLAT,
#                                padx=14, pady=10, yscrollcommand=sb.set,
#                                state=tk.DISABLED, cursor="arrow")
#         self.log_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         sb.config(command=self.log_box.yview)
#         for tag, col in [("ok", GREEN2), ("err", RED2), ("warn", ORANGE2),
#                          ("info", ACCENT2), ("ts", MUTED), ("div", BORDER2),
#                          ("late", ORANGE), ("ot", PURPLE), ("early", CYAN2)]:
#             self.log_box.tag_config(tag, foreground=col)

#     def _build_right(self, parent):
#         tk.Label(parent, text="BIOMETRIC SCANNER",
#                  font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 8))
#         sc       = tk.Frame(parent, bg=CARD2, highlightbackground=BORDER2, highlightthickness=1)
#         sc.pack(fill=tk.X, pady=(0, 14))
#         sc_inner = tk.Frame(sc, bg=CARD2, pady=16); sc_inner.pack()
#         self._fp       = FingerprintCanvas(sc_inner); self._fp.pack(pady=(0, 8))
#         self._scan_lbl = tk.Label(sc_inner, text="READY",
#                                   font=("Courier", 9, "bold"), bg=CARD2, fg=MUTED)
#         self._scan_lbl.pack()
#         self._scan_sub = tk.Label(sc_inner, text="Place finger when prompted",
#                                   font=("Courier", 7), bg=CARD2, fg=MUTED, wraplength=200)
#         self._scan_sub.pack(pady=(2, 0))

#         tk.Label(parent, text="LIVE DASHBOARD",
#                  font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 8))
#         dash = tk.Frame(parent, bg=BG); dash.pack(fill=tk.X)
#         row1 = tk.Frame(dash, bg=BG); row1.pack(fill=tk.X, pady=(0, 8))
#         self._tile_cin  = self._make_tile(row1, "CHECKED IN TODAY", "0", ACCENT2, "#0d1f3f")
#         self._tile_cout = self._make_tile(row1, "CHECKED OUT",      "0", GREEN2,  "#0a3321")
#         row2 = tk.Frame(dash, bg=BG); row2.pack(fill=tk.X, pady=(0, 8))
#         self._tile_early = self._make_tile(
#             row2, f"EARLY OUT (<{EARLY_CHECKOUT_H:02d}:00)", "0", CYAN2, CYAN_DIM, full=True)
#         row3 = tk.Frame(dash, bg=BG); row3.pack(fill=tk.X, pady=(0, 8))
#         self._tile_late = self._make_tile(row3, "LATE ARRIVALS", "0", ORANGE2, "#3d1f00")
#         self._tile_ot   = self._make_tile(row3, "OVERTIME",       "0", PURPLE,  "#1e0a40")

#         dr_frame = tk.Frame(parent, bg=CARD2, highlightbackground=BORDER, highlightthickness=1)
#         dr_frame.pack(fill=tk.X, pady=(0, 10))
#         dr_inner = tk.Frame(dr_frame, bg=CARD2, pady=10, padx=16); dr_inner.pack(fill=tk.X)
#         tk.Label(dr_inner, text="COMPLETION RATE",
#                  font=("Courier", 7, "bold"), bg=CARD2, fg=MUTED).pack(anchor="w", pady=(0, 6))
#         dr_row = tk.Frame(dr_inner, bg=CARD2); dr_row.pack(fill=tk.X)
#         self._donut = DonutRing(dr_row); self._donut.pack(side=tk.LEFT, padx=(0, 14))
#         dr_leg = tk.Frame(dr_row, bg=CARD2); dr_leg.pack(side=tk.LEFT, fill=tk.Y)
#         self._legend_lbl = tk.Label(dr_leg, text="0 of 0 workers\nhave checked out",
#                                     font=("Courier", 8), bg=CARD2, fg=TEXT2, justify=tk.LEFT)
#         self._legend_lbl.pack(anchor="w")
#         self._early_lbl  = tk.Label(dr_leg, text="",
#                                     font=("Courier", 8), bg=CARD2, fg=CYAN2, justify=tk.LEFT)
#         self._early_lbl.pack(anchor="w", pady=(6, 0))

#         tk.Label(parent, text="RECENT EVENTS",
#                  font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(8, 6))
#         ev_fr = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
#         ev_fr.pack(fill=tk.BOTH, expand=True)
#         self._event_box = tk.Text(ev_fr, font=("Courier", 8), bg=CARD, fg=TEXT2,
#                                   relief=tk.FLAT, padx=10, pady=8,
#                                   state=tk.DISABLED, cursor="arrow", height=7)
#         self._event_box.pack(fill=tk.BOTH, expand=True)
#         for tag, col in [("in", GREEN2), ("out", ACCENT2),
#                          ("warn", ORANGE2), ("ts", MUTED), ("early", CYAN2)]:
#             self._event_box.tag_config(tag, foreground=col)

#     def _make_tile(self, parent, label, value, fg, bg2, full=False):
#         tile = tk.Frame(parent, bg=CARD2, padx=14, pady=10,
#                         highlightbackground=bg2, highlightthickness=1)
#         kw = {"fill": tk.X, "expand": True}
#         if not full: kw["padx"] = (0, 6)
#         tile.pack(side=tk.LEFT, **kw)
#         val_lbl = tk.Label(tile, text=value, font=("Courier", 26, "bold"), bg=CARD2, fg=fg)
#         val_lbl.pack()
#         tk.Label(tile, text=label, font=("Courier", 6, "bold"), bg=CARD2, fg=TEXT2).pack()
#         return val_lbl

#     def _build_footer(self):
#         _make_sep(self.root, BORDER2)
#         foot = tk.Frame(self.root, bg=CARD, padx=28, pady=7)
#         foot.pack(fill=tk.X, side=tk.BOTTOM)
#         self._foot_lbl = tk.Label(foot, text="", font=("Courier", 8), bg=CARD, fg=MUTED)
#         self._foot_lbl.pack(side=tk.LEFT)
#         tk.Label(foot, text=(f"Shift {SHIFT_START_H:02d}:{SHIFT_START_M:02d}–"
#                              f"{(SHIFT_START_H+SHIFT_HOURS)%24:02d}:{SHIFT_START_M:02d} "
#                              f"· {SHIFT_HOURS}h std · {GRACE_MINUTES}min grace "
#                              f"· early<{EARLY_CHECKOUT_H:02d}:00 "
#                              f"· auto@{AUTO_CHECKOUT_H:02d}:00"),
#                  font=("Courier", 8), bg=CARD, fg=MUTED).pack(side=tk.RIGHT)

#     def _build_flash(self):
#         self.flash = tk.Frame(self.root, bg=ACCENT)
#         self.fi = tk.Label(self.flash, font=("Courier", 60, "bold"), bg=ACCENT, fg=WHITE)
#         self.fi.place(relx=0.5, rely=0.22, anchor="center")
#         self.fm = tk.Label(self.flash, font=("Courier", 22, "bold"),
#                            bg=ACCENT, fg=WHITE, wraplength=740)
#         self.fm.place(relx=0.5, rely=0.40, anchor="center")
#         self.fs = tk.Label(self.flash, font=("Courier", 22, "bold"),
#                            bg=ACCENT, fg=WHITE, wraplength=740, justify=tk.CENTER)
#         self.fs.place(relx=0.5, rely=0.56, anchor="center")
#         self.fx = tk.Label(self.flash, font=("Courier", 11, "bold"),
#                            bg=ACCENT, fg=GOLD2, wraplength=740)
#         self.fx.place(relx=0.5, rely=0.72, anchor="center")

#     # ------ TICKERS ------
#     def _tick_clock(self):
#         n = datetime.now()
#         self.date_lbl.config(text=n.strftime("%A, %d %B %Y"))
#         self.clock_lbl.config(text=n.strftime("%H:%M:%S"))
#         self.root.after(1000, self._tick_clock)

#     def _tick_stats(self):
#         lock  = load_lock()
#         cin   = lock.get("checked_in",  {})
#         cout  = lock.get("checked_out", {})
#         total = len(cin) + len(cout)
#         early = count_early_checkouts(lock)
#         late  = sum(1 for v in {**cin, **cout}.values()
#                     if isinstance(v, dict) and v.get("is_late"))
#         ot    = sum(1 for v in cout.values()
#                     if isinstance(v, dict) and v.get("overtime_hours", 0) > 0)
#         self._tile_cin.config(text=str(total))
#         self._tile_cout.config(text=str(len(cout)))
#         self._tile_early.config(text=str(early))
#         self._tile_late.config(text=str(late))
#         self._tile_ot.config(text=str(ot))
#         fraction   = len(cout) / total if total > 0 else 0
#         donut_col  = GREEN2 if fraction >= 0.8 else ORANGE2 if fraction >= 0.4 else ACCENT2
#         self._donut.set_value(fraction, donut_col)
#         self._legend_lbl.config(text=f"{len(cout)} of {total} workers\nhave checked out")
#         self._early_lbl.config(
#             text=f"⚡ {early} left before {EARLY_CHECKOUT_H:02d}:00" if early else "")
#         self._foot_lbl.config(
#             text=f"In:{total}  Out:{len(cout)}  On-site:{len(cin)}  "
#                  f"Early:{early}  Late:{late}  OT:{ot}")
#         self.root.after(STATS_REFRESH_MS, self._tick_stats)

#     def _tick_autocheckout(self):
#         now = datetime.now()
#         if (now.hour > AUTO_CHECKOUT_H or
#                 (now.hour == AUTO_CHECKOUT_H and now.minute >= AUTO_CHECKOUT_M)):
#             lock    = load_lock()
#             pending = {k: v for k, v in lock.get("checked_in", {}).items()
#                        if isinstance(v, dict)}
#             if pending:
#                 self.log(f"AUTO-CHECKOUT triggered @ {now.strftime('%H:%M')} "
#                          f"— {len(pending)} worker(s)", "warn")
#                 threading.Thread(
#                     target=run_auto_checkout,
#                     kwargs={"gui_log_fn": self.log, "done_cb": self._auto_checkout_done},
#                     daemon=True).start()
#             return
#         self.root.after(30_000, self._tick_autocheckout)

#     def _auto_checkout_done(self, success_names, fail_names):
#         def _u():
#             self._tick_stats()
#             n     = len(success_names)
#             names = ", ".join(success_names[:5]) + ("..." if len(success_names) > 5 else "")
#             extra = f"Failed: {', '.join(fail_names)}" if fail_names else ""
#             self._show_flash(">>", f"Auto-Checkout @ {datetime.now().strftime('%H:%M')}",
#                              f"{n} worker(s) checked out\n{names}", extra, "#1e0a40")
#             for name in success_names:
#                 self._add_event("AUTO-OUT", name, "warn")
#         self._gui(_u)

#     # ------ PANEL OPENERS ------
#     def _open_admin(self):           AdminPanel(self.root)

#     def _open_forgotten_id(self):
#         def _on_select(zk_id: str):
#             self.user_entry.delete(0, tk.END)
#             self.user_entry.insert(0, zk_id)
#             self.user_entry.focus_set()
#             self._apply_status(get_worker_status(zk_id))
#             threading.Thread(target=self._validate, args=(zk_id,), daemon=True).start()
#             self.log(f"Forgotten ID resolved → ZK#{zk_id}", "info")
#         ForgottenIDDialog(self.root, on_select=_on_select)

#     def _quick_export(self):
#         def _do():
#             fname = export_daily_summary()
#             if fname:
#                 self._gui(lambda: self.log(f"Exported → {os.path.abspath(fname)}", "ok"))
#             else:
#                 self._gui(lambda: self.log("Nothing to export.", "warn"))
#         threading.Thread(target=_do, daemon=True).start()

#     # ------ LOGGING ------
#     def log(self, msg: str, tag: str = "info"):
#         def _do():
#             self.log_box.config(state=tk.NORMAL)
#             if self._log_lines >= LOG_MAX_LINES:
#                 self.log_box.delete("1.0", "50.0")
#                 self._log_lines = max(self._log_lines - 50, 0)
#             self.log_box.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] ", "ts")
#             self.log_box.insert(tk.END, f"{msg}\n", tag)
#             self.log_box.see(tk.END)
#             self.log_box.config(state=tk.DISABLED)
#             self._log_lines += 1
#             self._log_count_lbl.config(text=f"({self._log_lines})")
#         self._gui(_do)

#     def _clear_log(self):
#         self.log_box.config(state=tk.NORMAL)
#         self.log_box.delete("1.0", tk.END)
#         self.log_box.config(state=tk.DISABLED)
#         self._log_lines = 0
#         self._log_count_lbl.config(text="")

#     def _add_event(self, action: str, name: str, tag: str = "ts"):
#         def _do():
#             self._event_box.config(state=tk.NORMAL)
#             ts = datetime.now().strftime("%H:%M")
#             self._event_box.insert("1.0", f"{ts}  {action:<10}  {name}\n", tag)
#             lines = int(self._event_box.index("end-1c").split(".")[0])
#             if lines > 100:
#                 self._event_box.delete("80.0", tk.END)
#             self._event_box.config(state=tk.DISABLED)
#         self._gui(_do)

#     def _show_flash(self, icon, headline, sub, extra, color):
#         self.flash.config(bg=color)
#         for w, v in [(self.fi, icon), (self.fm, headline), (self.fs, sub), (self.fx, extra)]:
#             w.config(text=v, bg=color)
#         self.flash.place(x=0, y=0, relwidth=1, relheight=1)
#         self.flash.lift()
#         self.root.after(2400, self.flash.place_forget)

#     # ------ SCANNER STATES ------
#     def _scan_start(self):
#         self._fp.start()
#         self._scan_lbl.config(text="SCANNING…", fg=ORANGE2)
#         self._scan_sub.config(text="Place your finger on the reader now")

#     def _scan_ok(self):
#         self._fp.stop_ok()
#         self._scan_lbl.config(text="CAPTURED ✔", fg=GREEN2)
#         self._scan_sub.config(text="Processing…")

#     def _scan_err(self, msg="FAILED"):
#         self._fp.stop_err(msg)
#         self._scan_lbl.config(text=msg, fg=RED2)
#         self._scan_sub.config(text="Please try again")

#     def _scan_reset(self):
#         self._fp.reset()
#         self._scan_lbl.config(text="READY", fg=MUTED)
#         self._scan_sub.config(text="Place finger when prompted")

#     # ------ STATUS / BUTTONS ------
#     def _set_status(self, text, fg=ACCENT, bg=ACCENT_DIM, border=ACCENT):
#         self.sf.config(bg=bg, highlightbackground=border)
#         for w in self.sf.winfo_children():
#             for iw in [w] + list(w.winfo_children()):
#                 try: iw.config(bg=bg)
#                 except Exception: pass
#         self.sl.config(text=text, fg=fg, bg=bg)
#         try:
#             self._status_led.config(bg=bg)
#             self._status_led.set_color(fg)
#             self._led.set_color(fg)
#         except Exception: pass

#     def _set_buttons(self, in_s, out_s):
#         self.btn_in.config(state=in_s,
#                            bg=GREEN if in_s == tk.NORMAL else GREEN_DIM,
#                            fg=BG if in_s == tk.NORMAL else MUTED)
#         self.btn_out.config(state=out_s,
#                             bg=RED if out_s == tk.NORMAL else RED_DIM,
#                             fg=WHITE if out_s == tk.NORMAL else MUTED)

#     def _set_avatar(self, name=None, color=BORDER):
#         self._avatar_cv.itemconfig(self._avatar_circle, fill=color)
#         self._avatar_cv.itemconfig(self._avatar_text,
#                                    text=_initials(name) if name else "",
#                                    fill=WHITE if name else MUTED)

#     def _apply_status(self, status, name=None, ci_time=""):
#         if status == "done":
#             self._set_buttons(tk.DISABLED, tk.DISABLED)
#             self._set_status("Attendance complete — see you tomorrow", RED, RED_DIM, RED)
#             self._set_avatar(name, RED_DIM)
#         elif status == "checked_in":
#             self._set_buttons(tk.DISABLED, tk.NORMAL)
#             msg = (f"Already checked IN at {ci_time} — proceed to Check-Out"
#                    if ci_time else "Already checked IN — proceed to Check-Out")
#             self._set_status(msg, ORANGE, ORANGE_DIM, ORANGE)
#             self._set_avatar(name, ORANGE_DIM)
#         elif status == "none":
#             self._set_buttons(tk.NORMAL, tk.DISABLED)
#             self._set_status("Ready to CHECK IN", GREEN, GREEN_DIM, GREEN)
#             self._set_avatar(name, GREEN_DIM)
#         else:
#             self._set_buttons(tk.DISABLED, tk.DISABLED)
#             self._set_status("Awaiting Worker ID", ACCENT, ACCENT_DIM, ACCENT)
#             self._set_avatar(None, BORDER)

#     # ------ KEY / ENTER ------
#     def _on_key(self, _=None):
#         if self._debounce_job:
#             self.root.after_cancel(self._debounce_job)
#         uid = self.user_entry.get().strip()
#         if not uid:
#             self._soft_reset(); return
#         self._apply_status(get_worker_status(uid))
#         self._debounce_job = self.root.after(
#             650, lambda: threading.Thread(
#                 target=self._validate, args=(uid,), daemon=True).start())

#     def _validate(self, uid: str):
#         if self.user_entry.get().strip() != uid or self._busy:
#             return
#         worker = find_worker(uid)
#         def _upd():
#             if self.user_entry.get().strip() != uid:
#                 return
#             if not worker:
#                 self.name_lbl.config(text="Unknown ID", fg=RED2)
#                 self.hint_lbl.config(
#                     text=f"ID '{uid}' not found — check attendance.log for details", fg=RED)
#                 self._set_buttons(tk.DISABLED, tk.DISABLED)
#                 self._set_status(f"Worker ID {uid} not found — see log", RED, RED_DIM, RED)
#                 self._set_avatar(None, RED_DIM)
#                 self.log(f"Worker ID {uid} lookup failed — check attendance.log", "err")
#             else:
#                 name   = worker.get("Full_Name", "N/A")
#                 status = get_worker_status(uid)
#                 self.name_lbl.config(text=name, fg=WHITE)
#                 ci_time_hint = ""
#                 if status in ("checked_in", "done"):
#                     lk  = load_lock()
#                     rec = (lk.get("checked_in", {}).get(str(uid)) or
#                            lk.get("checked_out", {}).get(str(uid)))
#                     if isinstance(rec, dict):
#                         raw = rec.get("time", "") or rec.get("checkin_time", "")
#                         try:
#                             ci_time_hint = datetime.strptime(
#                                 raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M")
#                         except Exception:
#                             ci_time_hint = raw[-5:] if len(raw) >= 5 else raw
#                 hints = {
#                     "checked_in": (
#                         f"Checked in at {ci_time_hint} — use Check-Out"
#                         if ci_time_hint else "Checked in today — use Check-Out", ORANGE),
#                     "done": (
#                         f"Attendance complete — checked in at {ci_time_hint}"
#                         if ci_time_hint else "Attendance complete for today", RED),
#                     "none": ("Not yet checked in today", TEXT2),
#                 }
#                 htxt, hcol = hints.get(status, ("", TEXT2))
#                 self.hint_lbl.config(text=htxt, fg=hcol)
#                 self._apply_status(status, name, ci_time=ci_time_hint)
#         self.root.after(0, _upd)

#     def _on_enter(self, _=None):
#         uid = self.user_entry.get().strip()
#         if not uid or self._busy: return
#         s = get_worker_status(uid)
#         if s == "none":       self._trigger("checkin")
#         elif s == "checked_in": self._trigger("checkout")

#     # ------ PROCESS ------
#     def _trigger(self, action: str):
#         if self._busy: return
#         uid = self.user_entry.get().strip()
#         if not uid: return
#         self._busy = True
#         self._set_buttons(tk.DISABLED, tk.DISABLED)
#         verb = "CHECK IN" if action == "checkin" else "CHECK OUT"
#         self._set_status(f"Scanning fingerprint for {verb}…", ORANGE, ORANGE_DIM, ORANGE)
#         self.root.after(0, self._scan_start)
#         threading.Thread(target=self._process, args=(uid, action), daemon=True).start()

#     def _process(self, uid: str, action: str):
#         is_open = False; success = False; msg = ""; full_name = uid
#         try:
#             self.log(f"{'─'*16} {action.upper()} · ID {uid} {'─'*16}", "div")

#             if zk.GetDeviceCount() == 0:
#                 self.log("Scanner not connected", "err")
#                 self._gui(lambda: self._scan_err("NO DEVICE"))
#                 self._gui(lambda: self._show_flash(
#                     "⚠", "Scanner Not Connected",
#                     "Connect the fingerprint device and try again.", "", "#6d28d9"))
#                 return

#             zk.OpenDevice(0); is_open = True
#             self.log("Waiting for fingerprint…", "info")
#             capture = None
#             for _ in range(150):
#                 capture = zk.AcquireFingerprint()
#                 if capture: break
#                 time.sleep(0.2)

#             if not capture:
#                 self.log("Scan timed out", "err")
#                 self._gui(lambda: self._scan_err("TIMEOUT"))
#                 self._gui(lambda: self._show_flash(
#                     "⏱", "Scan Timeout", "No fingerprint detected.", "", "#92400e"))
#                 return

#             self._gui(self._scan_ok)
#             self.log("Fingerprint captured ✔", "ok")

#             _wcache_invalidate(uid)
#             worker = find_worker(uid, force_refresh=True)
#             if not worker:
#                 self.log(f"ID {uid} not found in Zoho — check attendance.log", "err")
#                 self._gui(lambda: self._scan_err("NOT FOUND"))
#                 self._gui(lambda: self._show_flash(
#                     "✗", "Worker Not Found",
#                     f"ID {uid} does not exist.\nCheck attendance.log for diagnostics.",
#                     "", RED_DIM))
#                 return

#             full_name = worker.get("Full_Name", uid)
#             self.log(f"Identity: {full_name}", "ok")

#             status = get_worker_status(uid)

#             if status == "done":
#                 self.log("Already complete", "warn")
#                 self._gui(lambda: self._show_flash(
#                     "🔒", "Already Complete", full_name, "Done for today.", "#1e0a40"))
#                 self.root.after(2600, lambda: self._apply_status("done", full_name))
#                 return

#             if status == "checked_in" and action == "checkin":
#                 _ci_rec = load_lock().get("checked_in", {}).get(str(uid), {})
#                 _ci_raw = _ci_rec.get("time", "") if isinstance(_ci_rec, dict) else ""
#                 try:
#                     _ci_t = datetime.strptime(_ci_raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M")
#                 except Exception:
#                     _ci_t = _ci_raw[-5:] if len(_ci_raw) >= 5 else _ci_raw
#                 _ci_msg = f"Checked in at {_ci_t}" if _ci_t else "Use Check-Out instead."
#                 self.log(f"Already checked IN at {_ci_t}", "warn")
#                 self._gui(lambda: self._show_flash(
#                     "↩", "Already Checked In", full_name, _ci_msg, "#3d1f00"))
#                 self.root.after(2600, lambda: self._apply_status(
#                     "checked_in", full_name, ci_time=_ci_t))
#                 return

#             if status == "none" and action == "checkout":
#                 self.log("Not checked IN yet", "warn")
#                 self._gui(lambda: self._show_flash(
#                     "⚠", "Not Checked In", full_name, "Check IN first.", "#1e0a40"))
#                 self.root.after(2600, lambda: self._apply_status("none", full_name))
#                 return

#             self.log(f"Posting {action.upper()} to Zoho…", "info")
#             pa  = worker.get("Projects_Assigned")
#             pid = pa.get("ID") if isinstance(pa, dict) else DEFAULT_PROJECT_ID
#             success, msg = log_attendance(
#                 worker["ID"], uid, pid, full_name, action, self.log)

#             tag = "ok" if success else "err"
#             for line in msg.splitlines():
#                 if line.strip():
#                     ltag = tag
#                     if "late"     in line.lower(): ltag = "late"
#                     if "overtime" in line.lower(): ltag = "ot"
#                     if "early"    in line.lower(): ltag = "early"
#                     self.log(line.strip(), ltag)

#             if success:
#                 verb      = "Checked IN" if action == "checkin" else "Checked OUT"
#                 sub       = datetime.now().strftime("Time: %H:%M:%S · %A, %d %B %Y")
#                 extra     = ""
#                 flash_col = "#1d4ed8"

#                 if action == "checkin" and is_late(datetime.now()):
#                     extra     = f"⚠ Late arrival — {late_by_str(datetime.now())}"
#                     flash_col = "#92400e"

#                 if action == "checkout":
#                     lock2  = load_lock()
#                     co     = lock2.get("checked_out", {}).get(str(uid), {})
#                     ot     = co.get("overtime_hours", 0) if isinstance(co, dict) else 0
#                     now_   = datetime.now()
#                     checkin_raw = co.get("checkin_time", "") if isinstance(co, dict) else ""
#                     try:
#                         ci_dt  = datetime.strptime(checkin_raw, "%d-%b-%Y %H:%M:%S")
#                         ci_disp = ci_dt.strftime("%H:%M:%S")
#                     except Exception:
#                         ci_disp = (checkin_raw[-8:] if len(checkin_raw) >= 8
#                                    else checkin_raw or "—")
#                     co_disp = now_.strftime("%H:%M:%S")
#                     sub  = (f"IN {ci_disp} → OUT {co_disp}"
#                             f"\n{now_.strftime('%A, %d %B %Y')}")
#                     if ot > 0:
#                         extra = f"⏱ Overtime: {int(ot)}h {int((ot%1)*60)}m"

#                 ev_tag = "in" if action == "checkin" else "out"
#                 _v, _s, _e, _fc = verb, sub, extra, flash_col
#                 self._gui(lambda: self._add_event(_v, full_name, ev_tag))
#                 self._gui(self._tick_stats)
#                 self._gui(lambda: self._show_flash(
#                     "✔", f"{_v} — {full_name}", _s, _e, _fc))
#             else:
#                 _m = msg.splitlines()[0][:80] if msg else "Unknown error"
#                 self._gui(lambda: self._scan_err("ERROR"))
#                 self._gui(lambda: self._show_flash("✗", "Action Failed", _m, "", RED_DIM))

#         except Exception as exc:
#             _log.exception(f"_process error: {exc}")
#             self.log(f"Unexpected error: {exc}", "err")
#         finally:
#             if is_open:
#                 try: zk.CloseDevice()
#                 except Exception: pass
#             self._busy = False
#             self.root.after(2600, self._scan_reset)
#             self.root.after(2600, lambda: self._reset_ui(clear_log=success))

#     def _reset_ui(self, clear_log=False):
#         self.user_entry.delete(0, tk.END)
#         self.name_lbl.config(text="—", fg=MUTED)
#         self.hint_lbl.config(text="Enter a Worker ID above", fg=MUTED)
#         self._set_avatar(None, BORDER)
#         self._set_buttons(tk.DISABLED, tk.DISABLED)
#         self._set_status("Awaiting Worker ID", ACCENT, ACCENT_DIM, ACCENT)
#         if clear_log:
#             self._clear_log()
#         self.log("Ready for next worker.", "div")
#         self.user_entry.focus_set()

#     def _soft_reset(self):
#         self.name_lbl.config(text="—", fg=MUTED)
#         self.hint_lbl.config(text="Enter a Worker ID above", fg=MUTED)
#         self._set_avatar(None, BORDER)
#         self._set_buttons(tk.DISABLED, tk.DISABLED)
#         self._set_status("Awaiting Worker ID", ACCENT, ACCENT_DIM, ACCENT)

#     def _on_close(self):
#         try: zk.Terminate()
#         except Exception: pass
#         self.root.destroy()

# # ===========================================================
# if __name__ == "__main__":
#     root = tk.Tk()
#     FingerprintGUI(root)
#     root.mainloop()

























# import os, time, json, csv, requests, threading, math, queue, logging
# from datetime import datetime, timedelta
# from dotenv import load_dotenv
# from pyzkfp import ZKFP2
# import tkinter as tk
# from tkinter import ttk, messagebox
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry

# # ===========================================================
# # LOGGING
# # ===========================================================
# logging.basicConfig(
#     filename="attendance.log",
#     level=logging.INFO,
#     format="%(asctime)s [%(levelname)s] %(message)s",
#     datefmt="%Y-%m-%d %H:%M:%S")
# _log = logging.getLogger(__name__)

# # ===========================================================
# # CONFIGURATION
# # ===========================================================
# load_dotenv()

# ZOHO_DOMAIN    = os.getenv("ZOHO_DOMAIN",    "zoho.com")
# APP_OWNER      = os.getenv("APP_OWNER",      "wavemarkpropertieslimited")
# APP_NAME       = os.getenv("APP_NAME",       "real-estate-wages-system")
# CLIENT_ID      = os.getenv("ZOHO_CLIENT_ID")
# CLIENT_SECRET  = os.getenv("ZOHO_CLIENT_SECRET")
# REFRESH_TOKEN  = os.getenv("ZOHO_REFRESH_TOKEN")

# WORKERS_REPORT    = "All_Workers"
# ATTENDANCE_FORM   = "Daily_Attendance"
# ATTENDANCE_REPORT = "Daily_Attendance_Report"
# DEFAULT_PROJECT_ID = "4838902000000391493"

# TOKEN_CACHE  = {"token": None, "expires_at": 0}
# _TOKEN_LOCK  = threading.Lock()

# # Derive the TLD from ZOHO_DOMAIN so EU/IN accounts work too
# _ZOHO_TLD   = ZOHO_DOMAIN.split(".")[-1]          # "com", "eu", "in" …
# ACCOUNTS_URL = f"https://accounts.zoho.{_ZOHO_TLD}"
# API_DOMAIN   = f"https://creator.zoho.{_ZOHO_TLD}/api/v2"

# CHECKIN_LOCK_FILE = "checkin_today.json"

# # ── Shift policy ─────────────────────────────────────────
# SHIFT_START_H   = 7
# SHIFT_START_M   = 00
# SHIFT_HOURS     = 8
# GRACE_MINUTES   = 60
# EARLY_CHECKOUT_H = 17
# EARLY_CHECKOUT_M = 0
# AUTO_CHECKOUT_H  = 19
# AUTO_CHECKOUT_M  = 0

# # ── Performance constants ────────────────────────────────
# WORKER_CACHE_TTL = 3600
# MAX_POOL_SIZE    = 20
# ZOHO_TIMEOUT     = 30
# STATS_REFRESH_MS = 8000
# LOG_MAX_LINES    = 500
# LOCK_WRITE_LOCK  = threading.Lock()

# # ===========================================================
# # GLOBAL SDK
# # ===========================================================
# zk = ZKFP2()
# try:
#     zk.Init()
# except Exception as e:
#     _log.error(f"Fingerprint SDK Init Error: {e}")
#     print(f"Fingerprint SDK Init Error: {e}")

# # ===========================================================
# # HTTP SESSION — connection pooling + automatic retry
# # ===========================================================
# def _make_session():
#     s = requests.Session()
#     retry = Retry(
#         total=3, backoff_factor=1,
#         status_forcelist=[429, 500, 502, 503, 504],
#         allowed_methods=["GET", "POST", "PATCH"])
#     adapter = HTTPAdapter(
#         max_retries=retry,
#         pool_connections=MAX_POOL_SIZE,
#         pool_maxsize=MAX_POOL_SIZE,
#         pool_block=False)
#     s.mount("https://", adapter)
#     s.mount("http://",  adapter)
#     return s

# _SESSION = _make_session()

# def zoho_request(method, url, retries=3, **kwargs):
#     kwargs.setdefault("timeout", ZOHO_TIMEOUT)
#     for attempt in range(1, retries + 1):
#         try:
#             return _SESSION.request(method, url, **kwargs)
#         except (requests.exceptions.Timeout,
#                 requests.exceptions.ConnectionError, OSError) as exc:
#             _log.warning(f"zoho_request attempt {attempt}: {exc}")
#             if attempt < retries:
#                 time.sleep(min(2 ** attempt, 8))
#     return None


# # ===========================================================
# # AUTHENTICATION — thread-safe token refresh
# # ===========================================================
# def _validate_env():
#     """Check that required .env variables are present before attempting auth."""
#     missing = [k for k, v in {
#         "ZOHO_CLIENT_ID":     CLIENT_ID,
#         "ZOHO_CLIENT_SECRET": CLIENT_SECRET,
#         "ZOHO_REFRESH_TOKEN": REFRESH_TOKEN,
#     }.items() if not v]
#     if missing:
#         _log.error(f"Missing .env variables: {', '.join(missing)}")
#         return False
#     return True

# def get_access_token():
#     if not _validate_env():
#         return None

#     now = time.time()
#     with _TOKEN_LOCK:
#         if TOKEN_CACHE["token"] and now < TOKEN_CACHE["expires_at"] - 120:
#             return TOKEN_CACHE["token"]
#         TOKEN_CACHE["token"] = None

#     url = f"{ACCOUNTS_URL}/oauth/v2/token"
#     data = {
#         "refresh_token": REFRESH_TOKEN,
#         "client_id":     CLIENT_ID,
#         "client_secret": CLIENT_SECRET,
#         "grant_type":    "refresh_token",
#     }

#     for attempt in range(3):
#         r = zoho_request("POST", url, data=data, retries=1)
#         if r is None:
#             _log.error(f"Token refresh attempt {attempt+1}: no response / timeout")
#             time.sleep(3)
#             continue

#         if r.status_code == 200:
#             res = r.json()
#             if "access_token" in res:
#                 with _TOKEN_LOCK:
#                     TOKEN_CACHE["token"]      = res["access_token"]
#                     TOKEN_CACHE["expires_at"] = now + int(res.get("expires_in", 3600))
#                 _log.info("Zoho token refreshed OK")
#                 return TOKEN_CACHE["token"]
#             else:
#                 err = res.get("error", "unknown")
#                 _log.error(f"Token refresh attempt {attempt+1} HTTP 200 but error={err!r}. "
#                            f"Full response: {res}")
#                 if err == "invalid_client":
#                     _log.error(
#                         ">>> invalid_client: Your CLIENT_ID or CLIENT_SECRET is wrong, "
#                         "or the OAuth client was deleted/deauthorised in Zoho API Console "
#                         "(https://api-console.zoho.com). Re-generate credentials and update .env.")
#                     return None          # no point retrying
#                 if err in ("invalid_code", "access_denied"):
#                     _log.error(
#                         ">>> Refresh token revoked or expired. Re-authorise the app and "
#                         "generate a new ZOHO_REFRESH_TOKEN.")
#                     return None
#         else:
#             _log.error(f"Token refresh attempt {attempt+1} HTTP {r.status_code}: {r.text[:300]}")

#         time.sleep(3)

#     _log.error("Failed to refresh Zoho token after 3 attempts — "
#                "check REFRESH_TOKEN / CLIENT_ID / CLIENT_SECRET in .env")
#     return None

# def auth_headers():
#     token = get_access_token()
#     if not token:
#         _log.error("auth_headers: no token available — all Zoho calls will fail")
#         return {}
#     return {"Authorization": f"Zoho-oauthtoken {token}"}

# # ===========================================================
# # LOCAL STATE — in-memory cache + safe file persistence
# # ===========================================================
# _LOCK_MEM: dict = {}
# _LOCK_MEM_DATE: str = ""

# def load_lock() -> dict:
#     global _LOCK_MEM, _LOCK_MEM_DATE
#     today = datetime.now().strftime("%Y-%m-%d")
#     if _LOCK_MEM_DATE == today and _LOCK_MEM:
#         return _LOCK_MEM

#     if os.path.exists(CHECKIN_LOCK_FILE):
#         try:
#             with open(CHECKIN_LOCK_FILE, "r", encoding="utf-8") as f:
#                 data = json.load(f)
#             if data.get("date") == today:
#                 for key in ("checked_in", "checked_out"):
#                     if not isinstance(data.get(key), dict):
#                         data[key] = {}
#                     data[key] = {k: v for k, v in data[key].items()
#                                  if isinstance(v, dict)}
#                 _LOCK_MEM      = data
#                 _LOCK_MEM_DATE = today
#                 return _LOCK_MEM
#         except Exception as exc:
#             _log.warning(f"load_lock read error: {exc}")

#     fresh = {"date": today, "checked_in": {}, "checked_out": {}}
#     _LOCK_MEM      = fresh
#     _LOCK_MEM_DATE = today
#     save_lock(fresh)
#     return _LOCK_MEM

# def save_lock(data: dict):
#     global _LOCK_MEM, _LOCK_MEM_DATE
#     _LOCK_MEM      = data
#     _LOCK_MEM_DATE = data.get("date", "")
#     tmp = CHECKIN_LOCK_FILE + ".tmp"
#     with LOCK_WRITE_LOCK:
#         try:
#             with open(tmp, "w", encoding="utf-8") as f:
#                 json.dump(data, f, indent=2)
#             os.replace(tmp, CHECKIN_LOCK_FILE)
#         except Exception as exc:
#             _log.error(f"save_lock error: {exc}")

# def get_worker_status(zk_id: str) -> str:
#     lock = load_lock()
#     key  = str(zk_id)
#     if key in lock["checked_out"]:  return "done"
#     if key in lock["checked_in"]:   return "checked_in"
#     return "none"

# def count_early_checkouts(lock=None) -> int:
#     if lock is None:
#         lock = load_lock()
#     now         = datetime.now()
#     early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                               second=0, microsecond=0)
#     count = 0
#     for info in lock.get("checked_out", {}).values():
#         if not isinstance(info, dict):
#             continue
#         try:
#             co_dt = datetime.strptime(info.get("time", ""), "%H:%M:%S").replace(
#                 year=now.year, month=now.month, day=now.day)
#             if co_dt < early_limit:
#                 count += 1
#         except Exception:
#             pass
#     return count

# # ===========================================================
# # WORKER CACHE — TTL-based, evicts oldest when full
# # ===========================================================
# _WORKER_STORE: dict = {}
# _WORKER_LOCK  = threading.Lock()

# def _wcache_get(uid: str):
#     with _WORKER_LOCK:
#         e = _WORKER_STORE.get(str(uid))
#         if e and (time.time() - e["ts"]) < WORKER_CACHE_TTL:
#             return e["worker"]
#     return None

# def _wcache_set(uid: str, worker: dict):
#     with _WORKER_LOCK:
#         if len(_WORKER_STORE) >= 2000:
#             oldest = sorted(_WORKER_STORE, key=lambda k: _WORKER_STORE[k]["ts"])
#             for old_k in oldest[:200]:
#                 del _WORKER_STORE[old_k]
#         _WORKER_STORE[str(uid)] = {"worker": worker, "ts": time.time()}

# def _wcache_invalidate(uid: str):
#     with _WORKER_LOCK:
#         _WORKER_STORE.pop(str(uid), None)

# # ===========================================================
# # SHIFT HELPERS
# # ===========================================================
# def is_late(checkin_dt: datetime) -> bool:
#     cutoff = checkin_dt.replace(
#         hour=SHIFT_START_H, minute=SHIFT_START_M, second=0, microsecond=0
#     ) + timedelta(minutes=GRACE_MINUTES)
#     return checkin_dt > cutoff

# def late_by_str(checkin_dt: datetime) -> str:
#     shift_start = checkin_dt.replace(
#         hour=SHIFT_START_H, minute=SHIFT_START_M, second=0, microsecond=0)
#     delta = max((checkin_dt - shift_start).total_seconds(), 0)
#     mins  = int(delta // 60)
#     return f"{mins} min late" if mins else "on time"

# def overtime_hours(total_hours: float) -> float:
#     return max(round(total_hours - SHIFT_HOURS, 4), 0)

# # ===========================================================
# # ZOHO API
# # ===========================================================
# def find_worker(zk_user_id, force_refresh: bool = False):
#     """
#     Look up a worker in Zoho by their ZKTeco User ID.
#     Tries multiple criteria formats before falling back to a full-list scan.
#     """
#     uid = str(zk_user_id).strip()

#     if not force_refresh:
#         cached = _wcache_get(uid)
#         if cached:
#             _log.debug(f"find_worker({uid}): cache hit")
#             return cached

#     hdrs = auth_headers()
#     if not hdrs:
#         _log.error(f"find_worker({uid}): aborting — no valid Zoho token. "
#                    "Check REFRESH_TOKEN / CLIENT_ID / CLIENT_SECRET in .env")
#         return None

#     url = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/report/{WORKERS_REPORT}"

#     try:
#         int_id = int(uid)
#     except ValueError:
#         int_id = None

#     criteria_attempts = []
#     if int_id is not None:
#         criteria_attempts += [
#             f"(ZKTeco_User_ID2 == {int_id})",
#             f'(ZKTeco_User_ID2 == "{int_id}")',
#             f"(Worker_ID == {int_id})",
#             f'(Worker_ID == "{int_id}")',
#         ]
#     criteria_attempts += [
#         f'(ZKTeco_User_ID2 == "{uid}")',
#         f'(Worker_ID == "{uid}")',
#     ]

#     for criteria in criteria_attempts:
#         _log.info(f"find_worker({uid}): trying criteria={criteria!r}")
#         r = zoho_request("GET", url, headers=hdrs, params={"criteria": criteria})
#         if not r:
#             _log.error(f"find_worker({uid}): request timed out on criteria={criteria!r}")
#             continue
#         if r.status_code == 401:
#             _log.warning(f"find_worker: HTTP 401 for criteria: {criteria}")
#             with _TOKEN_LOCK:
#                 TOKEN_CACHE["token"]      = None
#                 TOKEN_CACHE["expires_at"] = 0
#             hdrs = auth_headers()         # try refreshing once
#             if not hdrs:
#                 _log.error(f"find_worker({uid}): token refresh failed, aborting")
#                 return None
#             r = zoho_request("GET", url, headers=hdrs, params={"criteria": criteria})
#             if not r or r.status_code != 200:
#                 _log.warning(f"find_worker: criteria failed for ID '{uid}', trying full fetch…")
#                 continue
#         if r.status_code != 200:
#             _log.error(f"find_worker({uid}): HTTP {r.status_code} — {r.text[:300]}")
#             continue

#         data = r.json().get("data", [])
#         if data:
#             _log.info(f"find_worker({uid}): found via criteria={criteria!r}")
#             _wcache_set(uid, data[0])
#             return data[0]

#     # ── Last resort: fetch ALL workers and match manually ──
#     _log.warning(f"find_worker({uid}): all criteria failed — attempting full worker scan")
#     r = zoho_request("GET", url, headers=hdrs)
#     if r and r.status_code == 200:
#         all_workers = r.json().get("data", [])
#         _log.info(f"find_worker({uid}): full scan returned {len(all_workers)} worker(s)")
#         for w in all_workers:
#             zk_val  = str(w.get("ZKTeco_User_ID2", "")).strip()
#             wid_val = str(w.get("Worker_ID",       "")).strip()
#             zk_val_clean  = zk_val.split(".")[0]
#             wid_val_clean = wid_val.split(".")[0]
#             if uid in (zk_val, wid_val, zk_val_clean, wid_val_clean):
#                 _log.info(f"find_worker({uid}): matched via full scan "
#                           f"(ZKTeco_User_ID2={zk_val!r}, Worker_ID={wid_val!r})")
#                 _wcache_set(uid, w)
#                 return w
#     else:
#         _log.error(f"find_worker({uid}): full scan HTTP "
#                    f"{r.status_code if r else 'timeout'}")

#     _log.error(f"find_worker({uid}): worker NOT found after all attempts. "
#                f"Verify ZKTeco_User_ID2 / Worker_ID field in Zoho for ID={uid}")
#     return None


# def search_workers_by_name(name_query: str) -> list:
#     """Search Zoho for workers whose Full_Name contains the query string."""
#     url  = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/report/{WORKERS_REPORT}"
#     hdrs = auth_headers()
#     if not hdrs:
#         _log.error("search_workers_by_name: no valid token — cannot search")
#         return []

#     q_lower = name_query.strip().lower()
#     results = []

#     # Try Zoho criteria-based search first
#     for criteria in [
#         f'(Full_Name contains "{name_query}")',
#         f'(Full_Name starts_with "{name_query}")',
#     ]:
#         try:
#             r = zoho_request("GET", url, headers=hdrs, params={"criteria": criteria})
#             if r and r.status_code == 200:
#                 data = r.json().get("data", [])
#                 if data:
#                     _log.info(f"search_workers_by_name: found {len(data)} via criteria={criteria!r}")
#                     return data
#         except Exception as exc:
#             _log.warning(f"search_workers_by_name criteria error: {exc}")

#     # Fallback: fetch ALL workers and filter locally
#     try:
#         _log.info("search_workers_by_name: falling back to full worker scan")
#         r = zoho_request("GET", url, headers=hdrs)
#         if r and r.status_code == 200:
#             all_workers = r.json().get("data", [])
#             _log.info(f"search_workers_by_name: full scan returned {len(all_workers)} workers")
#             results = [
#                 w for w in all_workers
#                 if q_lower in str(w.get("Full_Name", "")).lower()
#                 or q_lower in str(w.get("ZKTeco_User_ID2", "")).lower()
#                 or q_lower in str(w.get("Worker_ID", "")).lower()
#             ]
#         elif r:
#             _log.error(f"search_workers_by_name: full scan HTTP {r.status_code}: {r.text[:200]}")
#         else:
#             _log.error("search_workers_by_name: full scan timed out")
#     except Exception as exc:
#         _log.error(f"search_workers_by_name fallback error: {exc}")

#     return results


# def _extract_zoho_id(res_json):
#     data = res_json.get("data")
#     if isinstance(data, dict):
#         return data.get("ID") or data.get("id")
#     if isinstance(data, list) and data:
#         return data[0].get("ID") or data[0].get("id")
#     return res_json.get("ID") or res_json.get("id")


# def _find_record_in_zoho(worker_id, today_display, today_iso, hdrs, _log_fn=None):
#     def dbg(msg):
#         _log.debug(f"[ZOHO SEARCH] {msg}")
#         if _log_fn:
#             _log_fn(f"[search] {msg}", "warn")

#     report_url   = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/report/{ATTENDANCE_REPORT}"
#     criteria_list = [
#         f'(Worker_Name == "{worker_id}" && Date == "{today_display}")',
#         f'(Worker_Name == "{worker_id}" && Date == "{today_iso}")',
#         f'(Worker_ID_Lookup == "{worker_id}" && Date == "{today_display}")',
#         f'(Worker_ID_Lookup == "{worker_id}" && Date == "{today_iso}")',
#         f'(Worker_Name == "{worker_id}")',
#         f'(Worker_ID_Lookup == "{worker_id}")',
#     ]

#     for crit in criteria_list:
#         r = zoho_request("GET", report_url, headers=hdrs, params={"criteria": crit})
#         if not r or r.status_code != 200:
#             continue
#         recs = r.json().get("data", [])
#         if not recs:
#             continue
#         for rec in recs:
#             d = str(rec.get("Date", rec.get("Date_field", ""))).strip()
#             if d in (today_display, today_iso):
#                 return rec["ID"]
#         if len(recs) == 1:
#             return recs[0]["ID"]

#     for date_val in (today_display, today_iso):
#         r = zoho_request("GET", report_url, headers=hdrs,
#                          params={"criteria": f'(Date == "{date_val}")'})
#         if not r or r.status_code != 200:
#             continue
#         for rec in r.json().get("data", []):
#             for field in ("Worker_Name", "Worker_ID_Lookup", "Worker",
#                           "Worker_Name.ID", "Worker_ID"):
#                 val = rec.get(field)
#                 if isinstance(val, dict):
#                     val = val.get("ID") or val.get("id") or val.get("display_value", "")
#                 if str(val).strip() == str(worker_id).strip():
#                     return rec["ID"]

#     dbg("All strategies exhausted — not found.")
#     return None

# # ===========================================================
# # ATTENDANCE LOGIC
# # ===========================================================
# def log_attendance(worker_id, zk_id, project_id, full_name, action, _log_fn=None):
#     now     = datetime.now()
#     zk_key  = str(zk_id)
#     today_display = now.strftime("%d-%b-%Y")
#     today_iso     = now.strftime("%Y-%m-%d")

#     if action == "checkin":
#         form_url     = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/form/{ATTENDANCE_FORM}"
#         checkin_time = now.strftime("%d-%b-%Y %H:%M:%S")
#         hdrs         = auth_headers()
#         if not hdrs:
#             return False, "Could not refresh Zoho token."

#         worker_late = is_late(now)
#         late_note   = late_by_str(now)
#         late_mins   = int(max(
#             (now - now.replace(hour=SHIFT_START_H, minute=SHIFT_START_M,
#                                second=0, microsecond=0)).total_seconds() // 60, 0
#         )) if worker_late else 0

#         payload = {"data": {
#             "Worker_Name":      worker_id,
#             "Projects":         project_id,
#             "Date":             today_display,
#             "First_In":         checkin_time,
#             "Worker_Full_Name": full_name,
#             "Is_Late":          "true" if worker_late else "false",
#             "Late_By_Minutes":  late_mins,
#         }}

#         r = zoho_request("POST", form_url, headers=hdrs, json=payload)
#         if r and r.status_code in (200, 201):
#             res          = r.json()
#             zoho_rec_id  = _extract_zoho_id(res)
#             if not zoho_rec_id:
#                 zoho_rec_id = _find_record_in_zoho(
#                     worker_id, today_display, today_iso, auth_headers(), _log_fn)

#             lock = load_lock()
#             lock["checked_in"][zk_key] = {
#                 "time":      checkin_time,
#                 "zoho_id":   zoho_rec_id,
#                 "worker_id": worker_id,
#                 "name":      full_name,
#                 "is_late":   worker_late,
#                 "late_note": late_note,
#             }
#             save_lock(lock)
#             _log.info(f"CHECKIN OK: {full_name} late={worker_late}")
#             status_line = f"⚠ {late_note}" if worker_late else "✓ On time"
#             return True, (f"✅ {full_name} checked IN at {now.strftime('%H:%M')}\n"
#                           f"   {status_line}")

#         err = r.text[:200] if r else "Timeout"
#         _log.error(f"CHECKIN FAIL: {full_name}: {err}")
#         return False, f"Check-in failed: {err}"

#     elif action == "checkout":
#         lock = load_lock()
#         info = lock["checked_in"].get(zk_key)
#         if not info:
#             return False, "No check-in record found for today."

#         hdrs = auth_headers()
#         if not hdrs:
#             return False, "Could not refresh Zoho token."

#         att_record_id  = info.get("zoho_id")
#         stored_worker  = info.get("worker_id", worker_id)

#         def dbg(msg):
#             _log.debug(f"[CHECKOUT] {msg}")
#             if _log_fn:
#                 _log_fn(f"[checkout] {msg}", "warn")

#         if att_record_id:
#             direct_url = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
#                           f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
#             r_chk = zoho_request("GET", direct_url, headers=hdrs)
#             if not (r_chk and r_chk.status_code == 200):
#                 dbg("stored ID invalid — searching...")
#                 att_record_id = None

#         if not att_record_id:
#             att_record_id = _find_record_in_zoho(
#                 stored_worker, today_display, today_iso, hdrs, _log_fn)
#             if att_record_id:
#                 lock["checked_in"][zk_key]["zoho_id"] = att_record_id
#                 save_lock(lock)

#         if not att_record_id:
#             form_index_url = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/form/{ATTENDANCE_FORM}"
#             for date_val in (today_display, today_iso):
#                 crit = f'(Worker_Name == "{stored_worker}" && Date == "{date_val}")'
#                 r_f  = zoho_request("GET", form_index_url, headers=hdrs,
#                                     params={"criteria": crit})
#                 if r_f and r_f.status_code == 200:
#                     frecs = r_f.json().get("data", [])
#                     if frecs:
#                         att_record_id = frecs[0].get("ID")
#                         lock["checked_in"][zk_key]["zoho_id"] = att_record_id
#                         save_lock(lock)
#                         break

#         if not att_record_id:
#             return False, (f"Could not locate attendance record in Zoho.\n"
#                            f"Worker: {full_name}  Date: {today_display}\n"
#                            "Check the log for [checkout] diagnostics.")

#         try:
#             dt_in = datetime.strptime(info.get("time", ""), "%d-%b-%Y %H:%M:%S")
#         except Exception:
#             dt_in = now

#         total_hours = max((now - dt_in).total_seconds() / 3600, 0.01)
#         ot_hours    = overtime_hours(total_hours)
#         total_str   = f"{int(total_hours)}h {int((total_hours % 1) * 60)}m"
#         ot_str      = f"{int(ot_hours)}h {int((ot_hours % 1) * 60)}m" if ot_hours else "None"
#         total_hours_rounded = round(total_hours, 2)
#         ot_hours_rounded    = round(ot_hours, 2)

#         update_url = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
#                       f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
#         r_u = zoho_request("PATCH", update_url, headers=hdrs, json={"data": {
#             "Last_Out":       now.strftime("%d-%b-%Y %H:%M:%S"),
#             "Total_Hours":    total_hours_rounded,
#             "Overtime_Hours": ot_hours_rounded,
#         }})

#         http_code = r_u.status_code if r_u else "timeout"
#         body_raw  = r_u.text[:300]  if r_u else "No response"

#         if r_u and r_u.status_code == 200:
#             body = r_u.json()
#             code = body.get("code")
#             if code == 3000:
#                 checkout_hms = now.strftime("%H:%M:%S")
#                 lock["checked_in"].pop(zk_key, None)
#                 lock["checked_out"][zk_key] = {
#                     "time":           checkout_hms,
#                     "name":           full_name,
#                     "total_hours":    total_hours_rounded,
#                     "overtime_hours": ot_hours_rounded,
#                     "is_late":        info.get("is_late", False),
#                     "late_note":      info.get("late_note", ""),
#                     "checkin_time":   info.get("time", ""),
#                 }
#                 save_lock(lock)
#                 _log.info(f"CHECKOUT OK: {full_name} hours={total_hours_rounded}")
#                 ot_line     = f"   Overtime: {ot_str}" if ot_hours else ""
#                 early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                                           second=0, microsecond=0)
#                 early_note  = (f"\n   ⚠ Early checkout "
#                                f"(before {EARLY_CHECKOUT_H:02d}:{EARLY_CHECKOUT_M:02d})"
#                                if now < early_limit else "")
#                 return True, (f"🚪 {full_name} checked OUT at {now.strftime('%H:%M')}\n"
#                               f"   Total time: {total_str}\n{ot_line}{early_note}")

#             errors = body.get("error", body.get("message", ""))
#             return False, (f"Zoho rejected update (code {code}).\nError: {errors}\n"
#                            f"Worker: {full_name}  Hours: {total_hours_rounded}")

#         _log.error(f"CHECKOUT FAIL: {full_name} HTTP {http_code}: {body_raw}")
#         return False, f"Check-out PATCH failed (HTTP {http_code}): {body_raw}"

#     return False, "Unknown action."

# # ===========================================================
# # AUTO-CHECKOUT — concurrent batch processing
# # ===========================================================
# def run_auto_checkout(gui_log_fn=None, done_cb=None):
#     now           = datetime.now()
#     today_display = now.strftime("%d-%b-%Y")
#     today_iso     = now.strftime("%Y-%m-%d")
#     checkout_ts   = now.strftime("%d-%b-%Y %H:%M:%S")
#     checkout_hms  = now.strftime("%H:%M:%S")

#     lock    = load_lock()
#     pending = {k: v for k, v in lock.get("checked_in", {}).items()
#                if isinstance(v, dict)}

#     if not pending:
#         if done_cb:
#             done_cb([], [])
#         return

#     def info(msg):
#         _log.info(msg)
#         if gui_log_fn:
#             gui_log_fn(msg, "warn")

#     info(f"AUTO-CHECKOUT: {len(pending)} worker(s) at {now.strftime('%H:%M')}")

#     success_names, fail_names = [], []
#     result_lock = threading.Lock()
#     sem         = threading.Semaphore(8)

#     def _checkout_one(zk_key, winfo):
#         with sem:
#             full_name = winfo.get("name",      zk_key)
#             worker_id = winfo.get("worker_id", zk_key)
#             att_record_id = winfo.get("zoho_id")
#             hdrs = auth_headers()

#             if att_record_id:
#                 du = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
#                       f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
#                 rc = zoho_request("GET", du, headers=hdrs)
#                 if not (rc and rc.status_code == 200):
#                     att_record_id = None

#             if not att_record_id:
#                 att_record_id = _find_record_in_zoho(
#                     worker_id, today_display, today_iso, hdrs)

#             if not att_record_id:
#                 info(f"  SKIP {full_name}: no Zoho record")
#                 with result_lock:
#                     fail_names.append(full_name)
#                 return

#             try:
#                 dt_in = datetime.strptime(winfo.get("time", ""), "%d-%b-%Y %H:%M:%S")
#             except Exception:
#                 dt_in = now

#             total_h = max((now - dt_in).total_seconds() / 3600, 0.01)
#             ot_h    = overtime_hours(total_h)

#             uu = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
#                   f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
#             ru = zoho_request("PATCH", uu, headers=hdrs, json={"data": {
#                 "Last_Out":       checkout_ts,
#                 "Total_Hours":    round(total_h, 2),
#                 "Overtime_Hours": round(ot_h, 2),
#             }})

#             if ru and ru.status_code == 200 and ru.json().get("code") == 3000:
#                 lk = load_lock()
#                 lk["checked_in"].pop(zk_key, None)
#                 lk["checked_out"][zk_key] = {
#                     "time":           checkout_hms,
#                     "name":           full_name,
#                     "total_hours":    round(total_h, 2),
#                     "overtime_hours": round(ot_h, 2),
#                     "is_late":        winfo.get("is_late", False),
#                     "late_note":      winfo.get("late_note", ""),
#                     "checkin_time":   winfo.get("time", ""),
#                     "auto_checkout":  True,
#                 }
#                 save_lock(lk)
#                 h_str = f"{int(total_h)}h {int((total_h % 1) * 60)}m"
#                 info(f"  OK {full_name} -- {h_str}")
#                 with result_lock:
#                     success_names.append(full_name)
#             else:
#                 code = ru.status_code if ru else "timeout"
#                 info(f"  FAIL {full_name} HTTP {code}")
#                 with result_lock:
#                     fail_names.append(full_name)

#     threads = [threading.Thread(target=_checkout_one, args=(k, v), daemon=True)
#                for k, v in pending.items()]
#     for t in threads: t.start()
#     for t in threads: t.join()

#     info(f"AUTO-CHECKOUT done: {len(success_names)} OK, {len(fail_names)} failed")
#     if done_cb:
#         done_cb(success_names, fail_names)

# # ===========================================================
# # DAILY SUMMARY EXPORT
# # ===========================================================
# def export_daily_summary():
#     lock     = load_lock()
#     today    = lock.get("date", datetime.now().strftime("%Y-%m-%d"))
#     filename = f"attendance_{today}.csv"
#     rows     = []
#     now      = datetime.now()
#     early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                               second=0, microsecond=0)

#     for zk_id, info in lock.get("checked_out", {}).items():
#         if not isinstance(info, dict):
#             continue
#         co_str   = info.get("time", "")
#         is_early = False
#         try:
#             co_dt    = datetime.strptime(co_str, "%H:%M:%S").replace(
#                 year=now.year, month=now.month, day=now.day)
#             is_early = co_dt < early_limit
#         except Exception:
#             pass
#         rows.append({
#             "ZK_ID":          zk_id,
#             "Name":           info.get("name", ""),
#             "Check-In":       info.get("checkin_time", ""),
#             "Check-Out":      co_str,
#             "Total Hours":    info.get("total_hours", ""),
#             "Overtime Hours": info.get("overtime_hours", 0),
#             "Late?":          "Yes" if info.get("is_late") else "No",
#             "Late Note":      info.get("late_note", ""),
#             "Early Checkout?":"Yes" if is_early else "No",
#             "Auto Checkout?": "Yes" if info.get("auto_checkout") else "No",
#             "Status":         "Complete",
#         })

#     for zk_id, info in lock.get("checked_in", {}).items():
#         if not isinstance(info, dict):
#             continue
#         rows.append({
#             "ZK_ID":          zk_id,
#             "Name":           info.get("name", ""),
#             "Check-In":       info.get("time", ""),
#             "Check-Out":      "---",
#             "Total Hours":    "---",
#             "Overtime Hours": "---",
#             "Late?":          "Yes" if info.get("is_late") else "No",
#             "Late Note":      info.get("late_note", ""),
#             "Early Checkout?":"---",
#             "Auto Checkout?": "---",
#             "Status":         "Still In",
#         })

#     if not rows:
#         return None

#     fieldnames = ["ZK_ID", "Name", "Check-In", "Check-Out", "Total Hours",
#                   "Overtime Hours", "Late?", "Late Note", "Early Checkout?",
#                   "Auto Checkout?", "Status"]
#     with open(filename, "w", newline="", encoding="utf-8") as f:
#         writer = csv.DictWriter(f, fieldnames=fieldnames)
#         writer.writeheader()
#         writer.writerows(rows)

#     _log.info(f"CSV exported: {filename} ({len(rows)} rows)")
#     return filename

# # ===========================================================
# # COLOUR PALETTE
# # ===========================================================
# BG      = "#07090f"; CARD    = "#0c1018"; CARD2   = "#10151f"
# BORDER  = "#1c2438"; BORDER2 = "#243048"
# ACCENT  = "#3b82f6"; ACCENT_DIM = "#172554"; ACCENT2 = "#60a5fa"
# GREEN   = "#10b981"; GREEN2  = "#34d399"; GREEN_DIM  = "#052e1c"
# RED     = "#f43f5e"; RED2    = "#fb7185"; RED_DIM    = "#4c0519"
# ORANGE  = "#f59e0b"; ORANGE2 = "#fbbf24"; ORANGE_DIM = "#3d1f00"
# CYAN2   = "#67e8f9"; CYAN_DIM = "#083344"
# TEXT    = "#e2e8f0"; TEXT2   = "#94a3b8"; MUTED   = "#3d4f69"
# WHITE   = "#ffffff"; GOLD    = "#f59e0b"; GOLD2   = "#fde68a"
# PURPLE  = "#a78bfa"; PURPLE_DIM = "#2e1065"
# TEAL    = "#2dd4bf"; TEAL_DIM   = "#042f2e"

# # ===========================================================
# # UI HELPERS
# # ===========================================================
# def _btn_hover(btn, bg_on, fg_on, bg_off, fg_off):
#     btn.bind("<Enter>", lambda _: btn.config(bg=bg_on,  fg=fg_on))
#     btn.bind("<Leave>", lambda _: btn.config(bg=bg_off, fg=fg_off))

# def _make_sep(parent, color=BORDER, height=1):
#     tk.Frame(parent, bg=color, height=height).pack(fill=tk.X)

# def _initials(name: str) -> str:
#     parts = name.strip().split()
#     if not parts:      return "??"
#     if len(parts) == 1: return parts[0][:2].upper()
#     return (parts[0][0] + parts[-1][0]).upper()

# # ===========================================================
# # FORGOTTEN ID DIALOG
# # ===========================================================
# class ForgottenIDDialog(tk.Toplevel):
#     def __init__(self, parent, on_select):
#         super().__init__(parent)
#         self.on_select  = on_select
#         self._results   = []
#         self._search_job = None
#         self.title("Find Worker by Name")
#         self.configure(bg=BG)
#         self.resizable(False, False)
#         self.grab_set()
#         self.focus_force()
#         W, H = 520, 460
#         sw, sh = parent.winfo_screenwidth(), parent.winfo_screenheight()
#         self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
#         self._build()
#         self.name_entry.focus_set()

#     def _build(self):
#         tk.Frame(self, bg=TEAL, height=3).pack(fill=tk.X)
#         hdr = tk.Frame(self, bg=CARD, padx=20, pady=14); hdr.pack(fill=tk.X)
#         tk.Label(hdr, text="🔍 FORGOTTEN ID LOOKUP",
#                  font=("Courier", 11, "bold"), bg=CARD, fg=TEAL).pack(anchor="w")
#         tk.Label(hdr, text="Type your name below — matching workers will appear instantly",
#                  font=("Courier", 8), bg=CARD, fg=TEXT2).pack(anchor="w", pady=(3, 0))
#         _make_sep(self, BORDER2)

#         sf = tk.Frame(self, bg=BG, padx=20, pady=14); sf.pack(fill=tk.X)
#         tk.Label(sf, text="NAME", font=("Courier", 8, "bold"),
#                  bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 5))
#         eb = tk.Frame(sf, bg=TEAL, padx=2, pady=2); eb.pack(fill=tk.X)
#         ei = tk.Frame(eb, bg=CARD2); ei.pack(fill=tk.X)
#         self._name_var = tk.StringVar()
#         self._name_var.trace_add("write", lambda *_: self._on_type())
#         self.name_entry = tk.Entry(ei, textvariable=self._name_var,
#                                    font=("Courier", 16, "bold"),
#                                    bg=CARD2, fg=WHITE, insertbackground=TEAL,
#                                    bd=0, width=28)
#         self.name_entry.pack(padx=12, pady=10)
#         self.name_entry.bind("<Escape>", lambda _: self.destroy())
#         self.name_entry.bind("<Down>",   self._focus_list)

#         self._status_lbl = tk.Label(sf, text="Start typing to search…",
#                                     font=("Courier", 8), bg=BG, fg=MUTED)
#         self._status_lbl.pack(anchor="w", pady=(6, 0))
#         _make_sep(self, BORDER)

#         lf = tk.Frame(self, bg=BG, padx=20, pady=10); lf.pack(fill=tk.BOTH, expand=True)
#         tk.Label(lf, text="RESULTS — click a name to load their ID",
#                  font=("Courier", 7, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 6))

#         style = ttk.Style(self); style.theme_use("default")
#         style.configure("FID.Treeview", background=CARD2, foreground=TEXT,
#                          fieldbackground=CARD2, rowheight=34,
#                          font=("Courier", 10), borderwidth=0)
#         style.configure("FID.Treeview.Heading", background=CARD,
#                          foreground=TEAL, font=("Courier", 8, "bold"), relief="flat")
#         style.map("FID.Treeview",
#                   background=[("selected", TEAL_DIM)],
#                   foreground=[("selected", TEAL)])

#         cols = ("Name", "ZK ID", "Status")
#         self._tree = ttk.Treeview(lf, columns=cols, show="headings",
#                                   style="FID.Treeview", selectmode="browse", height=6)
#         self._tree.heading("Name",   text="FULL NAME")
#         self._tree.heading("ZK ID",  text="WORKER ID")
#         self._tree.heading("Status", text="TODAY")
#         self._tree.column("Name",   width=270, anchor="w",      stretch=True)
#         self._tree.column("ZK ID",  width=90,  anchor="center")
#         self._tree.column("Status", width=110, anchor="center")
#         for tag, col in [("in", ORANGE2), ("out", GREEN2), ("none", ACCENT2)]:
#             self._tree.tag_configure(tag, foreground=col)

#         vsb = ttk.Scrollbar(lf, orient="vertical", command=self._tree.yview)
#         self._tree.configure(yscrollcommand=vsb.set)
#         self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         vsb.pack(side=tk.RIGHT, fill=tk.Y)
#         self._tree.bind("<Double-1>",   self._on_select)
#         self._tree.bind("<Return>",     self._on_select)
#         self._tree.bind("<Up>",         self._up_to_entry)
#         _make_sep(self, BORDER2)

#         ft = tk.Frame(self, bg=CARD, padx=20, pady=10); ft.pack(fill=tk.X)
#         btn_sel = tk.Button(ft, text="✔ USE SELECTED ID",
#                             font=("Courier", 9, "bold"), relief=tk.FLAT,
#                             bg=TEAL_DIM, fg=TEAL,
#                             activebackground=TEAL, activeforeground=BG,
#                             cursor="hand2", padx=14, pady=6, command=self._on_select)
#         btn_sel.pack(side=tk.LEFT)
#         _btn_hover(btn_sel, TEAL, BG, TEAL_DIM, TEAL)

#         btn_cancel = tk.Button(ft, text="✕ CANCEL",
#                                font=("Courier", 9, "bold"), relief=tk.FLAT,
#                                bg=BORDER, fg=TEXT2,
#                                activebackground=RED_DIM, activeforeground=RED,
#                                cursor="hand2", padx=14, pady=6, command=self.destroy)
#         btn_cancel.pack(side=tk.RIGHT)
#         _btn_hover(btn_cancel, RED_DIM, RED, BORDER, TEXT2)

#     def _focus_list(self, _=None):
#         children = self._tree.get_children()
#         if children:
#             self._tree.focus(children[0])
#             self._tree.selection_set(children[0])
#             self._tree.focus_set()

#     def _up_to_entry(self, _=None):
#         idx = self._tree.index(self._tree.focus())
#         if idx == 0:
#             self.name_entry.focus_set()

#     def _on_type(self):
#         if self._search_job:
#             self.after_cancel(self._search_job)
#         query = self._name_var.get().strip()
#         if len(query) < 2:
#             self._status_lbl.config(text="Type at least 2 characters…", fg=MUTED)
#             self._tree.delete(*self._tree.get_children())
#             return
#         self._status_lbl.config(text="Searching…", fg=ORANGE2)
#         self._search_job = self.after(
#             500, lambda: threading.Thread(
#                 target=self._do_search, args=(query,), daemon=True).start())

#     def _do_search(self, query: str):
#         try:
#             workers = search_workers_by_name(query)
#         except Exception as exc:
#             _log.error(f"ForgottenIDDialog search error: {exc}")
#             workers = []
#         # schedule UI update safely — only if dialog still open
#         try:
#             self.after(0, lambda: self._populate(query, workers))
#         except Exception:
#             pass  # dialog was closed before callback scheduled

#     def _populate(self, query: str, workers: list):
#         try:
#             if not self.winfo_exists():
#                 return
#         except Exception:
#             return
#         self._results = workers
#         self._tree.delete(*self._tree.get_children())
#         if not workers:
#             self._status_lbl.config(
#                 text=f'No workers found matching "{query}"', fg=RED2)
#             return
#         seen_ids = set()
#         for w in workers:
#             name  = w.get("Full_Name", "—")
#             zk_id = str(w.get("ZKTeco_User_ID2", "")).strip()
#             if not zk_id or zk_id in ("0", "None", ""):
#                 zk_id = str(w.get("Worker_ID", "—")).strip()
#             # deduplicate by zk_id
#             iid = zk_id if zk_id not in seen_ids else f"{zk_id}_{name}"
#             seen_ids.add(zk_id)
#             status = get_worker_status(zk_id)
#             labels = {"checked_in": "⏱ IN", "done": "✔ OUT", "none": "— —"}
#             tag    = {"checked_in": "in", "done": "out", "none": "none"}.get(status, "none")
#             try:
#                 self._tree.insert("", tk.END,
#                                   values=(name, zk_id, labels.get(status, "—")),
#                                   tags=(tag,), iid=iid)
#             except Exception:
#                 self._tree.insert("", tk.END,
#                                   values=(name, zk_id, labels.get(status, "—")),
#                                   tags=(tag,))
#         count = len(workers)
#         if count == 1 and query == self._name_var.get().strip():
#             self._status_lbl.config(text="✔ 1 match found — filling ID automatically…", fg=TEAL)
#             first = self._tree.get_children()[0]
#             self._tree.selection_set(first)
#             self._tree.focus(first)
#             self.after(600, self._on_select)
#             return
#         self._status_lbl.config(
#             text=f"Found {count} worker{'s' if count != 1 else ''} — double-click or Enter to select",
#             fg=TEAL)

#     def _on_select(self, _=None):
#         sel = self._tree.selection()
#         if not sel:
#             return
#         # Get ZK ID from the actual row values (column index 1), not the iid
#         try:
#             zk_id = self._tree.item(sel[0], "values")[1]
#         except Exception:
#             zk_id = sel[0]
#         if zk_id and zk_id not in ("—", "", "None"):
#             self.destroy()
#             self.on_select(str(zk_id))

# # ===========================================================
# # FINGERPRINT CANVAS
# # ===========================================================
# class FingerprintCanvas(tk.Canvas):
#     SIZE = 140
#     def __init__(self, parent, **kwargs):
#         super().__init__(parent, width=self.SIZE, height=self.SIZE,
#                          bg=CARD2, highlightthickness=0, **kwargs)
#         self._cx = self._cy = self.SIZE // 2
#         self._angle = 0; self._state = "idle"; self._phase = 0
#         self._arc_items = []
#         self._draw_base(); self._animate()

#     def _draw_base(self):
#         cx, cy = self._cx, self._cy
#         self.delete("fp")
#         self.create_oval(cx-64, cy-64, cx+64, cy+64,
#                          outline=BORDER2, width=1, tags="fp")
#         arc_defs = [(10,0,300,2),(18,20,280,2),(26,30,270,1),
#                     (34,15,290,1),(42,25,265,1),(50,10,285,1),(58,35,250,1)]
#         self._arc_items = []
#         for r, start, extent, w in arc_defs:
#             item = self.create_arc(cx-r, cy-r, cx+r, cy+r,
#                                    start=start, extent=extent,
#                                    outline=MUTED, width=w,
#                                    style="arc", tags="fp")
#             self._arc_items.append(item)
#         self._centre = self.create_oval(cx-5, cy-5, cx+5, cy+5,
#                                         fill=MUTED, outline="", tags="fp")
#         self._spin = self.create_arc(cx-58, cy-58, cx+58, cy+58,
#                                      start=0, extent=0,
#                                      outline=ACCENT, width=3,
#                                      style="arc", tags="fp")

#     def start(self):    self._state = "scanning"
#     def stop_ok(self):
#         self._state = "ok"
#         for item in self._arc_items: self.itemconfig(item, outline=GREEN2)
#         self.itemconfig(self._centre, fill=GREEN2)
#         self.itemconfig(self._spin, extent=0)
#     def stop_err(self, _=""):
#         self._state = "error"
#         for item in self._arc_items: self.itemconfig(item, outline=RED2)
#         self.itemconfig(self._centre, fill=RED2)
#         self.itemconfig(self._spin, extent=0)
#     def reset(self):
#         self._state = "idle"; self._angle = 0; self._draw_base()

#     def _animate(self):
#         self._phase = (self._phase + 1) % 120
#         if self._state == "scanning":
#             self._angle = (self._angle + 6) % 360
#             sweep = int(200 * abs(math.sin(math.radians(self._angle))))
#             self.itemconfig(self._spin, start=self._angle, extent=sweep, outline=ACCENT)
#             for i, item in enumerate(self._arc_items):
#                 a  = 0.3 + 0.7 * abs(math.sin(math.radians((self._phase + i*10) * 4)))
#                 rv = int(int(ACCENT[1:3], 16) * a)
#                 gv = int(int(ACCENT[3:5], 16) * a)
#                 bv = int(int(ACCENT[5:7], 16) * a)
#                 self.itemconfig(item, outline=f"#{rv:02x}{gv:02x}{bv:02x}")
#             a2 = 0.4 + 0.6 * abs(math.sin(math.radians(self._phase * 3)))
#             rv = int(int(ACCENT[1:3], 16) * a2)
#             gv = int(int(ACCENT[3:5], 16) * a2)
#             bv = int(int(ACCENT[5:7], 16) * a2)
#             self.itemconfig(self._centre, fill=f"#{rv:02x}{gv:02x}{bv:02x}")
#         elif self._state == "ok":
#             a  = 0.6 + 0.4 * abs(math.sin(math.radians(self._phase * 2)))
#             rv = int(int(GREEN2[1:3], 16) * a)
#             gv = int(int(GREEN2[3:5], 16) * a)
#             bv = int(int(GREEN2[5:7], 16) * a)
#             col = f"#{rv:02x}{gv:02x}{bv:02x}"
#             for item in self._arc_items: self.itemconfig(item, outline=col)
#             self.itemconfig(self._centre, fill=col)
#         elif self._state == "error":
#             a  = 0.4 + 0.6 * abs(math.sin(math.radians(self._phase * 6)))
#             rv = int(int(RED2[1:3], 16) * a)
#             gv = int(int(RED2[3:5], 16) * a)
#             bv = int(int(RED2[5:7], 16) * a)
#             col = f"#{rv:02x}{gv:02x}{bv:02x}"
#             for item in self._arc_items: self.itemconfig(item, outline=col)
#             self.itemconfig(self._centre, fill=col)
#         else:
#             a  = 0.25 + 0.20 * abs(math.sin(math.radians(self._phase * 1.5)))
#             rv = min(int(int(MUTED[1:3], 16) * a * 2.5), 255)
#             gv = min(int(int(MUTED[3:5], 16) * a * 2.5), 255)
#             bv = min(int(int(MUTED[5:7], 16) * a * 2.5), 255)
#             col = f"#{rv:02x}{gv:02x}{bv:02x}"
#             for item in self._arc_items: self.itemconfig(item, outline=col)
#             self.itemconfig(self._spin, extent=0)
#         self.after(30, self._animate)

# # ===========================================================
# # PULSING LED
# # ===========================================================
# class PulseLED(tk.Canvas):
#     SIZE = 12
#     def __init__(self, parent, color=ACCENT):
#         super().__init__(parent, width=self.SIZE, height=self.SIZE,
#                          bg=parent.cget("bg"), highlightthickness=0)
#         r = self.SIZE // 2
#         self._dot   = self.create_oval(2, 2, r*2-2, r*2-2, fill=color, outline="")
#         self._color = color; self._phase = 0
#         self._pulse()

#     def set_color(self, c):
#         self._color = c
#         self.itemconfig(self._dot, fill=c)

#     def _pulse(self):
#         self._phase = (self._phase + 1) % 60
#         a = 0.55 + 0.45 * abs((self._phase % 60) - 30) / 30
#         c = self._color
#         try:
#             rv = int(int(c[1:3], 16) * a)
#             gv = int(int(c[3:5], 16) * a)
#             bv = int(int(c[5:7], 16) * a)
#             self.itemconfig(self._dot, fill=f"#{rv:02x}{gv:02x}{bv:02x}")
#         except Exception:
#             pass
#         self.after(50, self._pulse)

# # ===========================================================
# # DONUT RING
# # ===========================================================
# class DonutRing(tk.Canvas):
#     SIZE = 80
#     def __init__(self, parent, **kwargs):
#         super().__init__(parent, width=self.SIZE, height=self.SIZE,
#                          bg=CARD2, highlightthickness=0, **kwargs)
#         self._val = 0.0; self._color = GREEN2; self._phase = 0
#         self._draw(0); self._tick()

#     def set_value(self, fraction, color=GREEN2):
#         self._val = max(0.0, min(1.0, fraction)); self._color = color

#     def _draw(self, fraction):
#         self.delete("all")
#         cx = cy = self.SIZE // 2; r = cx - 6
#         self.create_arc(cx-r, cy-r, cx+r, cy+r,
#                         start=0, extent=359.9, outline=BORDER2, width=10, style="arc")
#         if fraction > 0:
#             self.create_arc(cx-r, cy-r, cx+r, cy+r,
#                             start=90, extent=-(fraction * 359.9),
#                             outline=self._color, width=10, style="arc")
#         self.create_text(cx, cy, text=f"{int(fraction*100)}%",
#                          font=("Courier", 11, "bold"),
#                          fill=self._color if fraction > 0 else MUTED)

#     def _tick(self):
#         self._phase += 1; self._draw(self._val); self.after(150, self._tick)

# # ===========================================================
# # ADMIN PANEL  (includes Daily Report tab)
# # ===========================================================
# class AdminPanel(tk.Toplevel):
#     def __init__(self, parent):
#         super().__init__(parent)
#         self.title("Attendance Command Center")
#         self.configure(bg="#ffffff"); self.resizable(True, True)
#         sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
#         W, H   = min(sw, 1200), min(sh, 760)
#         self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
#         self._all_rows  = []; self._sort_col = None; self._sort_asc = True
#         self._build(); self.refresh()

#     def _build(self):
#         # ── header ──────────────────────────────────────────────────
#         hdr = tk.Frame(self, bg="#f8f9fa"); hdr.pack(fill=tk.X)
#         tk.Frame(hdr, bg=PURPLE, height=2).pack(fill=tk.X)
#         hi  = tk.Frame(hdr, bg="#f8f9fa", padx=24, pady=14); hi.pack(fill=tk.X)
#         lf  = tk.Frame(hi, bg="#f8f9fa"); lf.pack(side=tk.LEFT)
#         tk.Label(lf, text="ATTENDANCE COMMAND CENTER",
#                  font=("Courier", 13, "bold"), bg="#f8f9fa", fg="#212529").pack(anchor="w")
#         self.sub_lbl = tk.Label(lf, text="", font=("Courier", 8), bg="#f8f9fa", fg="#6c757d")
#         self.sub_lbl.pack(anchor="w", pady=(2, 0))
#         rf = tk.Frame(hi, bg="#f8f9fa"); rf.pack(side=tk.RIGHT)
#         for txt, cmd, bg_, fg_ in [
#             ("↻ REFRESH",   self.refresh,  ACCENT_DIM, ACCENT2),
#             ("⬇ EXPORT CSV", self._export,  GREEN_DIM,  GREEN2),
#             ("✕ CLOSE",     self.destroy,  BORDER,     TEXT2)]:
#             b = tk.Button(rf, text=txt, font=("Courier", 9, "bold"), relief=tk.FLAT,
#                           bg=bg_, fg=fg_, cursor="hand2", padx=14, pady=6, command=cmd)
#             b.pack(side=tk.LEFT, padx=(0, 6))

#         # ── notebook tabs ────────────────────────────────────────────
#         style = ttk.Style(self); style.theme_use("default")
#         style.configure("Admin.TNotebook",        background="#ffffff", borderwidth=0)
#         style.configure("Admin.TNotebook.Tab",    background="#e2e8f0", foreground="#6c757d",
#                         font=("Courier", 9, "bold"), padding=[18, 8])
#         style.map("Admin.TNotebook.Tab",
#                   background=[("selected", "#ffffff")],
#                   foreground=[("selected", "#1d4ed8")])

#         nb = ttk.Notebook(self, style="Admin.TNotebook")
#         nb.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

#         # Tab 1 — All Records
#         self._tab_records = tk.Frame(nb, bg="#ffffff")
#         nb.add(self._tab_records, text="⚙  ALL RECORDS")

#         # Tab 2 — Daily Report
#         self._tab_report = tk.Frame(nb, bg="#ffffff")
#         nb.add(self._tab_report, text="📋  DAILY REPORT")

#         self._build_records_tab(self._tab_records)
#         self._build_report_tab(self._tab_report)

#     # ================================================================
#     #  TAB 1 — ALL RECORDS
#     # ================================================================
#     def _build_records_tab(self, parent):
#         sf = tk.Frame(parent, bg="#ffffff", padx=20, pady=8); sf.pack(fill=tk.X)
#         tk.Label(sf, text="SEARCH:", font=("Courier", 8, "bold"), bg="#ffffff", fg="#adb5bd").pack(side=tk.LEFT)
#         self._search_var = tk.StringVar()
#         self._search_var.trace_add("write", lambda *_: self._apply_filter())
#         tk.Entry(sf, textvariable=self._search_var, font=("Courier", 10),
#                  bg="#f1f3f5", fg="#212529", insertbackground="#d97706", bd=0, width=30
#                  ).pack(side=tk.LEFT, padx=(8, 0), ipady=4)
#         self._count_lbl = tk.Label(sf, text="", font=("Courier", 8), bg="#ffffff", fg="#adb5bd")
#         self._count_lbl.pack(side=tk.RIGHT)

#         self.kpi_fr = tk.Frame(parent, bg="#ffffff", padx=20, pady=10); self.kpi_fr.pack(fill=tk.X)
#         _make_sep(parent, BORDER2)

#         tw = tk.Frame(parent, bg="#ffffff", padx=20, pady=10); tw.pack(fill=tk.BOTH, expand=True)
#         style = ttk.Style(self); style.theme_use("default")
#         style.configure("Cmd.Treeview", background="#f1f3f5", foreground="#212529",
#                          fieldbackground="#f1f3f5", rowheight=28,
#                          font=("Courier", 9), borderwidth=0)
#         style.configure("Cmd.Treeview.Heading", background="#e2e8f0",
#                          foreground="#1d4ed8", font=("Courier", 9, "bold"),
#                          relief="flat", borderwidth=1)
#         style.map("Cmd.Treeview",
#                   background=[("selected", "#dbeafe")],
#                   foreground=[("selected", "#1d4ed8")])

#         cols    = ("ID", "Name", "Check-In", "Check-Out", "Hours", "OT", "Early?", "Late", "Status")
#         widths  = (60, 220, 100, 100, 70, 70, 70, 75, 90)
#         minws   = (60, 220,  90,  90, 60, 60, 60, 65, 80)
#         anchors = ("center", "center", "center", "center", "center",
#                    "center", "center", "center", "center")
#         stretches = (False, True, False, False, False, False, False, False, False)
#         self.tree = ttk.Treeview(tw, columns=cols, show="headings",
#                                   style="Cmd.Treeview", selectmode="browse")
#         for col, w, mw, a, st in zip(cols, widths, minws, anchors, stretches):
#             self.tree.heading(col, text=col.upper(),
#                               command=lambda c=col: self._sort_by(c))
#             self.tree.column(col, width=w, minwidth=mw, anchor=a, stretch=st)
#         for tag, col in [("late", "#b45309"), ("ot", "#7c3aed"), ("complete", "#059669"),
#                          ("still_in", "#1d4ed8"), ("early", "#0891b2"),
#                          ("auto", "#7c3aed"), ("alt", "#212529")]:
#             self.tree.tag_configure(
#                 tag,
#                 foreground=col,
#                 background="#f1f3f5" if tag == "alt" else "")

#         vsb = ttk.Scrollbar(tw, orient="vertical", command=self.tree.yview)
#         self.tree.configure(yscrollcommand=vsb.set)
#         self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         vsb.pack(side=tk.RIGHT, fill=tk.Y)

#     # ================================================================
#     #  TAB 2 — DAILY REPORT  (Late Arrivals & Early Checkouts)
#     # ================================================================
#     def _build_report_tab(self, parent):
#         # sub-header with refresh
#         hdr = tk.Frame(parent, bg="#f8f9fa", padx=20, pady=10); hdr.pack(fill=tk.X)
#         tk.Frame(hdr, bg=GOLD, height=2).pack(fill=tk.X, side=tk.TOP)
#         hi = tk.Frame(hdr, bg="#f8f9fa"); hi.pack(fill=tk.X, pady=(6, 0))
#         lf = tk.Frame(hi, bg="#f8f9fa"); lf.pack(side=tk.LEFT)
#         tk.Label(lf, text="📋 DAILY REPORT — Late Arrivals & Early Checkouts",
#                  font=("Courier", 11, "bold"), bg="#f8f9fa", fg="#212529").pack(anchor="w")
#         self._report_sub_lbl = tk.Label(lf, text="", font=("Courier", 8), bg="#f8f9fa", fg="#6c757d")
#         self._report_sub_lbl.pack(anchor="w", pady=(2, 0))
#         rf = tk.Frame(hi, bg="#f8f9fa"); rf.pack(side=tk.RIGHT)
#         b = tk.Button(rf, text="↻ REFRESH REPORT", font=("Courier", 9, "bold"),
#                       relief=tk.FLAT, bg=ACCENT_DIM, fg=ACCENT2, cursor="hand2",
#                       padx=14, pady=6, command=self._refresh_report)
#         b.pack()
#         _btn_hover(b, ACCENT2, BG, ACCENT_DIM, ACCENT2)

#         # KPI strip
#         self._report_kpi_fr = tk.Frame(parent, bg="#ffffff", padx=20, pady=10)
#         self._report_kpi_fr.pack(fill=tk.X)
#         tk.Frame(parent, bg="#ced4da", height=1).pack(fill=tk.X)

#         # scrollable body
#         body_wrap = tk.Frame(parent, bg="#ffffff"); body_wrap.pack(fill=tk.BOTH, expand=True)
#         self._report_canvas = tk.Canvas(body_wrap, bg="#ffffff", highlightthickness=0)
#         vsb = ttk.Scrollbar(body_wrap, orient="vertical",
#                              command=self._report_canvas.yview)
#         self._report_canvas.configure(yscrollcommand=vsb.set)
#         vsb.pack(side=tk.RIGHT, fill=tk.Y)
#         self._report_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         self._report_body     = tk.Frame(self._report_canvas, bg="#ffffff")
#         self._report_body_win = self._report_canvas.create_window(
#             (0, 0), window=self._report_body, anchor="nw")
#         self._report_body.bind("<Configure>",   self._on_report_body_resize)
#         self._report_canvas.bind("<Configure>", self._on_report_canvas_resize)
#         self._report_canvas.bind_all("<MouseWheel>",
#             lambda e: self._report_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
#         self._report_canvas.bind_all("<Button-4>",
#             lambda e: self._report_canvas.yview_scroll(-1, "units"))
#         self._report_canvas.bind_all("<Button-5>",
#             lambda e: self._report_canvas.yview_scroll( 1, "units"))

#     def _on_report_body_resize(self, _=None):
#         self._report_canvas.configure(
#             scrollregion=self._report_canvas.bbox("all"))

#     def _on_report_canvas_resize(self, event):
#         self._report_canvas.itemconfig(self._report_body_win, width=event.width)

#     def _make_report_section(self, parent, title, accent, icon, rows, col_defs):
#         sec_hdr = tk.Frame(parent, bg="#f1f3f5"); sec_hdr.pack(fill=tk.X)
#         tk.Frame(sec_hdr, bg=accent, width=6).pack(side=tk.LEFT, fill=tk.Y)
#         inner_hdr = tk.Frame(sec_hdr, bg="#f1f3f5", padx=24, pady=14)
#         inner_hdr.pack(side=tk.LEFT, fill=tk.X, expand=True)
#         tk.Label(inner_hdr, text=f"{icon} {title}",
#                  font=("Courier", 14, "bold"), bg="#f1f3f5", fg=accent).pack(anchor="w")
#         self._report_count_labels[title] = tk.Label(
#             inner_hdr, text="", font=("Courier", 9), bg="#f1f3f5", fg="#6c757d")
#         self._report_count_labels[title].pack(anchor="w", pady=(2, 0))
#         tk.Frame(parent, bg=accent, height=2).pack(fill=tk.X)

#         grid_wrap = tk.Frame(parent, bg="#ffffff"); grid_wrap.pack(fill=tk.X)
#         grid_wrap.columnconfigure(0, minsize=6)
#         for ci, (_, _, minw, wt) in enumerate(col_defs):
#             grid_wrap.columnconfigure(ci+1, minsize=minw, weight=wt)

#         tk.Frame(grid_wrap, bg=accent, width=6).grid(row=0, column=0, sticky="nsew")
#         for ci, (lbl, _, _, _) in enumerate(col_defs):
#             cell = tk.Frame(grid_wrap, bg="#f8f9fa", padx=14, pady=9)
#             cell.grid(row=0, column=ci+1, sticky="nsew")
#             tk.Label(cell, text=lbl, font=("Courier", 9, "bold"),
#                      bg="#f8f9fa", fg=accent, anchor="w").pack(fill=tk.X)
#         tk.Frame(grid_wrap, bg=accent, height=1).grid(
#             row=1, column=0, columnspan=len(col_defs)+1, sticky="ew")

#         if not rows:
#             empty = tk.Frame(grid_wrap, bg="#ffffff")
#             empty.grid(row=2, column=0, columnspan=len(col_defs)+1, sticky="ew")
#             tk.Label(empty, text=f"  No {title.lower()} recorded today.",
#                      font=("Courier", 11), bg="#ffffff", fg="#adb5bd", pady=20
#                      ).pack(anchor="w", padx=24)
#         else:
#             for ri, row in enumerate(rows):
#                 grid_row = ri + 2
#                 row_bg   = "#f1f3f5" if ri % 2 == 0 else "#f8f9fa"
#                 tk.Frame(grid_wrap, bg=accent, width=6).grid(
#                     row=grid_row, column=0, sticky="nsew")
#                 for ci, (_, key, _, _) in enumerate(col_defs):
#                     val  = str(row.get(key, "—"))
#                     fg_  = "#212529"
#                     if key == "zk_id":  fg_ = GOLD
#                     if key == "name":   fg_ = "#212529"
#                     if key == "status": fg_ = accent
#                     bold = key in ("zk_id", "name")
#                     cell = tk.Frame(grid_wrap, bg=row_bg, padx=14, pady=11)
#                     cell.grid(row=grid_row, column=ci+1, sticky="nsew")
#                     tk.Label(cell, text=val,
#                              font=("Courier", 11, "bold" if bold else "normal"),
#                              bg=row_bg, fg=fg_, anchor="w").pack(fill=tk.X)
#                 tk.Frame(grid_wrap, bg="#dee2e6", height=1).grid(
#                     row=grid_row, column=0, columnspan=len(col_defs)+1, sticky="sew")

#         tk.Frame(parent, bg="#ced4da", height=1).pack(fill=tk.X)
#         tk.Frame(parent, bg="#ffffff", height=24).pack()

#     def _refresh_report(self):
#         for w in self._report_body.winfo_children(): w.destroy()
#         self._report_count_labels = {}
#         lock  = load_lock()
#         now   = datetime.now()
#         cin   = lock.get("checked_in",  {})
#         cout  = lock.get("checked_out", {})
#         early_limit  = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                                    second=0, microsecond=0)
#         late_rows  = []
#         early_rows = []
#         all_workers = {**cin, **cout}

#         for zk_id, info in sorted(all_workers.items(),
#             key=lambda x: (x[1].get("time","") or x[1].get("checkin_time",""))
#                           if isinstance(x[1], dict) else ""):
#             if not isinstance(info, dict): continue
#             if not info.get("is_late", False): continue
#             name   = info.get("name", zk_id)
#             ci_raw = info.get("time","") or info.get("checkin_time","")
#             is_out = zk_id in cout
#             try:
#                 ci_disp = datetime.strptime(ci_raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M:%S")
#             except Exception:
#                 ci_disp = ci_raw[-8:] if len(ci_raw) >= 8 else ci_raw or "—"
#             status = "✔ OUT" if is_out else "● ACTIVE"
#             late_rows.append({"zk_id": zk_id, "name": name,
#                               "checkin": ci_disp,
#                               "late_note": info.get("late_note",""),
#                               "status": status})

#         for zk_id, info in sorted(cout.items(),
#             key=lambda x: x[1].get("time","") if isinstance(x[1], dict) else ""):
#             if not isinstance(info, dict): continue
#             co_raw = info.get("time","")
#             try:
#                 co_dt    = datetime.strptime(co_raw, "%H:%M:%S").replace(
#                     year=now.year, month=now.month, day=now.day)
#                 is_early = co_dt < early_limit
#             except Exception:
#                 is_early = False
#             if not is_early: continue
#             name   = info.get("name", zk_id)
#             ci_raw = info.get("checkin_time","")
#             try:
#                 ci_disp = datetime.strptime(ci_raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M:%S")
#             except Exception:
#                 ci_disp = ci_raw[-8:] if len(ci_raw) >= 8 else ci_raw or "—"
#             hrs   = info.get("total_hours", 0)
#             h_str = (f"{int(hrs)}h {int((hrs%1)*60):02d}m"
#                      if isinstance(hrs, (int, float)) else "—")
#             early_rows.append({"zk_id": zk_id, "name": name,
#                                 "checkin": ci_disp, "checkout": co_raw or "—",
#                                 "hours": h_str, "status": "⚡ LEFT EARLY"})

#         # KPI tiles
#         for w in self._report_kpi_fr.winfo_children(): w.destroy()
#         total_in = len(cin) + len(cout)
#         for label, val, fg, border in [
#             ("TOTAL IN TODAY",   total_in,        "#212529", "#ced4da"),
#             ("STILL ON-SITE",    len(cin),         "#1d4ed8", "#bfdbfe"),
#             ("CHECKED OUT",      len(cout),        "#059669", "#a7f3d0"),
#             ("LATE ARRIVALS",    len(late_rows),   "#b45309", "#fde68a"),
#             ("EARLY CHECKOUTS",  len(early_rows),  "#0891b2", "#a5f3fc"),
#         ]:
#             tile = tk.Frame(self._report_kpi_fr, bg="#ffffff", padx=20, pady=10,
#                             highlightbackground=border, highlightthickness=1, relief="flat")
#             tile.pack(side=tk.LEFT, padx=(0, 10), fill=tk.Y)
#             tk.Label(tile, text=str(val),
#                      font=("Courier", 28, "bold"), bg="#ffffff", fg=fg).pack()
#             tk.Label(tile, text=label,
#                      font=("Courier", 7, "bold"),  bg="#ffffff", fg="#6c757d").pack()

#         self._make_report_section(
#             self._report_body, title="LATE ARRIVALS",
#             accent=ORANGE2, icon="⚠", rows=late_rows,
#             col_defs=[("ZK ID","zk_id",80,0),("FULL NAME","name",260,1),
#                       ("CHECKED IN","checkin",120,0),
#                       ("LATE BY","late_note",160,0),
#                       ("STATUS","status",120,0)])
#         self._make_report_section(
#             self._report_body, title="EARLY CHECKOUTS",
#             accent=CYAN2, icon="⚡", rows=early_rows,
#             col_defs=[("ZK ID","zk_id",80,0),("FULL NAME","name",260,1),
#                       ("CHECKED IN","checkin",120,0),
#                       ("CHECKED OUT","checkout",120,0),
#                       ("HOURS","hours",100,0),
#                       ("STATUS","status",140,0)])

#         now_str = now.strftime("%H:%M:%S")
#         self._report_sub_lbl.config(text=(
#             f"Date: {lock.get('date', now.strftime('%Y-%m-%d'))}  "
#             f"Shift start: {SHIFT_START_H:02d}:{SHIFT_START_M:02d}  "
#             f"Early threshold: before {EARLY_CHECKOUT_H:02d}:{EARLY_CHECKOUT_M:02d}  "
#             f"Last refresh: {now_str}"))

#         if "LATE ARRIVALS" in self._report_count_labels:
#             self._report_count_labels["LATE ARRIVALS"].config(
#                 text=f"{len(late_rows)} worker{'s' if len(late_rows)!=1 else ''} arrived late today")
#         if "EARLY CHECKOUTS" in self._report_count_labels:
#             self._report_count_labels["EARLY CHECKOUTS"].config(
#                 text=f"{len(early_rows)} worker{'s' if len(early_rows)!=1 else ''} "
#                      f"left before {EARLY_CHECKOUT_H:02d}:{EARLY_CHECKOUT_M:02d}")

#         self._report_canvas.update_idletasks()
#         self._report_canvas.configure(
#             scrollregion=self._report_canvas.bbox("all"))

#     # ================================================================
#     #  SHARED RECORDS TAB METHODS
#     # ================================================================
#     def _sort_by(self, col):
#         self._sort_asc = not self._sort_asc if self._sort_col == col else True
#         self._sort_col = col; self._apply_filter()

#     def _apply_filter(self):
#         q = self._search_var.get().strip().lower()
#         visible = [r for r in self._all_rows
#                    if not q or any(q in str(v).lower() for v in r["values"])]
#         if self._sort_col:
#             cols = ["ID", "Name", "Check-In", "Check-Out",
#                     "Hours", "OT", "Early?", "Late", "Status"]
#             idx  = cols.index(self._sort_col) if self._sort_col in cols else 0
#             visible.sort(key=lambda r: str(r["values"][idx]),
#                          reverse=not self._sort_asc)
#         self.tree.delete(*self.tree.get_children())
#         for i, r in enumerate(visible):
#             tags = list(r["tags"]) + ["alt"] if i % 2 == 1 else list(r["tags"])
#             self.tree.insert("", tk.END, values=r["values"], tags=tuple(tags))
#         self._count_lbl.config(text=f"{len(visible)}/{len(self._all_rows)} records")

#     def refresh(self):
#         self._all_rows = []
#         lock  = load_lock()
#         cin   = lock.get("checked_in",  {})
#         cout  = lock.get("checked_out", {})
#         late_count = ot_count = early_count = auto_count = 0
#         now   = datetime.now()
#         early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                                   second=0, microsecond=0)

#         for zk_id, info in sorted(cout.items(),
#             key=lambda x: x[1].get("checkin_time", "") if isinstance(x[1], dict) else ""):
#             if not isinstance(info, dict): continue
#             name  = info.get("name", zk_id)
#             ci    = info.get("checkin_time", "---"); ci_s = ci[-8:] if len(ci) > 8 else ci
#             co    = info.get("time", "---")
#             hrs   = info.get("total_hours",    0)
#             ot    = info.get("overtime_hours", 0)
#             late  = info.get("is_late",  False)
#             auto  = info.get("auto_checkout", False)
#             h_str = (f"{int(hrs)}h {int((hrs%1)*60):02d}m"
#                      if isinstance(hrs, (int, float)) else str(hrs))
#             o_str = (f"{int(ot)}h {int((ot%1)*60):02d}m" if ot else "---")
#             is_early = False
#             try:
#                 co_dt    = datetime.strptime(co, "%H:%M:%S").replace(
#                     year=now.year, month=now.month, day=now.day)
#                 is_early = co_dt < early_limit
#             except Exception: pass
#             if late:     late_count  += 1
#             if ot > 0:   ot_count    += 1
#             if is_early: early_count += 1
#             if auto:     auto_count  += 1
#             tags = []
#             if late:     tags.append("late")
#             if ot > 0:   tags.append("ot")
#             if is_early: tags.append("early")
#             if auto:     tags.append("auto")
#             tags.append("complete")
#             self._all_rows.append({"values": (
#                 zk_id, name, ci_s, co, h_str, o_str,
#                 "⚡ YES" if is_early else "---",
#                 "⚠ LATE" if late else "---",
#                 "AUTO" if auto else "✔ DONE"), "tags": tags})

#         for zk_id, info in sorted(cin.items(),
#             key=lambda x: x[1].get("time", "") if isinstance(x[1], dict) else ""):
#             if not isinstance(info, dict): continue
#             name = info.get("name", zk_id)
#             ci   = info.get("time", "---"); late = info.get("is_late", False)
#             try:
#                 dt_in   = datetime.strptime(ci, "%d-%b-%Y %H:%M:%S")
#                 elapsed = (now - dt_in).total_seconds() / 3600
#                 h_str   = f"{int(elapsed)}h {int((elapsed%1)*60):02d}m"
#             except Exception:
#                 h_str = "---"
#             ci_s = ci[-8:] if len(ci) > 8 else ci
#             if late: late_count += 1
#             tags = ["late"] if late else []
#             tags.append("still_in")
#             self._all_rows.append({"values": (
#                 zk_id, name, ci_s, "---", h_str, "---", "---",
#                 "⚠ LATE" if late else "---", "● ACTIVE"), "tags": tags})

#         self._apply_filter()
#         for w in self.kpi_fr.winfo_children(): w.destroy()
#         total = len(cin) + len(cout)
#         for label, val, fg, border in [
#             ("TOTAL",       total,       "#212529", "#ced4da"),
#             ("CHECKED IN",  total,       "#1d4ed8", "#bfdbfe"),
#             ("CHECKED OUT", len(cout),   "#059669", "#a7f3d0"),
#             ("AUTO-OUT",    auto_count,  "#7c3aed", "#ddd6fe"),
#             ("EARLY OUT",   early_count, "#0891b2", "#a5f3fc"),
#             ("LATE",        late_count,  "#b45309", "#fde68a"),
#             ("OVERTIME",    ot_count,    "#7c3aed", "#ddd6fe")]:
#             tile = tk.Frame(self.kpi_fr, bg="#ffffff", padx=13, pady=8,
#                             highlightbackground=border, highlightthickness=1, relief="flat")
#             tile.pack(side=tk.LEFT, padx=(0, 8), fill=tk.Y)
#             tk.Label(tile, text=str(val), font=("Courier", 20, "bold"),
#                      bg="#ffffff", fg=fg).pack()
#             tk.Label(tile, text=label, font=("Courier", 6, "bold"),
#                      bg="#ffffff", fg="#6c757d").pack()

#         self.sub_lbl.config(text=(
#             f"Date:{lock.get('date','')}  "
#             f"Shift:{SHIFT_START_H:02d}:{SHIFT_START_M:02d}  "
#             f"Std:{SHIFT_HOURS}h  Grace:{GRACE_MINUTES}min  "
#             f"Auto-out:{AUTO_CHECKOUT_H:02d}:00  "
#             f"Refreshed:{datetime.now().strftime('%H:%M:%S')}"))

#         # also refresh the report tab data
#         self._refresh_report()

#     def _export(self):
#         fname = export_daily_summary()
#         if fname:
#             messagebox.showinfo("Exported", f"Saved:\n{os.path.abspath(fname)}", parent=self)
#         else:
#             messagebox.showwarning("Nothing to Export", "No records for today.", parent=self)


# # ===========================================================
# # MAIN GUI
# # ===========================================================
# class FingerprintGUI:
#     def __init__(self, root):
#         self.root   = root
#         self.root.title("Wavemark Properties — Attendance Terminal")
#         self.root.configure(bg=BG)
#         self.root.resizable(False, False)
#         self._busy         = False
#         self._debounce_job = None
#         self._log_lines    = 0
#         self._gui_q: queue.Queue = queue.Queue()
#         sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
#         W, H   = min(sw, 980), min(sh, 800)
#         self.root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
#         self._build_ui()
#         self._tick_clock()
#         self._tick_stats()
#         self._tick_autocheckout()
#         self._drain_q()
#         self.root.protocol("WM_DELETE_WINDOW", self._on_close)

#         # Startup check — warn user immediately if .env is broken
#         self.root.after(1500, self._startup_token_check)

#     def _startup_token_check(self):
#         def _check():
#             token = get_access_token()
#             if not token:
#                 self._gui(lambda: self.log(
#                     "⚠ WARNING: Could not connect to Zoho — "
#                     "check CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN in .env\n"
#                     "  Visit https://api-console.zoho.com to regenerate credentials.", "err"))
#         threading.Thread(target=_check, daemon=True).start()

#     def _drain_q(self):
#         try:
#             while True: self._gui_q.get_nowait()()
#         except queue.Empty: pass
#         self.root.after(50, self._drain_q)

#     def _gui(self, fn):
#         self._gui_q.put(fn)

#     # ------ UI BUILD ------
#     def _build_ui(self):
#         self._build_header(); self._build_body()
#         self._build_footer(); self._build_flash()

#     def _build_header(self):
#         hdr = tk.Frame(self.root, bg=CARD); hdr.pack(fill=tk.X)
#         tk.Frame(hdr, bg=GOLD, height=3).pack(fill=tk.X)
#         hi  = tk.Frame(hdr, bg=CARD, padx=28, pady=14); hi.pack(fill=tk.X)
#         lf  = tk.Frame(hi, bg=CARD); lf.pack(side=tk.LEFT)
#         # ── Animated marquee for company name ──────────────────────
#         self._marquee_canvas = tk.Canvas(lf, bg=CARD, highlightthickness=0,
#                                          height=26, width=340)
#         self._marquee_canvas.pack(anchor="w")
#         self._marquee_text = self._marquee_canvas.create_text(
#             340, 13, text="WAVEMARK PROPERTIES LIMITED   ✦   WAVEMARK PROPERTIES LIMITED   ✦   ",
#             font=("Courier", 11, "bold"), fill=GOLD, anchor="w")
#         self._marquee_x = 340
#         self._marquee_speed = 2
#         self._animate_marquee()
#         # ── Static subtitle ─────────────────────────────────────────
#         tk.Label(lf, text="Biometric Attendance Terminal · v5.3 · 2000-user edition",
#                  font=("Courier", 8), bg=CARD, fg=MUTED).pack(anchor="w", pady=(1, 0))
#         rf = tk.Frame(hi, bg=CARD); rf.pack(side=tk.RIGHT)
#         btn_row = tk.Frame(rf, bg=CARD); btn_row.pack(anchor="e", pady=(0, 6))
#         btn_refresh = tk.Button(btn_row, text="↻ REFRESH",
#                                 font=("Courier", 8, "bold"), relief=tk.FLAT,
#                                 bg=ACCENT_DIM, fg=ACCENT2,
#                                 activebackground=ACCENT, activeforeground=WHITE,
#                                 cursor="hand2", padx=10, pady=5,
#                                 command=self._refresh_main)
#         btn_refresh.pack(side=tk.LEFT, padx=(0, 6))
#         _btn_hover(btn_refresh, ACCENT, WHITE, ACCENT_DIM, ACCENT2)
#         btn_admin = tk.Button(btn_row, text="⚙ ADMIN PANEL",
#                               font=("Courier", 8, "bold"), relief=tk.FLAT,
#                               bg=PURPLE_DIM, fg=PURPLE,
#                               activebackground=PURPLE, activeforeground=WHITE,
#                               cursor="hand2", padx=10, pady=5,
#                               command=self._open_admin)
#         btn_admin.pack(side=tk.LEFT)
#         _btn_hover(btn_admin, PURPLE, WHITE, PURPLE_DIM, PURPLE)
#         self.date_lbl  = tk.Label(rf, text="", font=("Courier", 8),  bg=CARD, fg=TEXT2)
#         self.date_lbl.pack(anchor="e")
#         self.clock_lbl = tk.Label(rf, text="", font=("Courier", 24, "bold"), bg=CARD, fg=WHITE)
#         self.clock_lbl.pack(anchor="e")
#         _make_sep(self.root, BORDER2)
#         sbar = tk.Frame(self.root, bg=CARD2, padx=28, pady=6); sbar.pack(fill=tk.X)
#         tk.Label(sbar, text=(f"SHIFT {SHIFT_START_H:02d}:{SHIFT_START_M:02d} · "
#                              f"STD {SHIFT_HOURS}H · GRACE {GRACE_MINUTES}MIN · "
#                              f"EARLY<{EARLY_CHECKOUT_H:02d}:00 · AUTO@{AUTO_CHECKOUT_H:02d}:00"),
#                  font=("Courier", 8), bg=CARD2, fg=MUTED).pack(side=tk.LEFT)
#         tk.Label(sbar, text="ENTER → auto-action   ESC → clear",
#                  font=("Courier", 8), bg=CARD2, fg=MUTED).pack(side=tk.RIGHT)

#     def _build_body(self):
#         body = tk.Frame(self.root, bg=BG, padx=24, pady=14)
#         body.pack(fill=tk.BOTH, expand=True)
#         cols = tk.Frame(body, bg=BG); cols.pack(fill=tk.BOTH, expand=True)
#         left  = tk.Frame(cols, bg=BG); left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         tk.Frame(cols, bg=BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y, padx=16)
#         right = tk.Frame(cols, bg=BG, width=300); right.pack(side=tk.LEFT, fill=tk.Y)
#         self._build_left(left); self._build_right(right)

#     def _build_left(self, parent):
#         id_card = tk.Frame(parent, bg=CARD2, highlightbackground=BORDER2, highlightthickness=1)
#         id_card.pack(fill=tk.X, pady=(0, 12))
#         ch = tk.Frame(id_card, bg=CARD, padx=18, pady=10); ch.pack(fill=tk.X)
#         tk.Label(ch, text="WORKER IDENTIFICATION",
#                  font=("Courier", 8, "bold"), bg=CARD, fg=TEXT2).pack(side=tk.LEFT)
#         self._led = PulseLED(ch, MUTED); self._led.pack(side=tk.RIGHT, padx=(0, 2))
#         _make_sep(id_card, BORDER)
#         ci = tk.Frame(id_card, bg=CARD2, padx=18, pady=14); ci.pack(fill=tk.X)
#         er = tk.Frame(ci, bg=CARD2); er.pack(fill=tk.X)
#         tk.Label(er, text="ID", font=("Courier", 8, "bold"),
#                  bg=CARD2, fg=MUTED, width=3, anchor="w").pack(side=tk.LEFT)
#         eb = tk.Frame(er, bg=GOLD, padx=1, pady=1); eb.pack(side=tk.LEFT, padx=(6, 0))
#         ei = tk.Frame(eb, bg="#09101a"); ei.pack()
#         self.user_entry = tk.Entry(ei, font=("Courier", 28, "bold"), width=9, bd=0,
#                                    bg="#09101a", fg=WHITE, insertbackground=GOLD,
#                                    selectbackground=GOLD2, selectforeground=BG)
#         self.user_entry.pack(padx=14, pady=8)
#         self.user_entry.bind("<KeyRelease>", self._on_key)
#         self.user_entry.bind("<Return>",     self._on_enter)
#         self.user_entry.bind("<Escape>",     lambda _: self._reset_ui())
#         self.user_entry.focus_set()
#         btn_clr = tk.Button(er, text="✕", font=("Courier", 10, "bold"), relief=tk.FLAT,
#                             bg=BORDER, fg=MUTED,
#                             activebackground=RED_DIM, activeforeground=RED,
#                             cursor="hand2", padx=8, pady=4, command=self._reset_ui)
#         btn_clr.pack(side=tk.LEFT, padx=(10, 0))
#         _btn_hover(btn_clr, RED_DIM, RED, BORDER, MUTED)

#         idf = tk.Frame(ci, bg=CARD2); idf.pack(fill=tk.X, pady=(12, 0))
#         self._avatar_cv = tk.Canvas(idf, width=48, height=48,
#                                     bg=CARD2, highlightthickness=0)
#         self._avatar_cv.pack(side=tk.LEFT, padx=(0, 12))
#         self._avatar_circle = self._avatar_cv.create_oval(2, 2, 46, 46,
#                                                            fill=BORDER, outline="")
#         self._avatar_text   = self._avatar_cv.create_text(24, 24, text="",
#                                                            font=("Courier", 13, "bold"),
#                                                            fill=MUTED)
#         info_col = tk.Frame(idf, bg=CARD2); info_col.pack(side=tk.LEFT, fill=tk.X)
#         self.name_lbl = tk.Label(info_col, text="—",
#                                   font=("Courier", 16, "bold"), bg=CARD2, fg=MUTED)
#         self.name_lbl.pack(anchor="w")
#         self.hint_lbl = tk.Label(info_col, text="Enter a Worker ID above",
#                                   font=("Courier", 9), bg=CARD2, fg=MUTED)
#         self.hint_lbl.pack(anchor="w", pady=(2, 0))

#         self.sf = tk.Frame(parent, bg=ACCENT_DIM,
#                            highlightbackground=ACCENT, highlightthickness=1)
#         self.sf.pack(fill=tk.X, pady=(0, 12))
#         sb_inner = tk.Frame(self.sf, bg=ACCENT_DIM); sb_inner.pack(fill=tk.X, padx=16, pady=10)
#         self._status_led = PulseLED(sb_inner, ACCENT)
#         self._status_led.pack(side=tk.LEFT, padx=(0, 8))
#         self.sl = tk.Label(sb_inner, text="Awaiting Worker ID",
#                            font=("Courier", 10, "bold"),
#                            bg=ACCENT_DIM, fg=ACCENT, anchor="w")
#         self.sl.pack(side=tk.LEFT, fill=tk.X)

#         # ── action buttons (Daily Report button REMOVED) ──
#         br = tk.Frame(parent, bg=BG); br.pack(fill=tk.X, pady=(0, 12))
#         self.btn_in = tk.Button(br, text="▶ CHECK IN",
#                                 font=("Courier", 12, "bold"), width=13,
#                                 relief=tk.FLAT, bg=GREEN_DIM, fg=MUTED,
#                                 activebackground=GREEN, activeforeground=BG,
#                                 cursor="hand2", state=tk.DISABLED,
#                                 command=lambda: self._trigger("checkin"))
#         self.btn_in.pack(side=tk.LEFT, ipady=12, padx=(0, 6))

#         self.btn_forgot = tk.Button(br, text="🔍 FORGOT ID",
#                                     font=("Courier", 9, "bold"), relief=tk.FLAT,
#                                     bg=TEAL_DIM, fg=TEAL,
#                                     activebackground=TEAL, activeforeground=BG,
#                                     cursor="hand2", padx=10,
#                                     command=self._open_forgotten_id)
#         self.btn_forgot.pack(side=tk.LEFT, ipady=12, padx=(0, 6))
#         _btn_hover(self.btn_forgot, TEAL, BG, TEAL_DIM, TEAL)

#         self.btn_out = tk.Button(br, text="■ CHECK OUT",
#                                  font=("Courier", 12, "bold"), width=13,
#                                  relief=tk.FLAT, bg=RED_DIM, fg=MUTED,
#                                  activebackground=RED, activeforeground=WHITE,
#                                  cursor="hand2", state=tk.DISABLED,
#                                  command=lambda: self._trigger("checkout"))
#         self.btn_out.pack(side=tk.LEFT, ipady=12, padx=(0, 6))

#         btn_exp = tk.Button(br, text="⬇ CSV", font=("Courier", 9, "bold"), relief=tk.FLAT,
#                             bg=BORDER, fg=TEXT2, cursor="hand2", padx=10,
#                             command=self._quick_export)
#         btn_exp.pack(side=tk.RIGHT, ipady=12)
#         _btn_hover(btn_exp, GREEN_DIM, GREEN2, BORDER, TEXT2)

#         _make_sep(parent, BORDER); tk.Frame(parent, bg=BG, height=8).pack()
#         lh = tk.Frame(parent, bg=BG); lh.pack(fill=tk.X, pady=(0, 6))
#         tk.Label(lh, text="ACTIVITY LOG",
#                  font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(side=tk.LEFT)
#         self._log_count_lbl = tk.Label(lh, text="", font=("Courier", 7), bg=BG, fg=MUTED)
#         self._log_count_lbl.pack(side=tk.LEFT, padx=(8, 0))
#         btn_clrlog = tk.Button(lh, text="CLEAR", font=("Courier", 7, "bold"),
#                                relief=tk.FLAT, bg=BORDER, fg=MUTED,
#                                padx=8, pady=2, cursor="hand2",
#                                command=self._clear_log)
#         btn_clrlog.pack(side=tk.RIGHT)
#         _btn_hover(btn_clrlog, BORDER2, TEXT2, BORDER, MUTED)

#         lw = tk.Frame(parent, bg=CARD, highlightbackground=BORDER2, highlightthickness=1)
#         lw.pack(fill=tk.BOTH, expand=True)
#         sb = tk.Scrollbar(lw, bg=BORDER, troughcolor=CARD); sb.pack(side=tk.RIGHT, fill=tk.Y)
#         self.log_box = tk.Text(lw, font=("Courier", 9), bg=CARD, fg=TEXT2, relief=tk.FLAT,
#                                padx=14, pady=10, yscrollcommand=sb.set,
#                                state=tk.DISABLED, cursor="arrow")
#         self.log_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         sb.config(command=self.log_box.yview)
#         for tag, col in [("ok", GREEN2), ("err", RED2), ("warn", ORANGE2),
#                          ("info", ACCENT2), ("ts", MUTED), ("div", BORDER2),
#                          ("late", ORANGE), ("ot", PURPLE), ("early", CYAN2)]:
#             self.log_box.tag_config(tag, foreground=col)

#     def _build_right(self, parent):
#         tk.Label(parent, text="BIOMETRIC SCANNER",
#                  font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 8))
#         sc       = tk.Frame(parent, bg=CARD2, highlightbackground=BORDER2, highlightthickness=1)
#         sc.pack(fill=tk.X, pady=(0, 14))
#         sc_inner = tk.Frame(sc, bg=CARD2, pady=16); sc_inner.pack()
#         self._fp       = FingerprintCanvas(sc_inner); self._fp.pack(pady=(0, 8))
#         self._scan_lbl = tk.Label(sc_inner, text="READY",
#                                   font=("Courier", 9, "bold"), bg=CARD2, fg=MUTED)
#         self._scan_lbl.pack()
#         self._scan_sub = tk.Label(sc_inner, text="Place finger when prompted",
#                                   font=("Courier", 7), bg=CARD2, fg=MUTED, wraplength=200)
#         self._scan_sub.pack(pady=(2, 0))

#         tk.Label(parent, text="LIVE DASHBOARD",
#                  font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 8))
#         dash = tk.Frame(parent, bg=BG); dash.pack(fill=tk.X)
#         row1 = tk.Frame(dash, bg=BG); row1.pack(fill=tk.X, pady=(0, 8))
#         self._tile_cin  = self._make_tile(row1, "CHECKED IN TODAY", "0", ACCENT2, "#0d1f3f")
#         self._tile_cout = self._make_tile(row1, "CHECKED OUT",      "0", GREEN2,  "#0a3321")
#         row2 = tk.Frame(dash, bg=BG); row2.pack(fill=tk.X, pady=(0, 8))
#         self._tile_early = self._make_tile(
#             row2, f"EARLY OUT (<{EARLY_CHECKOUT_H:02d}:00)", "0", CYAN2, CYAN_DIM, full=True)
#         row3 = tk.Frame(dash, bg=BG); row3.pack(fill=tk.X, pady=(0, 8))
#         self._tile_late = self._make_tile(row3, "LATE ARRIVALS", "0", ORANGE2, "#3d1f00")
#         self._tile_ot   = self._make_tile(row3, "OVERTIME",       "0", PURPLE,  "#1e0a40")

#         dr_frame = tk.Frame(parent, bg=CARD2, highlightbackground=BORDER, highlightthickness=1)
#         dr_frame.pack(fill=tk.X, pady=(0, 10))
#         dr_inner = tk.Frame(dr_frame, bg=CARD2, pady=10, padx=16); dr_inner.pack(fill=tk.X)
#         tk.Label(dr_inner, text="COMPLETION RATE",
#                  font=("Courier", 7, "bold"), bg=CARD2, fg=MUTED).pack(anchor="w", pady=(0, 6))
#         dr_row = tk.Frame(dr_inner, bg=CARD2); dr_row.pack(fill=tk.X)
#         self._donut = DonutRing(dr_row); self._donut.pack(side=tk.LEFT, padx=(0, 14))
#         dr_leg = tk.Frame(dr_row, bg=CARD2); dr_leg.pack(side=tk.LEFT, fill=tk.Y)
#         self._legend_lbl = tk.Label(dr_leg, text="0 of 0 workers\nhave checked out",
#                                     font=("Courier", 8), bg=CARD2, fg=TEXT2, justify=tk.LEFT)
#         self._legend_lbl.pack(anchor="w")
#         self._early_lbl  = tk.Label(dr_leg, text="",
#                                     font=("Courier", 8), bg=CARD2, fg=CYAN2, justify=tk.LEFT)
#         self._early_lbl.pack(anchor="w", pady=(6, 0))

#         tk.Label(parent, text="RECENT EVENTS",
#                  font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(8, 6))
#         ev_fr = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
#         ev_fr.pack(fill=tk.BOTH, expand=True)
#         self._event_box = tk.Text(ev_fr, font=("Courier", 8), bg=CARD, fg=TEXT2,
#                                   relief=tk.FLAT, padx=10, pady=8,
#                                   state=tk.DISABLED, cursor="arrow", height=7)
#         self._event_box.pack(fill=tk.BOTH, expand=True)
#         for tag, col in [("in", GREEN2), ("out", ACCENT2),
#                          ("warn", ORANGE2), ("ts", MUTED), ("early", CYAN2)]:
#             self._event_box.tag_config(tag, foreground=col)

#     def _make_tile(self, parent, label, value, fg, bg2, full=False):
#         tile = tk.Frame(parent, bg=CARD2, padx=14, pady=10,
#                         highlightbackground=bg2, highlightthickness=1)
#         kw = {"fill": tk.X, "expand": True}
#         if not full: kw["padx"] = (0, 6)
#         tile.pack(side=tk.LEFT, **kw)
#         val_lbl = tk.Label(tile, text=value, font=("Courier", 26, "bold"), bg=CARD2, fg=fg)
#         val_lbl.pack()
#         tk.Label(tile, text=label, font=("Courier", 6, "bold"), bg=CARD2, fg=TEXT2).pack()
#         return val_lbl

#     def _build_footer(self):
#         _make_sep(self.root, BORDER2)
#         foot = tk.Frame(self.root, bg=CARD, padx=28, pady=7)
#         foot.pack(fill=tk.X, side=tk.BOTTOM)
#         self._foot_lbl = tk.Label(foot, text="", font=("Courier", 8), bg=CARD, fg=MUTED)
#         self._foot_lbl.pack(side=tk.LEFT)
#         tk.Label(foot, text=(f"Shift {SHIFT_START_H:02d}:{SHIFT_START_M:02d}–"
#                              f"{(SHIFT_START_H+SHIFT_HOURS)%24:02d}:{SHIFT_START_M:02d} "
#                              f"· {SHIFT_HOURS}h std · {GRACE_MINUTES}min grace "
#                              f"· early<{EARLY_CHECKOUT_H:02d}:00 "
#                              f"· auto@{AUTO_CHECKOUT_H:02d}:00"),
#                  font=("Courier", 8), bg=CARD, fg=MUTED).pack(side=tk.RIGHT)

#     def _build_flash(self):
#         self.flash = tk.Frame(self.root, bg=ACCENT)
#         self.fi = tk.Label(self.flash, font=("Courier", 60, "bold"), bg=ACCENT, fg=WHITE)
#         self.fi.place(relx=0.5, rely=0.22, anchor="center")
#         self.fm = tk.Label(self.flash, font=("Courier", 22, "bold"),
#                            bg=ACCENT, fg=WHITE, wraplength=740)
#         self.fm.place(relx=0.5, rely=0.40, anchor="center")
#         self.fs = tk.Label(self.flash, font=("Courier", 22, "bold"),
#                            bg=ACCENT, fg=WHITE, wraplength=740, justify=tk.CENTER)
#         self.fs.place(relx=0.5, rely=0.56, anchor="center")
#         self.fx = tk.Label(self.flash, font=("Courier", 11, "bold"),
#                            bg=ACCENT, fg=GOLD2, wraplength=740)
#         self.fx.place(relx=0.5, rely=0.72, anchor="center")

#     # ------ TICKERS ------
#     def _tick_clock(self):
#         n = datetime.now()
#         self.date_lbl.config(text=n.strftime("%A, %d %B %Y"))
#         self.clock_lbl.config(text=n.strftime("%H:%M:%S"))
#         self.root.after(1000, self._tick_clock)

#     def _tick_stats(self):
#         lock  = load_lock()
#         cin   = lock.get("checked_in",  {})
#         cout  = lock.get("checked_out", {})
#         total = len(cin) + len(cout)
#         early = count_early_checkouts(lock)
#         late  = sum(1 for v in {**cin, **cout}.values()
#                     if isinstance(v, dict) and v.get("is_late"))
#         ot    = sum(1 for v in cout.values()
#                     if isinstance(v, dict) and v.get("overtime_hours", 0) > 0)
#         self._tile_cin.config(text=str(total))
#         self._tile_cout.config(text=str(len(cout)))
#         self._tile_early.config(text=str(early))
#         self._tile_late.config(text=str(late))
#         self._tile_ot.config(text=str(ot))
#         fraction   = len(cout) / total if total > 0 else 0
#         donut_col  = GREEN2 if fraction >= 0.8 else ORANGE2 if fraction >= 0.4 else ACCENT2
#         self._donut.set_value(fraction, donut_col)
#         self._legend_lbl.config(text=f"{len(cout)} of {total} workers\nhave checked out")
#         self._early_lbl.config(
#             text=f"⚡ {early} left before {EARLY_CHECKOUT_H:02d}:00" if early else "")
#         self._foot_lbl.config(
#             text=f"In:{total}  Out:{len(cout)}  On-site:{len(cin)}  "
#                  f"Early:{early}  Late:{late}  OT:{ot}")
#         self.root.after(STATS_REFRESH_MS, self._tick_stats)

#     def _tick_autocheckout(self):
#         now = datetime.now()
#         if (now.hour > AUTO_CHECKOUT_H or
#                 (now.hour == AUTO_CHECKOUT_H and now.minute >= AUTO_CHECKOUT_M)):
#             lock    = load_lock()
#             pending = {k: v for k, v in lock.get("checked_in", {}).items()
#                        if isinstance(v, dict)}
#             if pending:
#                 self.log(f"AUTO-CHECKOUT triggered @ {now.strftime('%H:%M')} "
#                          f"— {len(pending)} worker(s)", "warn")
#                 threading.Thread(
#                     target=run_auto_checkout,
#                     kwargs={"gui_log_fn": self.log, "done_cb": self._auto_checkout_done},
#                     daemon=True).start()
#             return
#         self.root.after(30_000, self._tick_autocheckout)

#     def _auto_checkout_done(self, success_names, fail_names):
#         def _u():
#             self._tick_stats()
#             n     = len(success_names)
#             names = ", ".join(success_names[:5]) + ("..." if len(success_names) > 5 else "")
#             extra = f"Failed: {', '.join(fail_names)}" if fail_names else ""
#             self._show_flash(">>", f"Auto-Checkout @ {datetime.now().strftime('%H:%M')}",
#                              f"{n} worker(s) checked out\n{names}", extra, "#1e0a40")
#             for name in success_names:
#                 self._add_event("AUTO-OUT", name, "warn")
#         self._gui(_u)

#     # ------ PANEL OPENERS ------
#     def _animate_marquee(self):
#         try:
#             self._marquee_x -= self._marquee_speed
#             # Get the bounding box of the text to know its full width
#             bbox = self._marquee_canvas.bbox(self._marquee_text)
#             if bbox:
#                 text_width = bbox[2] - bbox[0]
#                 # Reset when the full text has scrolled off the left edge
#                 if self._marquee_x < -text_width // 2:
#                     self._marquee_x = 340
#             self._marquee_canvas.coords(self._marquee_text, self._marquee_x, 13)
#             self.root.after(30, self._animate_marquee)
#         except Exception:
#             pass  # window was destroyed

#     def _open_admin(self):           AdminPanel(self.root)

#     def _refresh_main(self):
#         """Destroy and fully rebuild the entire main window."""
#         self.root.destroy()
#         root = tk.Tk()
#         FingerprintGUI(root)
#         root.mainloop()

#     def _open_forgotten_id(self):
#         def _on_select(zk_id: str):
#             self.user_entry.delete(0, tk.END)
#             self.user_entry.insert(0, zk_id)
#             self.user_entry.focus_set()
#             self._apply_status(get_worker_status(zk_id))
#             threading.Thread(target=self._validate, args=(zk_id,), daemon=True).start()
#             self.log(f"Forgotten ID resolved → ZK#{zk_id}", "info")
#         ForgottenIDDialog(self.root, on_select=_on_select)

#     def _quick_export(self):
#         def _do():
#             fname = export_daily_summary()
#             if fname:
#                 self._gui(lambda: self.log(f"Exported → {os.path.abspath(fname)}", "ok"))
#             else:
#                 self._gui(lambda: self.log("Nothing to export.", "warn"))
#         threading.Thread(target=_do, daemon=True).start()

#     # ------ LOGGING ------
#     def log(self, msg: str, tag: str = "info"):
#         def _do():
#             self.log_box.config(state=tk.NORMAL)
#             if self._log_lines >= LOG_MAX_LINES:
#                 self.log_box.delete("1.0", "50.0")
#                 self._log_lines = max(self._log_lines - 50, 0)
#             self.log_box.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] ", "ts")
#             self.log_box.insert(tk.END, f"{msg}\n", tag)
#             self.log_box.see(tk.END)
#             self.log_box.config(state=tk.DISABLED)
#             self._log_lines += 1
#             self._log_count_lbl.config(text=f"({self._log_lines})")
#         self._gui(_do)

#     def _clear_log(self):
#         self.log_box.config(state=tk.NORMAL)
#         self.log_box.delete("1.0", tk.END)
#         self.log_box.config(state=tk.DISABLED)
#         self._log_lines = 0
#         self._log_count_lbl.config(text="")

#     def _add_event(self, action: str, name: str, tag: str = "ts"):
#         def _do():
#             self._event_box.config(state=tk.NORMAL)
#             ts = datetime.now().strftime("%H:%M")
#             self._event_box.insert("1.0", f"{ts}  {action:<10}  {name}\n", tag)
#             lines = int(self._event_box.index("end-1c").split(".")[0])
#             if lines > 100:
#                 self._event_box.delete("80.0", tk.END)
#             self._event_box.config(state=tk.DISABLED)
#         self._gui(_do)

#     def _show_flash(self, icon, headline, sub, extra, color):
#         self.flash.config(bg=color)
#         for w, v in [(self.fi, icon), (self.fm, headline), (self.fs, sub), (self.fx, extra)]:
#             w.config(text=v, bg=color)
#         self.flash.place(x=0, y=0, relwidth=1, relheight=1)
#         self.flash.lift()
#         self.root.after(2400, self.flash.place_forget)

#     # ------ SCANNER STATES ------
#     def _scan_start(self):
#         self._fp.start()
#         self._scan_lbl.config(text="SCANNING…", fg=ORANGE2)
#         self._scan_sub.config(text="Place your finger on the reader now")

#     def _scan_ok(self):
#         self._fp.stop_ok()
#         self._scan_lbl.config(text="CAPTURED ✔", fg=GREEN2)
#         self._scan_sub.config(text="Processing…")

#     def _scan_err(self, msg="FAILED"):
#         self._fp.stop_err(msg)
#         self._scan_lbl.config(text=msg, fg=RED2)
#         self._scan_sub.config(text="Please try again")

#     def _scan_reset(self):
#         self._fp.reset()
#         self._scan_lbl.config(text="READY", fg=MUTED)
#         self._scan_sub.config(text="Place finger when prompted")

#     # ------ STATUS / BUTTONS ------
#     def _set_status(self, text, fg=ACCENT, bg=ACCENT_DIM, border=ACCENT):
#         self.sf.config(bg=bg, highlightbackground=border)
#         for w in self.sf.winfo_children():
#             for iw in [w] + list(w.winfo_children()):
#                 try: iw.config(bg=bg)
#                 except Exception: pass
#         self.sl.config(text=text, fg=fg, bg=bg)
#         try:
#             self._status_led.config(bg=bg)
#             self._status_led.set_color(fg)
#             self._led.set_color(fg)
#         except Exception: pass

#     def _set_buttons(self, in_s, out_s):
#         self.btn_in.config(state=in_s,
#                            bg=GREEN if in_s == tk.NORMAL else GREEN_DIM,
#                            fg=BG if in_s == tk.NORMAL else MUTED)
#         self.btn_out.config(state=out_s,
#                             bg=RED if out_s == tk.NORMAL else RED_DIM,
#                             fg=WHITE if out_s == tk.NORMAL else MUTED)

#     def _set_avatar(self, name=None, color=BORDER):
#         self._avatar_cv.itemconfig(self._avatar_circle, fill=color)
#         self._avatar_cv.itemconfig(self._avatar_text,
#                                    text=_initials(name) if name else "",
#                                    fill=WHITE if name else MUTED)

#     def _apply_status(self, status, name=None, ci_time=""):
#         if status == "done":
#             self._set_buttons(tk.DISABLED, tk.DISABLED)
#             self._set_status("Attendance complete — see you tomorrow", RED, RED_DIM, RED)
#             self._set_avatar(name, RED_DIM)
#         elif status == "checked_in":
#             self._set_buttons(tk.DISABLED, tk.NORMAL)
#             msg = (f"Already checked IN at {ci_time} — proceed to Check-Out"
#                    if ci_time else "Already checked IN — proceed to Check-Out")
#             self._set_status(msg, ORANGE, ORANGE_DIM, ORANGE)
#             self._set_avatar(name, ORANGE_DIM)
#         elif status == "none":
#             self._set_buttons(tk.NORMAL, tk.DISABLED)
#             self._set_status("Ready to CHECK IN", GREEN, GREEN_DIM, GREEN)
#             self._set_avatar(name, GREEN_DIM)
#         else:
#             self._set_buttons(tk.DISABLED, tk.DISABLED)
#             self._set_status("Awaiting Worker ID", ACCENT, ACCENT_DIM, ACCENT)
#             self._set_avatar(None, BORDER)

#     # ------ KEY / ENTER ------
#     def _on_key(self, _=None):
#         if self._debounce_job:
#             self.root.after_cancel(self._debounce_job)
#         uid = self.user_entry.get().strip()
#         if not uid:
#             self._soft_reset(); return
#         self._apply_status(get_worker_status(uid))
#         self._debounce_job = self.root.after(
#             650, lambda: threading.Thread(
#                 target=self._validate, args=(uid,), daemon=True).start())

#     def _validate(self, uid: str):
#         if self.user_entry.get().strip() != uid or self._busy:
#             return
#         worker = find_worker(uid)
#         def _upd():
#             if self.user_entry.get().strip() != uid:
#                 return
#             if not worker:
#                 self.name_lbl.config(text="Unknown ID", fg=RED2)
#                 self.hint_lbl.config(
#                     text=f"ID '{uid}' not found — check attendance.log for details", fg=RED)
#                 self._set_buttons(tk.DISABLED, tk.DISABLED)
#                 self._set_status(f"Worker ID {uid} not found — see log", RED, RED_DIM, RED)
#                 self._set_avatar(None, RED_DIM)
#                 self.log(f"Worker ID {uid} lookup failed — check attendance.log", "err")
#             else:
#                 name   = worker.get("Full_Name", "N/A")
#                 status = get_worker_status(uid)
#                 self.name_lbl.config(text=name, fg=WHITE)
#                 ci_time_hint = ""
#                 if status in ("checked_in", "done"):
#                     lk  = load_lock()
#                     rec = (lk.get("checked_in", {}).get(str(uid)) or
#                            lk.get("checked_out", {}).get(str(uid)))
#                     if isinstance(rec, dict):
#                         raw = rec.get("time", "") or rec.get("checkin_time", "")
#                         try:
#                             ci_time_hint = datetime.strptime(
#                                 raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M")
#                         except Exception:
#                             ci_time_hint = raw[-5:] if len(raw) >= 5 else raw
#                 hints = {
#                     "checked_in": (
#                         f"Checked in at {ci_time_hint} — use Check-Out"
#                         if ci_time_hint else "Checked in today — use Check-Out", ORANGE),
#                     "done": (
#                         f"Attendance complete — checked in at {ci_time_hint}"
#                         if ci_time_hint else "Attendance complete for today", RED),
#                     "none": ("Not yet checked in today", TEXT2),
#                 }
#                 htxt, hcol = hints.get(status, ("", TEXT2))
#                 self.hint_lbl.config(text=htxt, fg=hcol)
#                 self._apply_status(status, name, ci_time=ci_time_hint)
#         self.root.after(0, _upd)

#     def _on_enter(self, _=None):
#         uid = self.user_entry.get().strip()
#         if not uid or self._busy: return
#         s = get_worker_status(uid)
#         if s == "none":       self._trigger("checkin")
#         elif s == "checked_in": self._trigger("checkout")

#     # ------ PROCESS ------
#     def _trigger(self, action: str):
#         if self._busy: return
#         uid = self.user_entry.get().strip()
#         if not uid: return
#         self._busy = True
#         self._set_buttons(tk.DISABLED, tk.DISABLED)
#         verb = "CHECK IN" if action == "checkin" else "CHECK OUT"
#         self._set_status(f"Scanning fingerprint for {verb}…", ORANGE, ORANGE_DIM, ORANGE)
#         self.root.after(0, self._scan_start)
#         threading.Thread(target=self._process, args=(uid, action), daemon=True).start()

#     def _process(self, uid: str, action: str):
#         is_open = False; success = False; msg = ""; full_name = uid
#         try:
#             self.log(f"{'─'*16} {action.upper()} · ID {uid} {'─'*16}", "div")

#             if zk.GetDeviceCount() == 0:
#                 self.log("Scanner not connected", "err")
#                 self._gui(lambda: self._scan_err("NO DEVICE"))
#                 self._gui(lambda: self._show_flash(
#                     "⚠", "Scanner Not Connected",
#                     "Connect the fingerprint device and try again.", "", "#6d28d9"))
#                 return

#             zk.OpenDevice(0); is_open = True
#             self.log("Waiting for fingerprint…", "info")
#             capture = None
#             for _ in range(150):
#                 capture = zk.AcquireFingerprint()
#                 if capture: break
#                 time.sleep(0.2)

#             if not capture:
#                 self.log("Scan timed out", "err")
#                 self._gui(lambda: self._scan_err("TIMEOUT"))
#                 self._gui(lambda: self._show_flash(
#                     "⏱", "Scan Timeout", "No fingerprint detected.", "", "#92400e"))
#                 return

#             self._gui(self._scan_ok)
#             self.log("Fingerprint captured ✔", "ok")

#             _wcache_invalidate(uid)
#             worker = find_worker(uid, force_refresh=True)
#             if not worker:
#                 self.log(f"ID {uid} not found in Zoho — check attendance.log", "err")
#                 self._gui(lambda: self._scan_err("NOT FOUND"))
#                 self._gui(lambda: self._show_flash(
#                     "✗", "Worker Not Found",
#                     f"ID {uid} does not exist.\nCheck attendance.log for diagnostics.",
#                     "", RED_DIM))
#                 return

#             full_name = worker.get("Full_Name", uid)
#             self.log(f"Identity: {full_name}", "ok")

#             status = get_worker_status(uid)

#             if status == "done":
#                 self.log("Already complete", "warn")
#                 self._gui(lambda: self._show_flash(
#                     "🔒", "Already Complete", full_name, "Done for today.", "#1e0a40"))
#                 self.root.after(2600, lambda: self._apply_status("done", full_name))
#                 return

#             if status == "checked_in" and action == "checkin":
#                 _ci_rec = load_lock().get("checked_in", {}).get(str(uid), {})
#                 _ci_raw = _ci_rec.get("time", "") if isinstance(_ci_rec, dict) else ""
#                 try:
#                     _ci_t = datetime.strptime(_ci_raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M")
#                 except Exception:
#                     _ci_t = _ci_raw[-5:] if len(_ci_raw) >= 5 else _ci_raw
#                 _ci_msg = f"Checked in at {_ci_t}" if _ci_t else "Use Check-Out instead."
#                 self.log(f"Already checked IN at {_ci_t}", "warn")
#                 self._gui(lambda: self._show_flash(
#                     "↩", "Already Checked In", full_name, _ci_msg, "#3d1f00"))
#                 self.root.after(2600, lambda: self._apply_status(
#                     "checked_in", full_name, ci_time=_ci_t))
#                 return

#             if status == "none" and action == "checkout":
#                 self.log("Not checked IN yet", "warn")
#                 self._gui(lambda: self._show_flash(
#                     "⚠", "Not Checked In", full_name, "Check IN first.", "#1e0a40"))
#                 self.root.after(2600, lambda: self._apply_status("none", full_name))
#                 return

#             self.log(f"Posting {action.upper()} to Zoho…", "info")
#             pa  = worker.get("Projects_Assigned")
#             pid = pa.get("ID") if isinstance(pa, dict) else DEFAULT_PROJECT_ID
#             success, msg = log_attendance(
#                 worker["ID"], uid, pid, full_name, action, self.log)

#             tag = "ok" if success else "err"
#             for line in msg.splitlines():
#                 if line.strip():
#                     ltag = tag
#                     if "late"     in line.lower(): ltag = "late"
#                     if "overtime" in line.lower(): ltag = "ot"
#                     if "early"    in line.lower(): ltag = "early"
#                     self.log(line.strip(), ltag)

#             if success:
#                 verb      = "Checked IN" if action == "checkin" else "Checked OUT"
#                 sub       = datetime.now().strftime("Time: %H:%M:%S · %A, %d %B %Y")
#                 extra     = ""
#                 flash_col = "#1d4ed8"

#                 if action == "checkin" and is_late(datetime.now()):
#                     extra     = f"⚠ Late arrival — {late_by_str(datetime.now())}"
#                     flash_col = "#92400e"

#                 if action == "checkout":
#                     lock2  = load_lock()
#                     co     = lock2.get("checked_out", {}).get(str(uid), {})
#                     ot     = co.get("overtime_hours", 0) if isinstance(co, dict) else 0
#                     now_   = datetime.now()
#                     checkin_raw = co.get("checkin_time", "") if isinstance(co, dict) else ""
#                     try:
#                         ci_dt  = datetime.strptime(checkin_raw, "%d-%b-%Y %H:%M:%S")
#                         ci_disp = ci_dt.strftime("%H:%M:%S")
#                     except Exception:
#                         ci_disp = (checkin_raw[-8:] if len(checkin_raw) >= 8
#                                    else checkin_raw or "—")
#                     co_disp = now_.strftime("%H:%M:%S")
#                     sub  = (f"IN {ci_disp} → OUT {co_disp}"
#                             f"\n{now_.strftime('%A, %d %B %Y')}")
#                     if ot > 0:
#                         extra = f"⏱ Overtime: {int(ot)}h {int((ot%1)*60)}m"

#                 ev_tag = "in" if action == "checkin" else "out"
#                 _v, _s, _e, _fc = verb, sub, extra, flash_col
#                 self._gui(lambda: self._add_event(_v, full_name, ev_tag))
#                 self._gui(self._tick_stats)
#                 self._gui(lambda: self._show_flash(
#                     "✔", f"{_v} — {full_name}", _s, _e, _fc))
#             else:
#                 _m = msg.splitlines()[0][:80] if msg else "Unknown error"
#                 self._gui(lambda: self._scan_err("ERROR"))
#                 self._gui(lambda: self._show_flash("✗", "Action Failed", _m, "", RED_DIM))

#         except Exception as exc:
#             _log.exception(f"_process error: {exc}")
#             self.log(f"Unexpected error: {exc}", "err")
#         finally:
#             if is_open:
#                 try: zk.CloseDevice()
#                 except Exception: pass
#             self._busy = False
#             self.root.after(2600, self._scan_reset)
#             self.root.after(2600, lambda: self._reset_ui(clear_log=success))

#     def _reset_ui(self, clear_log=False):
#         self.user_entry.delete(0, tk.END)
#         self.name_lbl.config(text="—", fg=MUTED)
#         self.hint_lbl.config(text="Enter a Worker ID above", fg=MUTED)
#         self._set_avatar(None, BORDER)
#         self._set_buttons(tk.DISABLED, tk.DISABLED)
#         self._set_status("Awaiting Worker ID", ACCENT, ACCENT_DIM, ACCENT)
#         if clear_log:
#             self._clear_log()
#         self.log("Ready for next worker.", "div")
#         self.user_entry.focus_set()

#     def _soft_reset(self):
#         self.name_lbl.config(text="—", fg=MUTED)
#         self.hint_lbl.config(text="Enter a Worker ID above", fg=MUTED)
#         self._set_avatar(None, BORDER)
#         self._set_buttons(tk.DISABLED, tk.DISABLED)
#         self._set_status("Awaiting Worker ID", ACCENT, ACCENT_DIM, ACCENT)

#     def _on_close(self):
#         try: zk.Terminate()
#         except Exception: pass
#         self.root.destroy()

# # ===========================================================
# if __name__ == "__main__":
#     root = tk.Tk()
#     FingerprintGUI(root)
#     root.mainloop()

















# import os, time, json, csv, requests, threading, math, queue, logging
# from datetime import datetime, timedelta
# from dotenv import load_dotenv
# from pyzkfp import ZKFP2
# import tkinter as tk
# from tkinter import ttk, messagebox
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry

# # ===========================================================
# # LOGGING
# # ===========================================================
# logging.basicConfig(
#     filename="attendance.log",
#     level=logging.INFO,
#     format="%(asctime)s [%(levelname)s] %(message)s",
#     datefmt="%Y-%m-%d %H:%M:%S")
# _log = logging.getLogger(__name__)

# # ===========================================================
# # CONFIGURATION
# # ===========================================================
# load_dotenv()

# ZOHO_DOMAIN    = os.getenv("ZOHO_DOMAIN",    "zoho.com")
# APP_OWNER      = os.getenv("APP_OWNER",      "wavemarkpropertieslimited")
# APP_NAME       = os.getenv("APP_NAME",       "real-estate-wages-system")
# CLIENT_ID      = os.getenv("ZOHO_CLIENT_ID")
# CLIENT_SECRET  = os.getenv("ZOHO_CLIENT_SECRET")
# REFRESH_TOKEN  = os.getenv("ZOHO_REFRESH_TOKEN")

# WORKERS_REPORT    = "All_Workers"
# ATTENDANCE_FORM   = "Daily_Attendance"
# ATTENDANCE_REPORT = "Daily_Attendance_Report"
# DEFAULT_PROJECT_ID = "4838902000000391493"

# TOKEN_CACHE  = {"token": None, "expires_at": 0}
# _TOKEN_LOCK  = threading.Lock()

# # Derive the TLD from ZOHO_DOMAIN so EU/IN accounts work too
# _ZOHO_TLD   = ZOHO_DOMAIN.split(".")[-1]          # "com", "eu", "in" …
# ACCOUNTS_URL = f"https://accounts.zoho.{_ZOHO_TLD}"
# API_DOMAIN   = f"https://creator.zoho.{_ZOHO_TLD}/api/v2"

# CHECKIN_LOCK_FILE = "checkin_today.json"

# # ── Shift policy ─────────────────────────────────────────
# SHIFT_START_H   = 7
# SHIFT_START_M   = 00
# SHIFT_HOURS     = 8
# GRACE_MINUTES   = 60
# EARLY_CHECKOUT_H = 17
# EARLY_CHECKOUT_M = 0
# AUTO_CHECKOUT_H  = 19
# AUTO_CHECKOUT_M  = 0

# # ── Performance constants ────────────────────────────────
# WORKER_CACHE_TTL = 3600
# MAX_POOL_SIZE    = 20
# ZOHO_TIMEOUT     = 30
# STATS_REFRESH_MS = 8000
# LOG_MAX_LINES    = 500
# LOCK_WRITE_LOCK  = threading.Lock()

# # ===========================================================
# # GLOBAL SDK
# # ===========================================================
# zk = ZKFP2()
# try:
#     zk.Init()
# except Exception as e:
#     _log.error(f"Fingerprint SDK Init Error: {e}")
#     print(f"Fingerprint SDK Init Error: {e}")

# # ===========================================================
# # HTTP SESSION — connection pooling + automatic retry
# # ===========================================================
# def _make_session():
#     s = requests.Session()
#     retry = Retry(
#         total=3, backoff_factor=1,
#         status_forcelist=[429, 500, 502, 503, 504],
#         allowed_methods=["GET", "POST", "PATCH"])
#     adapter = HTTPAdapter(
#         max_retries=retry,
#         pool_connections=MAX_POOL_SIZE,
#         pool_maxsize=MAX_POOL_SIZE,
#         pool_block=False)
#     s.mount("https://", adapter)
#     s.mount("http://",  adapter)
#     return s

# _SESSION = _make_session()

# def zoho_request(method, url, retries=3, **kwargs):
#     kwargs.setdefault("timeout", ZOHO_TIMEOUT)
#     for attempt in range(1, retries + 1):
#         try:
#             return _SESSION.request(method, url, **kwargs)
#         except (requests.exceptions.Timeout,
#                 requests.exceptions.ConnectionError, OSError) as exc:
#             _log.warning(f"zoho_request attempt {attempt}: {exc}")
#             if attempt < retries:
#                 time.sleep(min(2 ** attempt, 8))
#     return None


# # ===========================================================
# # AUTHENTICATION — thread-safe token refresh
# # ===========================================================
# def _validate_env():
#     """Check that required .env variables are present before attempting auth."""
#     missing = [k for k, v in {
#         "ZOHO_CLIENT_ID":     CLIENT_ID,
#         "ZOHO_CLIENT_SECRET": CLIENT_SECRET,
#         "ZOHO_REFRESH_TOKEN": REFRESH_TOKEN,
#     }.items() if not v]
#     if missing:
#         _log.error(f"Missing .env variables: {', '.join(missing)}")
#         return False
#     return True

# def get_access_token():
#     if not _validate_env():
#         return None

#     now = time.time()
#     with _TOKEN_LOCK:
#         if TOKEN_CACHE["token"] and now < TOKEN_CACHE["expires_at"] - 120:
#             return TOKEN_CACHE["token"]
#         TOKEN_CACHE["token"] = None

#     url = f"{ACCOUNTS_URL}/oauth/v2/token"
#     data = {
#         "refresh_token": REFRESH_TOKEN,
#         "client_id":     CLIENT_ID,
#         "client_secret": CLIENT_SECRET,
#         "grant_type":    "refresh_token",
#     }

#     for attempt in range(3):
#         r = zoho_request("POST", url, data=data, retries=1)
#         if r is None:
#             _log.error(f"Token refresh attempt {attempt+1}: no response / timeout")
#             time.sleep(3)
#             continue

#         if r.status_code == 200:
#             res = r.json()
#             if "access_token" in res:
#                 with _TOKEN_LOCK:
#                     TOKEN_CACHE["token"]      = res["access_token"]
#                     TOKEN_CACHE["expires_at"] = now + int(res.get("expires_in", 3600))
#                 _log.info("Zoho token refreshed OK")
#                 return TOKEN_CACHE["token"]
#             else:
#                 err = res.get("error", "unknown")
#                 _log.error(f"Token refresh attempt {attempt+1} HTTP 200 but error={err!r}. "
#                            f"Full response: {res}")
#                 if err == "invalid_client":
#                     _log.error(
#                         ">>> invalid_client: Your CLIENT_ID or CLIENT_SECRET is wrong, "
#                         "or the OAuth client was deleted/deauthorised in Zoho API Console "
#                         "(https://api-console.zoho.com). Re-generate credentials and update .env.")
#                     return None          # no point retrying
#                 if err in ("invalid_code", "access_denied"):
#                     _log.error(
#                         ">>> Refresh token revoked or expired. Re-authorise the app and "
#                         "generate a new ZOHO_REFRESH_TOKEN.")
#                     return None
#         else:
#             _log.error(f"Token refresh attempt {attempt+1} HTTP {r.status_code}: {r.text[:300]}")

#         time.sleep(3)

#     _log.error("Failed to refresh Zoho token after 3 attempts — "
#                "check REFRESH_TOKEN / CLIENT_ID / CLIENT_SECRET in .env")
#     return None

# def auth_headers():
#     token = get_access_token()
#     if not token:
#         _log.error("auth_headers: no token available — all Zoho calls will fail")
#         return {}
#     return {"Authorization": f"Zoho-oauthtoken {token}"}

# # ===========================================================
# # LOCAL STATE — in-memory cache + safe file persistence
# # ===========================================================
# _LOCK_MEM: dict = {}
# _LOCK_MEM_DATE: str = ""

# def load_lock() -> dict:
#     global _LOCK_MEM, _LOCK_MEM_DATE
#     today = datetime.now().strftime("%Y-%m-%d")
#     if _LOCK_MEM_DATE == today and _LOCK_MEM:
#         return _LOCK_MEM

#     if os.path.exists(CHECKIN_LOCK_FILE):
#         try:
#             with open(CHECKIN_LOCK_FILE, "r", encoding="utf-8") as f:
#                 data = json.load(f)
#             if data.get("date") == today:
#                 for key in ("checked_in", "checked_out"):
#                     if not isinstance(data.get(key), dict):
#                         data[key] = {}
#                     data[key] = {k: v for k, v in data[key].items()
#                                  if isinstance(v, dict)}
#                 _LOCK_MEM      = data
#                 _LOCK_MEM_DATE = today
#                 return _LOCK_MEM
#         except Exception as exc:
#             _log.warning(f"load_lock read error: {exc}")

#     fresh = {"date": today, "checked_in": {}, "checked_out": {}}
#     _LOCK_MEM      = fresh
#     _LOCK_MEM_DATE = today
#     save_lock(fresh)
#     return _LOCK_MEM

# def save_lock(data: dict):
#     global _LOCK_MEM, _LOCK_MEM_DATE
#     _LOCK_MEM      = data
#     _LOCK_MEM_DATE = data.get("date", "")
#     tmp = CHECKIN_LOCK_FILE + ".tmp"
#     with LOCK_WRITE_LOCK:
#         try:
#             with open(tmp, "w", encoding="utf-8") as f:
#                 json.dump(data, f, indent=2)
#             os.replace(tmp, CHECKIN_LOCK_FILE)
#         except Exception as exc:
#             _log.error(f"save_lock error: {exc}")

# def get_worker_status(zk_id: str) -> str:
#     lock = load_lock()
#     key  = str(zk_id)
#     if key in lock["checked_out"]:  return "done"
#     if key in lock["checked_in"]:   return "checked_in"
#     return "none"

# def count_early_checkouts(lock=None) -> int:
#     if lock is None:
#         lock = load_lock()
#     now         = datetime.now()
#     early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                               second=0, microsecond=0)
#     count = 0
#     for info in lock.get("checked_out", {}).values():
#         if not isinstance(info, dict):
#             continue
#         try:
#             co_dt = datetime.strptime(info.get("time", ""), "%H:%M:%S").replace(
#                 year=now.year, month=now.month, day=now.day)
#             if co_dt < early_limit:
#                 count += 1
#         except Exception:
#             pass
#     return count

# # ===========================================================
# # WORKER CACHE — TTL-based, evicts oldest when full
# # ===========================================================
# _WORKER_STORE: dict = {}
# _WORKER_LOCK  = threading.Lock()

# def _wcache_get(uid: str):
#     with _WORKER_LOCK:
#         e = _WORKER_STORE.get(str(uid))
#         if e and (time.time() - e["ts"]) < WORKER_CACHE_TTL:
#             return e["worker"]
#     return None

# def _wcache_set(uid: str, worker: dict):
#     with _WORKER_LOCK:
#         if len(_WORKER_STORE) >= 2000:
#             oldest = sorted(_WORKER_STORE, key=lambda k: _WORKER_STORE[k]["ts"])
#             for old_k in oldest[:200]:
#                 del _WORKER_STORE[old_k]
#         _WORKER_STORE[str(uid)] = {"worker": worker, "ts": time.time()}

# def _wcache_invalidate(uid: str):
#     with _WORKER_LOCK:
#         _WORKER_STORE.pop(str(uid), None)

# # ===========================================================
# # SHIFT HELPERS
# # ===========================================================
# def is_late(checkin_dt: datetime) -> bool:
#     cutoff = checkin_dt.replace(
#         hour=SHIFT_START_H, minute=SHIFT_START_M, second=0, microsecond=0
#     ) + timedelta(minutes=GRACE_MINUTES)
#     return checkin_dt > cutoff

# def late_by_str(checkin_dt: datetime) -> str:
#     shift_start = checkin_dt.replace(
#         hour=SHIFT_START_H, minute=SHIFT_START_M, second=0, microsecond=0)
#     delta = max((checkin_dt - shift_start).total_seconds(), 0)
#     mins  = int(delta // 60)
#     return f"{mins} min late" if mins else "on time"

# def overtime_hours(total_hours: float) -> float:
#     return max(round(total_hours - SHIFT_HOURS, 4), 0)

# # ===========================================================
# # ZOHO API
# # ===========================================================
# def find_worker(zk_user_id, force_refresh: bool = False):
#     """
#     Look up a worker in Zoho by their ZKTeco User ID.
#     Tries multiple criteria formats before falling back to a full-list scan.
#     """
#     uid = str(zk_user_id).strip()

#     if not force_refresh:
#         cached = _wcache_get(uid)
#         if cached:
#             _log.debug(f"find_worker({uid}): cache hit")
#             return cached

#     hdrs = auth_headers()
#     if not hdrs:
#         _log.error(f"find_worker({uid}): aborting — no valid Zoho token. "
#                    "Check REFRESH_TOKEN / CLIENT_ID / CLIENT_SECRET in .env")
#         return None

#     url = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/report/{WORKERS_REPORT}"

#     try:
#         int_id = int(uid)
#     except ValueError:
#         int_id = None

#     criteria_attempts = []
#     if int_id is not None:
#         criteria_attempts += [
#             f"(ZKTeco_User_ID2 == {int_id})",
#             f'(ZKTeco_User_ID2 == "{int_id}")',
#             f"(Worker_ID == {int_id})",
#             f'(Worker_ID == "{int_id}")',
#         ]
#     criteria_attempts += [
#         f'(ZKTeco_User_ID2 == "{uid}")',
#         f'(Worker_ID == "{uid}")',
#     ]

#     for criteria in criteria_attempts:
#         _log.info(f"find_worker({uid}): trying criteria={criteria!r}")
#         r = zoho_request("GET", url, headers=hdrs, params={"criteria": criteria})
#         if not r:
#             _log.error(f"find_worker({uid}): request timed out on criteria={criteria!r}")
#             continue
#         if r.status_code == 401:
#             _log.warning(f"find_worker: HTTP 401 for criteria: {criteria}")
#             with _TOKEN_LOCK:
#                 TOKEN_CACHE["token"]      = None
#                 TOKEN_CACHE["expires_at"] = 0
#             hdrs = auth_headers()         # try refreshing once
#             if not hdrs:
#                 _log.error(f"find_worker({uid}): token refresh failed, aborting")
#                 return None
#             r = zoho_request("GET", url, headers=hdrs, params={"criteria": criteria})
#             if not r or r.status_code != 200:
#                 _log.warning(f"find_worker: criteria failed for ID '{uid}', trying full fetch…")
#                 continue
#         if r.status_code != 200:
#             _log.error(f"find_worker({uid}): HTTP {r.status_code} — {r.text[:300]}")
#             continue

#         data = r.json().get("data", [])
#         if data:
#             _log.info(f"find_worker({uid}): found via criteria={criteria!r}")
#             _wcache_set(uid, data[0])
#             return data[0]

#     # ── Last resort: fetch ALL workers and match manually ──
#     _log.warning(f"find_worker({uid}): all criteria failed — attempting full worker scan")
#     r = zoho_request("GET", url, headers=hdrs)
#     if r and r.status_code == 200:
#         all_workers = r.json().get("data", [])
#         _log.info(f"find_worker({uid}): full scan returned {len(all_workers)} worker(s)")
#         for w in all_workers:
#             zk_val  = str(w.get("ZKTeco_User_ID2", "")).strip()
#             wid_val = str(w.get("Worker_ID",       "")).strip()
#             zk_val_clean  = zk_val.split(".")[0]
#             wid_val_clean = wid_val.split(".")[0]
#             if uid in (zk_val, wid_val, zk_val_clean, wid_val_clean):
#                 _log.info(f"find_worker({uid}): matched via full scan "
#                           f"(ZKTeco_User_ID2={zk_val!r}, Worker_ID={wid_val!r})")
#                 _wcache_set(uid, w)
#                 return w
#     else:
#         _log.error(f"find_worker({uid}): full scan HTTP "
#                    f"{r.status_code if r else 'timeout'}")

#     _log.error(f"find_worker({uid}): worker NOT found after all attempts. "
#                f"Verify ZKTeco_User_ID2 / Worker_ID field in Zoho for ID={uid}")
#     return None


# def search_workers_by_name(name_query: str) -> list:
#     """Search Zoho for workers whose Full_Name contains the query string."""
#     url  = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/report/{WORKERS_REPORT}"
#     hdrs = auth_headers()
#     if not hdrs:
#         _log.error("search_workers_by_name: no valid token — cannot search")
#         return []

#     q_lower = name_query.strip().lower()
#     results = []

#     # Try Zoho criteria-based search first
#     for criteria in [
#         f'(Full_Name contains "{name_query}")',
#         f'(Full_Name starts_with "{name_query}")',
#     ]:
#         try:
#             r = zoho_request("GET", url, headers=hdrs, params={"criteria": criteria})
#             if r and r.status_code == 200:
#                 data = r.json().get("data", [])
#                 if data:
#                     _log.info(f"search_workers_by_name: found {len(data)} via criteria={criteria!r}")
#                     return data
#         except Exception as exc:
#             _log.warning(f"search_workers_by_name criteria error: {exc}")

#     # Fallback: fetch ALL workers and filter locally
#     try:
#         _log.info("search_workers_by_name: falling back to full worker scan")
#         r = zoho_request("GET", url, headers=hdrs)
#         if r and r.status_code == 200:
#             all_workers = r.json().get("data", [])
#             _log.info(f"search_workers_by_name: full scan returned {len(all_workers)} workers")
#             results = [
#                 w for w in all_workers
#                 if q_lower in str(w.get("Full_Name", "")).lower()
#                 or q_lower in str(w.get("ZKTeco_User_ID2", "")).lower()
#                 or q_lower in str(w.get("Worker_ID", "")).lower()
#             ]
#         elif r:
#             _log.error(f"search_workers_by_name: full scan HTTP {r.status_code}: {r.text[:200]}")
#         else:
#             _log.error("search_workers_by_name: full scan timed out")
#     except Exception as exc:
#         _log.error(f"search_workers_by_name fallback error: {exc}")

#     return results


# def _extract_zoho_id(res_json):
#     data = res_json.get("data")
#     if isinstance(data, dict):
#         return data.get("ID") or data.get("id")
#     if isinstance(data, list) and data:
#         return data[0].get("ID") or data[0].get("id")
#     return res_json.get("ID") or res_json.get("id")


# def _find_record_in_zoho(worker_id, today_display, today_iso, hdrs, _log_fn=None):
#     def dbg(msg):
#         _log.debug(f"[ZOHO SEARCH] {msg}")
#         if _log_fn:
#             _log_fn(f"[search] {msg}", "warn")

#     report_url   = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/report/{ATTENDANCE_REPORT}"
#     criteria_list = [
#         f'(Worker_Name == "{worker_id}" && Date == "{today_display}")',
#         f'(Worker_Name == "{worker_id}" && Date == "{today_iso}")',
#         f'(Worker_ID_Lookup == "{worker_id}" && Date == "{today_display}")',
#         f'(Worker_ID_Lookup == "{worker_id}" && Date == "{today_iso}")',
#         f'(Worker_Name == "{worker_id}")',
#         f'(Worker_ID_Lookup == "{worker_id}")',
#     ]

#     for crit in criteria_list:
#         r = zoho_request("GET", report_url, headers=hdrs, params={"criteria": crit})
#         if not r or r.status_code != 200:
#             continue
#         recs = r.json().get("data", [])
#         if not recs:
#             continue
#         for rec in recs:
#             d = str(rec.get("Date", rec.get("Date_field", ""))).strip()
#             if d in (today_display, today_iso):
#                 return rec["ID"]
#         if len(recs) == 1:
#             return recs[0]["ID"]

#     for date_val in (today_display, today_iso):
#         r = zoho_request("GET", report_url, headers=hdrs,
#                          params={"criteria": f'(Date == "{date_val}")'})
#         if not r or r.status_code != 200:
#             continue
#         for rec in r.json().get("data", []):
#             for field in ("Worker_Name", "Worker_ID_Lookup", "Worker",
#                           "Worker_Name.ID", "Worker_ID"):
#                 val = rec.get(field)
#                 if isinstance(val, dict):
#                     val = val.get("ID") or val.get("id") or val.get("display_value", "")
#                 if str(val).strip() == str(worker_id).strip():
#                     return rec["ID"]

#     dbg("All strategies exhausted — not found.")
#     return None

# # ===========================================================
# # ATTENDANCE LOGIC
# # ===========================================================
# def log_attendance(worker_id, zk_id, project_id, full_name, action, _log_fn=None):
#     now     = datetime.now()
#     zk_key  = str(zk_id)
#     today_display = now.strftime("%d-%b-%Y")
#     today_iso     = now.strftime("%Y-%m-%d")

#     if action == "checkin":
#         form_url     = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/form/{ATTENDANCE_FORM}"
#         checkin_time = now.strftime("%d-%b-%Y %H:%M:%S")
#         hdrs         = auth_headers()
#         if not hdrs:
#             return False, "Could not refresh Zoho token."

#         worker_late = is_late(now)
#         late_note   = late_by_str(now)
#         late_mins   = int(max(
#             (now - now.replace(hour=SHIFT_START_H, minute=SHIFT_START_M,
#                                second=0, microsecond=0)).total_seconds() // 60, 0
#         )) if worker_late else 0

#         payload = {"data": {
#             "Worker_Name":      worker_id,
#             "Projects":         project_id,
#             "Date":             today_display,
#             "First_In":         checkin_time,
#             "Worker_Full_Name": full_name,
#             "Is_Late":          "true" if worker_late else "false",
#             "Late_By_Minutes":  late_mins,
#         }}

#         r = zoho_request("POST", form_url, headers=hdrs, json=payload)
#         if r and r.status_code in (200, 201):
#             res          = r.json()
#             zoho_rec_id  = _extract_zoho_id(res)
#             if not zoho_rec_id:
#                 zoho_rec_id = _find_record_in_zoho(
#                     worker_id, today_display, today_iso, auth_headers(), _log_fn)

#             lock = load_lock()
#             lock["checked_in"][zk_key] = {
#                 "time":      checkin_time,
#                 "zoho_id":   zoho_rec_id,
#                 "worker_id": worker_id,
#                 "name":      full_name,
#                 "is_late":   worker_late,
#                 "late_note": late_note,
#             }
#             save_lock(lock)
#             _log.info(f"CHECKIN OK: {full_name} late={worker_late}")
#             status_line = f"⚠ {late_note}" if worker_late else "✓ On time"
#             return True, (f"✅ {full_name} checked IN at {now.strftime('%H:%M')}\n"
#                           f"   {status_line}")

#         err = r.text[:200] if r else "Timeout"
#         _log.error(f"CHECKIN FAIL: {full_name}: {err}")
#         return False, f"Check-in failed: {err}"

#     elif action == "checkout":
#         lock = load_lock()
#         info = lock["checked_in"].get(zk_key)
#         if not info:
#             return False, "No check-in record found for today."

#         hdrs = auth_headers()
#         if not hdrs:
#             return False, "Could not refresh Zoho token."

#         att_record_id  = info.get("zoho_id")
#         stored_worker  = info.get("worker_id", worker_id)

#         def dbg(msg):
#             _log.debug(f"[CHECKOUT] {msg}")
#             if _log_fn:
#                 _log_fn(f"[checkout] {msg}", "warn")

#         if att_record_id:
#             direct_url = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
#                           f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
#             r_chk = zoho_request("GET", direct_url, headers=hdrs)
#             if not (r_chk and r_chk.status_code == 200):
#                 dbg("stored ID invalid — searching...")
#                 att_record_id = None

#         if not att_record_id:
#             att_record_id = _find_record_in_zoho(
#                 stored_worker, today_display, today_iso, hdrs, _log_fn)
#             if att_record_id:
#                 lock["checked_in"][zk_key]["zoho_id"] = att_record_id
#                 save_lock(lock)

#         if not att_record_id:
#             form_index_url = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/form/{ATTENDANCE_FORM}"
#             for date_val in (today_display, today_iso):
#                 crit = f'(Worker_Name == "{stored_worker}" && Date == "{date_val}")'
#                 r_f  = zoho_request("GET", form_index_url, headers=hdrs,
#                                     params={"criteria": crit})
#                 if r_f and r_f.status_code == 200:
#                     frecs = r_f.json().get("data", [])
#                     if frecs:
#                         att_record_id = frecs[0].get("ID")
#                         lock["checked_in"][zk_key]["zoho_id"] = att_record_id
#                         save_lock(lock)
#                         break

#         if not att_record_id:
#             return False, (f"Could not locate attendance record in Zoho.\n"
#                            f"Worker: {full_name}  Date: {today_display}\n"
#                            "Check the log for [checkout] diagnostics.")

#         try:
#             dt_in = datetime.strptime(info.get("time", ""), "%d-%b-%Y %H:%M:%S")
#         except Exception:
#             dt_in = now

#         total_hours = max((now - dt_in).total_seconds() / 3600, 0.01)
#         ot_hours    = overtime_hours(total_hours)
#         total_str   = f"{int(total_hours)}h {int((total_hours % 1) * 60)}m"
#         ot_str      = f"{int(ot_hours)}h {int((ot_hours % 1) * 60)}m" if ot_hours else "None"
#         total_hours_rounded = round(total_hours, 2)
#         ot_hours_rounded    = round(ot_hours, 2)

#         update_url = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
#                       f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
#         r_u = zoho_request("PATCH", update_url, headers=hdrs, json={"data": {
#             "Last_Out":       now.strftime("%d-%b-%Y %H:%M:%S"),
#             "Total_Hours":    total_hours_rounded,
#             "Overtime_Hours": ot_hours_rounded,
#         }})

#         http_code = r_u.status_code if r_u else "timeout"
#         body_raw  = r_u.text[:300]  if r_u else "No response"

#         if r_u and r_u.status_code == 200:
#             body = r_u.json()
#             code = body.get("code")
#             if code == 3000:
#                 checkout_hms = now.strftime("%H:%M:%S")
#                 lock["checked_in"].pop(zk_key, None)
#                 lock["checked_out"][zk_key] = {
#                     "time":           checkout_hms,
#                     "name":           full_name,
#                     "total_hours":    total_hours_rounded,
#                     "overtime_hours": ot_hours_rounded,
#                     "is_late":        info.get("is_late", False),
#                     "late_note":      info.get("late_note", ""),
#                     "checkin_time":   info.get("time", ""),
#                 }
#                 save_lock(lock)
#                 _log.info(f"CHECKOUT OK: {full_name} hours={total_hours_rounded}")
#                 ot_line     = f"   Overtime: {ot_str}" if ot_hours else ""
#                 early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                                           second=0, microsecond=0)
#                 early_note  = (f"\n   ⚠ Early checkout "
#                                f"(before {EARLY_CHECKOUT_H:02d}:{EARLY_CHECKOUT_M:02d})"
#                                if now < early_limit else "")
#                 return True, (f"🚪 {full_name} checked OUT at {now.strftime('%H:%M')}\n"
#                               f"   Total time: {total_str}\n{ot_line}{early_note}")

#             errors = body.get("error", body.get("message", ""))
#             return False, (f"Zoho rejected update (code {code}).\nError: {errors}\n"
#                            f"Worker: {full_name}  Hours: {total_hours_rounded}")

#         _log.error(f"CHECKOUT FAIL: {full_name} HTTP {http_code}: {body_raw}")
#         return False, f"Check-out PATCH failed (HTTP {http_code}): {body_raw}"

#     return False, "Unknown action."

# # ===========================================================
# # AUTO-CHECKOUT — concurrent batch processing
# # ===========================================================
# def run_auto_checkout(gui_log_fn=None, done_cb=None):
#     now           = datetime.now()
#     today_display = now.strftime("%d-%b-%Y")
#     today_iso     = now.strftime("%Y-%m-%d")
#     checkout_ts   = now.strftime("%d-%b-%Y %H:%M:%S")
#     checkout_hms  = now.strftime("%H:%M:%S")

#     lock    = load_lock()
#     pending = {k: v for k, v in lock.get("checked_in", {}).items()
#                if isinstance(v, dict)}

#     if not pending:
#         if done_cb:
#             done_cb([], [])
#         return

#     def info(msg):
#         _log.info(msg)
#         if gui_log_fn:
#             gui_log_fn(msg, "warn")

#     info(f"AUTO-CHECKOUT: {len(pending)} worker(s) at {now.strftime('%H:%M')}")

#     success_names, fail_names = [], []
#     result_lock = threading.Lock()
#     sem         = threading.Semaphore(8)

#     def _checkout_one(zk_key, winfo):
#         with sem:
#             full_name = winfo.get("name",      zk_key)
#             worker_id = winfo.get("worker_id", zk_key)
#             att_record_id = winfo.get("zoho_id")
#             hdrs = auth_headers()

#             if att_record_id:
#                 du = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
#                       f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
#                 rc = zoho_request("GET", du, headers=hdrs)
#                 if not (rc and rc.status_code == 200):
#                     att_record_id = None

#             if not att_record_id:
#                 att_record_id = _find_record_in_zoho(
#                     worker_id, today_display, today_iso, hdrs)

#             if not att_record_id:
#                 info(f"  SKIP {full_name}: no Zoho record")
#                 with result_lock:
#                     fail_names.append(full_name)
#                 return

#             try:
#                 dt_in = datetime.strptime(winfo.get("time", ""), "%d-%b-%Y %H:%M:%S")
#             except Exception:
#                 dt_in = now

#             total_h = max((now - dt_in).total_seconds() / 3600, 0.01)
#             ot_h    = overtime_hours(total_h)

#             uu = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
#                   f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
#             ru = zoho_request("PATCH", uu, headers=hdrs, json={"data": {
#                 "Last_Out":       checkout_ts,
#                 "Total_Hours":    round(total_h, 2),
#                 "Overtime_Hours": round(ot_h, 2),
#             }})

#             if ru and ru.status_code == 200 and ru.json().get("code") == 3000:
#                 lk = load_lock()
#                 lk["checked_in"].pop(zk_key, None)
#                 lk["checked_out"][zk_key] = {
#                     "time":           checkout_hms,
#                     "name":           full_name,
#                     "total_hours":    round(total_h, 2),
#                     "overtime_hours": round(ot_h, 2),
#                     "is_late":        winfo.get("is_late", False),
#                     "late_note":      winfo.get("late_note", ""),
#                     "checkin_time":   winfo.get("time", ""),
#                     "auto_checkout":  True,
#                 }
#                 save_lock(lk)
#                 h_str = f"{int(total_h)}h {int((total_h % 1) * 60)}m"
#                 info(f"  OK {full_name} -- {h_str}")
#                 with result_lock:
#                     success_names.append(full_name)
#             else:
#                 code = ru.status_code if ru else "timeout"
#                 info(f"  FAIL {full_name} HTTP {code}")
#                 with result_lock:
#                     fail_names.append(full_name)

#     threads = [threading.Thread(target=_checkout_one, args=(k, v), daemon=True)
#                for k, v in pending.items()]
#     for t in threads: t.start()
#     for t in threads: t.join()

#     info(f"AUTO-CHECKOUT done: {len(success_names)} OK, {len(fail_names)} failed")
#     if done_cb:
#         done_cb(success_names, fail_names)

# # ===========================================================
# # DAILY SUMMARY EXPORT
# # ===========================================================
# def export_daily_summary():
#     lock     = load_lock()
#     today    = lock.get("date", datetime.now().strftime("%Y-%m-%d"))
#     filename = f"attendance_{today}.csv"
#     rows     = []
#     now      = datetime.now()
#     early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                               second=0, microsecond=0)

#     for zk_id, info in lock.get("checked_out", {}).items():
#         if not isinstance(info, dict):
#             continue
#         co_str   = info.get("time", "")
#         is_early = False
#         try:
#             co_dt    = datetime.strptime(co_str, "%H:%M:%S").replace(
#                 year=now.year, month=now.month, day=now.day)
#             is_early = co_dt < early_limit
#         except Exception:
#             pass
#         rows.append({
#             "ZK_ID":          zk_id,
#             "Name":           info.get("name", ""),
#             "Check-In":       info.get("checkin_time", ""),
#             "Check-Out":      co_str,
#             "Total Hours":    info.get("total_hours", ""),
#             "Overtime Hours": info.get("overtime_hours", 0),
#             "Late?":          "Yes" if info.get("is_late") else "No",
#             "Late Note":      info.get("late_note", ""),
#             "Early Checkout?":"Yes" if is_early else "No",
#             "Auto Checkout?": "Yes" if info.get("auto_checkout") else "No",
#             "Status":         "Complete",
#         })

#     for zk_id, info in lock.get("checked_in", {}).items():
#         if not isinstance(info, dict):
#             continue
#         rows.append({
#             "ZK_ID":          zk_id,
#             "Name":           info.get("name", ""),
#             "Check-In":       info.get("time", ""),
#             "Check-Out":      "---",
#             "Total Hours":    "---",
#             "Overtime Hours": "---",
#             "Late?":          "Yes" if info.get("is_late") else "No",
#             "Late Note":      info.get("late_note", ""),
#             "Early Checkout?":"---",
#             "Auto Checkout?": "---",
#             "Status":         "Still In",
#         })

#     if not rows:
#         return None

#     fieldnames = ["ZK_ID", "Name", "Check-In", "Check-Out", "Total Hours",
#                   "Overtime Hours", "Late?", "Late Note", "Early Checkout?",
#                   "Auto Checkout?", "Status"]
#     with open(filename, "w", newline="", encoding="utf-8") as f:
#         writer = csv.DictWriter(f, fieldnames=fieldnames)
#         writer.writeheader()
#         writer.writerows(rows)

#     _log.info(f"CSV exported: {filename} ({len(rows)} rows)")
#     return filename

# # ===========================================================
# # COLOUR PALETTE
# # ===========================================================
# BG      = "#07090f"; CARD    = "#0c1018"; CARD2   = "#10151f"
# BORDER  = "#1c2438"; BORDER2 = "#243048"
# ACCENT  = "#3b82f6"; ACCENT_DIM = "#172554"; ACCENT2 = "#60a5fa"
# GREEN   = "#10b981"; GREEN2  = "#34d399"; GREEN_DIM  = "#052e1c"
# RED     = "#f43f5e"; RED2    = "#fb7185"; RED_DIM    = "#4c0519"
# ORANGE  = "#f59e0b"; ORANGE2 = "#fbbf24"; ORANGE_DIM = "#3d1f00"
# CYAN2   = "#67e8f9"; CYAN_DIM = "#083344"
# TEXT    = "#e2e8f0"; TEXT2   = "#94a3b8"; MUTED   = "#3d4f69"
# WHITE   = "#ffffff"; GOLD    = "#f59e0b"; GOLD2   = "#fde68a"
# PURPLE  = "#a78bfa"; PURPLE_DIM = "#2e1065"
# TEAL    = "#2dd4bf"; TEAL_DIM   = "#042f2e"

# # ===========================================================
# # UI HELPERS
# # ===========================================================
# def _btn_hover(btn, bg_on, fg_on, bg_off, fg_off):
#     btn.bind("<Enter>", lambda _: btn.config(bg=bg_on,  fg=fg_on))
#     btn.bind("<Leave>", lambda _: btn.config(bg=bg_off, fg=fg_off))

# def _make_sep(parent, color=BORDER, height=1):
#     tk.Frame(parent, bg=color, height=height).pack(fill=tk.X)

# def _initials(name: str) -> str:
#     parts = name.strip().split()
#     if not parts:      return "??"
#     if len(parts) == 1: return parts[0][:2].upper()
#     return (parts[0][0] + parts[-1][0]).upper()

# # ===========================================================
# # FORGOTTEN ID DIALOG
# # ===========================================================
# class ForgottenIDDialog(tk.Toplevel):
#     def __init__(self, parent, on_select):
#         super().__init__(parent)
#         self.on_select  = on_select
#         self._results   = []
#         self._search_job = None
#         self.title("Find Worker by Name")
#         self.configure(bg=BG)
#         self.resizable(False, False)
#         self.grab_set()
#         self.focus_force()
#         W, H = 520, 460
#         sw, sh = parent.winfo_screenwidth(), parent.winfo_screenheight()
#         self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
#         self._build()
#         self.name_entry.focus_set()

#     def _build(self):
#         tk.Frame(self, bg=TEAL, height=3).pack(fill=tk.X)
#         hdr = tk.Frame(self, bg=CARD, padx=20, pady=14); hdr.pack(fill=tk.X)
#         tk.Label(hdr, text="🔍 FORGOTTEN ID LOOKUP",
#                  font=("Courier", 11, "bold"), bg=CARD, fg=TEAL).pack(anchor="w")
#         tk.Label(hdr, text="Type your name below — matching workers will appear instantly",
#                  font=("Courier", 8), bg=CARD, fg=TEXT2).pack(anchor="w", pady=(3, 0))
#         _make_sep(self, BORDER2)

#         sf = tk.Frame(self, bg=BG, padx=20, pady=14); sf.pack(fill=tk.X)
#         tk.Label(sf, text="NAME", font=("Courier", 8, "bold"),
#                  bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 5))
#         eb = tk.Frame(sf, bg=TEAL, padx=2, pady=2); eb.pack(fill=tk.X)
#         ei = tk.Frame(eb, bg=CARD2); ei.pack(fill=tk.X)
#         self._name_var = tk.StringVar()
#         self._name_var.trace_add("write", lambda *_: self._on_type())
#         self.name_entry = tk.Entry(ei, textvariable=self._name_var,
#                                    font=("Courier", 16, "bold"),
#                                    bg=CARD2, fg=WHITE, insertbackground=TEAL,
#                                    bd=0, width=28)
#         self.name_entry.pack(padx=12, pady=10)
#         self.name_entry.bind("<Escape>", lambda _: self.destroy())
#         self.name_entry.bind("<Down>",   self._focus_list)

#         self._status_lbl = tk.Label(sf, text="Start typing to search…",
#                                     font=("Courier", 8), bg=BG, fg=MUTED)
#         self._status_lbl.pack(anchor="w", pady=(6, 0))
#         _make_sep(self, BORDER)

#         lf = tk.Frame(self, bg=BG, padx=20, pady=10); lf.pack(fill=tk.BOTH, expand=True)
#         tk.Label(lf, text="RESULTS — click a name to load their ID",
#                  font=("Courier", 7, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 6))

#         style = ttk.Style(self); style.theme_use("default")
#         style.configure("FID.Treeview", background=CARD2, foreground=TEXT,
#                          fieldbackground=CARD2, rowheight=34,
#                          font=("Courier", 10), borderwidth=0)
#         style.configure("FID.Treeview.Heading", background=CARD,
#                          foreground=TEAL, font=("Courier", 8, "bold"), relief="flat")
#         style.map("FID.Treeview",
#                   background=[("selected", TEAL_DIM)],
#                   foreground=[("selected", TEAL)])

#         cols = ("Name", "ZK ID", "Status")
#         self._tree = ttk.Treeview(lf, columns=cols, show="headings",
#                                   style="FID.Treeview", selectmode="browse", height=6)
#         self._tree.heading("Name",   text="FULL NAME")
#         self._tree.heading("ZK ID",  text="WORKER ID")
#         self._tree.heading("Status", text="TODAY")
#         self._tree.column("Name",   width=270, anchor="w",      stretch=True)
#         self._tree.column("ZK ID",  width=90,  anchor="center")
#         self._tree.column("Status", width=110, anchor="center")
#         for tag, col in [("in", ORANGE2), ("out", GREEN2), ("none", ACCENT2)]:
#             self._tree.tag_configure(tag, foreground=col)

#         vsb = ttk.Scrollbar(lf, orient="vertical", command=self._tree.yview)
#         self._tree.configure(yscrollcommand=vsb.set)
#         self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         vsb.pack(side=tk.RIGHT, fill=tk.Y)
#         self._tree.bind("<Double-1>",   self._on_select)
#         self._tree.bind("<Return>",     self._on_select)
#         self._tree.bind("<Up>",         self._up_to_entry)
#         _make_sep(self, BORDER2)

#         ft = tk.Frame(self, bg=CARD, padx=20, pady=10); ft.pack(fill=tk.X)
#         btn_sel = tk.Button(ft, text="✔ USE SELECTED ID",
#                             font=("Courier", 9, "bold"), relief=tk.FLAT,
#                             bg=TEAL_DIM, fg=TEAL,
#                             activebackground=TEAL, activeforeground=BG,
#                             cursor="hand2", padx=14, pady=6, command=self._on_select)
#         btn_sel.pack(side=tk.LEFT)
#         _btn_hover(btn_sel, TEAL, BG, TEAL_DIM, TEAL)

#         btn_cancel = tk.Button(ft, text="✕ CANCEL",
#                                font=("Courier", 9, "bold"), relief=tk.FLAT,
#                                bg=BORDER, fg=TEXT2,
#                                activebackground=RED_DIM, activeforeground=RED,
#                                cursor="hand2", padx=14, pady=6, command=self.destroy)
#         btn_cancel.pack(side=tk.RIGHT)
#         _btn_hover(btn_cancel, RED_DIM, RED, BORDER, TEXT2)

#     def _focus_list(self, _=None):
#         children = self._tree.get_children()
#         if children:
#             self._tree.focus(children[0])
#             self._tree.selection_set(children[0])
#             self._tree.focus_set()

#     def _up_to_entry(self, _=None):
#         idx = self._tree.index(self._tree.focus())
#         if idx == 0:
#             self.name_entry.focus_set()

#     def _on_type(self):
#         if self._search_job:
#             self.after_cancel(self._search_job)
#         query = self._name_var.get().strip()
#         if len(query) < 2:
#             self._status_lbl.config(text="Type at least 2 characters…", fg=MUTED)
#             self._tree.delete(*self._tree.get_children())
#             return
#         self._status_lbl.config(text="Searching…", fg=ORANGE2)
#         self._search_job = self.after(
#             500, lambda: threading.Thread(
#                 target=self._do_search, args=(query,), daemon=True).start())

#     def _do_search(self, query: str):
#         try:
#             workers = search_workers_by_name(query)
#         except Exception as exc:
#             _log.error(f"ForgottenIDDialog search error: {exc}")
#             workers = []
#         # schedule UI update safely — only if dialog still open
#         try:
#             self.after(0, lambda: self._populate(query, workers))
#         except Exception:
#             pass  # dialog was closed before callback scheduled

#     def _populate(self, query: str, workers: list):
#         try:
#             if not self.winfo_exists():
#                 return
#         except Exception:
#             return
#         self._results = workers
#         self._tree.delete(*self._tree.get_children())
#         if not workers:
#             self._status_lbl.config(
#                 text=f'No workers found matching "{query}"', fg=RED2)
#             return
#         seen_ids = set()
#         for w in workers:
#             name  = w.get("Full_Name", "—")
#             zk_id = str(w.get("ZKTeco_User_ID2", "")).strip()
#             if not zk_id or zk_id in ("0", "None", ""):
#                 zk_id = str(w.get("Worker_ID", "—")).strip()
#             # deduplicate by zk_id
#             iid = zk_id if zk_id not in seen_ids else f"{zk_id}_{name}"
#             seen_ids.add(zk_id)
#             status = get_worker_status(zk_id)
#             labels = {"checked_in": "⏱ IN", "done": "✔ OUT", "none": "— —"}
#             tag    = {"checked_in": "in", "done": "out", "none": "none"}.get(status, "none")
#             try:
#                 self._tree.insert("", tk.END,
#                                   values=(name, zk_id, labels.get(status, "—")),
#                                   tags=(tag,), iid=iid)
#             except Exception:
#                 self._tree.insert("", tk.END,
#                                   values=(name, zk_id, labels.get(status, "—")),
#                                   tags=(tag,))
#         count = len(workers)
#         if count == 1 and query == self._name_var.get().strip():
#             self._status_lbl.config(text="✔ 1 match found — filling ID automatically…", fg=TEAL)
#             first = self._tree.get_children()[0]
#             self._tree.selection_set(first)
#             self._tree.focus(first)
#             self.after(600, self._on_select)
#             return
#         self._status_lbl.config(
#             text=f"Found {count} worker{'s' if count != 1 else ''} — double-click or Enter to select",
#             fg=TEAL)

#     def _on_select(self, _=None):
#         sel = self._tree.selection()
#         if not sel:
#             return
#         # Get ZK ID from the actual row values (column index 1), not the iid
#         try:
#             zk_id = self._tree.item(sel[0], "values")[1]
#         except Exception:
#             zk_id = sel[0]
#         if zk_id and zk_id not in ("—", "", "None"):
#             self.destroy()
#             self.on_select(str(zk_id))

# # ===========================================================
# # FINGERPRINT CANVAS
# # ===========================================================
# class FingerprintCanvas(tk.Canvas):
#     SIZE = 140
#     def __init__(self, parent, **kwargs):
#         super().__init__(parent, width=self.SIZE, height=self.SIZE,
#                          bg=CARD2, highlightthickness=0, **kwargs)
#         self._cx = self._cy = self.SIZE // 2
#         self._angle = 0; self._state = "idle"; self._phase = 0
#         self._arc_items = []
#         self._draw_base(); self._animate()

#     def _draw_base(self):
#         cx, cy = self._cx, self._cy
#         self.delete("fp")
#         self.create_oval(cx-64, cy-64, cx+64, cy+64,
#                          outline=BORDER2, width=1, tags="fp")
#         arc_defs = [(10,0,300,2),(18,20,280,2),(26,30,270,1),
#                     (34,15,290,1),(42,25,265,1),(50,10,285,1),(58,35,250,1)]
#         self._arc_items = []
#         for r, start, extent, w in arc_defs:
#             item = self.create_arc(cx-r, cy-r, cx+r, cy+r,
#                                    start=start, extent=extent,
#                                    outline=MUTED, width=w,
#                                    style="arc", tags="fp")
#             self._arc_items.append(item)
#         self._centre = self.create_oval(cx-5, cy-5, cx+5, cy+5,
#                                         fill=MUTED, outline="", tags="fp")
#         self._spin = self.create_arc(cx-58, cy-58, cx+58, cy+58,
#                                      start=0, extent=0,
#                                      outline=ACCENT, width=3,
#                                      style="arc", tags="fp")

#     def start(self):    self._state = "scanning"
#     def stop_ok(self):
#         self._state = "ok"
#         for item in self._arc_items: self.itemconfig(item, outline=GREEN2)
#         self.itemconfig(self._centre, fill=GREEN2)
#         self.itemconfig(self._spin, extent=0)
#     def stop_err(self, _=""):
#         self._state = "error"
#         for item in self._arc_items: self.itemconfig(item, outline=RED2)
#         self.itemconfig(self._centre, fill=RED2)
#         self.itemconfig(self._spin, extent=0)
#     def reset(self):
#         self._state = "idle"; self._angle = 0; self._draw_base()

#     def _animate(self):
#         self._phase = (self._phase + 1) % 120
#         if self._state == "scanning":
#             self._angle = (self._angle + 6) % 360
#             sweep = int(200 * abs(math.sin(math.radians(self._angle))))
#             self.itemconfig(self._spin, start=self._angle, extent=sweep, outline=ACCENT)
#             for i, item in enumerate(self._arc_items):
#                 a  = 0.3 + 0.7 * abs(math.sin(math.radians((self._phase + i*10) * 4)))
#                 rv = int(int(ACCENT[1:3], 16) * a)
#                 gv = int(int(ACCENT[3:5], 16) * a)
#                 bv = int(int(ACCENT[5:7], 16) * a)
#                 self.itemconfig(item, outline=f"#{rv:02x}{gv:02x}{bv:02x}")
#             a2 = 0.4 + 0.6 * abs(math.sin(math.radians(self._phase * 3)))
#             rv = int(int(ACCENT[1:3], 16) * a2)
#             gv = int(int(ACCENT[3:5], 16) * a2)
#             bv = int(int(ACCENT[5:7], 16) * a2)
#             self.itemconfig(self._centre, fill=f"#{rv:02x}{gv:02x}{bv:02x}")
#         elif self._state == "ok":
#             a  = 0.6 + 0.4 * abs(math.sin(math.radians(self._phase * 2)))
#             rv = int(int(GREEN2[1:3], 16) * a)
#             gv = int(int(GREEN2[3:5], 16) * a)
#             bv = int(int(GREEN2[5:7], 16) * a)
#             col = f"#{rv:02x}{gv:02x}{bv:02x}"
#             for item in self._arc_items: self.itemconfig(item, outline=col)
#             self.itemconfig(self._centre, fill=col)
#         elif self._state == "error":
#             a  = 0.4 + 0.6 * abs(math.sin(math.radians(self._phase * 6)))
#             rv = int(int(RED2[1:3], 16) * a)
#             gv = int(int(RED2[3:5], 16) * a)
#             bv = int(int(RED2[5:7], 16) * a)
#             col = f"#{rv:02x}{gv:02x}{bv:02x}"
#             for item in self._arc_items: self.itemconfig(item, outline=col)
#             self.itemconfig(self._centre, fill=col)
#         else:
#             a  = 0.25 + 0.20 * abs(math.sin(math.radians(self._phase * 1.5)))
#             rv = min(int(int(MUTED[1:3], 16) * a * 2.5), 255)
#             gv = min(int(int(MUTED[3:5], 16) * a * 2.5), 255)
#             bv = min(int(int(MUTED[5:7], 16) * a * 2.5), 255)
#             col = f"#{rv:02x}{gv:02x}{bv:02x}"
#             for item in self._arc_items: self.itemconfig(item, outline=col)
#             self.itemconfig(self._spin, extent=0)
#         self.after(30, self._animate)

# # ===========================================================
# # PULSING LED
# # ===========================================================
# class PulseLED(tk.Canvas):
#     SIZE = 12
#     def __init__(self, parent, color=ACCENT):
#         super().__init__(parent, width=self.SIZE, height=self.SIZE,
#                          bg=parent.cget("bg"), highlightthickness=0)
#         r = self.SIZE // 2
#         self._dot   = self.create_oval(2, 2, r*2-2, r*2-2, fill=color, outline="")
#         self._color = color; self._phase = 0
#         self._pulse()

#     def set_color(self, c):
#         self._color = c
#         self.itemconfig(self._dot, fill=c)

#     def _pulse(self):
#         self._phase = (self._phase + 1) % 60
#         a = 0.55 + 0.45 * abs((self._phase % 60) - 30) / 30
#         c = self._color
#         try:
#             rv = int(int(c[1:3], 16) * a)
#             gv = int(int(c[3:5], 16) * a)
#             bv = int(int(c[5:7], 16) * a)
#             self.itemconfig(self._dot, fill=f"#{rv:02x}{gv:02x}{bv:02x}")
#         except Exception:
#             pass
#         self.after(50, self._pulse)

# # ===========================================================
# # DONUT RING
# # ===========================================================
# class DonutRing(tk.Canvas):
#     SIZE = 80
#     def __init__(self, parent, **kwargs):
#         super().__init__(parent, width=self.SIZE, height=self.SIZE,
#                          bg=CARD2, highlightthickness=0, **kwargs)
#         self._val = 0.0; self._color = GREEN2; self._phase = 0
#         self._draw(0); self._tick()

#     def set_value(self, fraction, color=GREEN2):
#         self._val = max(0.0, min(1.0, fraction)); self._color = color

#     def _draw(self, fraction):
#         self.delete("all")
#         cx = cy = self.SIZE // 2; r = cx - 6
#         self.create_arc(cx-r, cy-r, cx+r, cy+r,
#                         start=0, extent=359.9, outline=BORDER2, width=10, style="arc")
#         if fraction > 0:
#             self.create_arc(cx-r, cy-r, cx+r, cy+r,
#                             start=90, extent=-(fraction * 359.9),
#                             outline=self._color, width=10, style="arc")
#         self.create_text(cx, cy, text=f"{int(fraction*100)}%",
#                          font=("Courier", 11, "bold"),
#                          fill=self._color if fraction > 0 else MUTED)

#     def _tick(self):
#         self._phase += 1; self._draw(self._val); self.after(150, self._tick)

# # ===========================================================
# # ADMIN PANEL  (includes Daily Report tab)
# # ===========================================================
# class AdminPanel(tk.Toplevel):
#     def __init__(self, parent):
#         super().__init__(parent)
#         self.title("Attendance Command Center")
#         self.configure(bg="#ffffff"); self.resizable(True, True)
#         sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
#         W, H   = min(sw, 1200), min(sh, 760)
#         self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
#         self._all_rows  = []; self._sort_col = None; self._sort_asc = True
#         self._build(); self.refresh()

#     def _build(self):
#         # ── header ──────────────────────────────────────────────────
#         hdr = tk.Frame(self, bg="#f8f9fa"); hdr.pack(fill=tk.X)
#         tk.Frame(hdr, bg=PURPLE, height=2).pack(fill=tk.X)
#         hi  = tk.Frame(hdr, bg="#f8f9fa", padx=24, pady=14); hi.pack(fill=tk.X)
#         lf  = tk.Frame(hi, bg="#f8f9fa"); lf.pack(side=tk.LEFT)
#         tk.Label(lf, text="ATTENDANCE COMMAND CENTER",
#                  font=("Courier", 13, "bold"), bg="#f8f9fa", fg="#212529").pack(anchor="w")
#         self.sub_lbl = tk.Label(lf, text="", font=("Courier", 8), bg="#f8f9fa", fg="#6c757d")
#         self.sub_lbl.pack(anchor="w", pady=(2, 0))
#         rf = tk.Frame(hi, bg="#f8f9fa"); rf.pack(side=tk.RIGHT)
#         for txt, cmd, bg_, fg_ in [
#             ("↻ REFRESH",   self.refresh,  ACCENT_DIM, ACCENT2),
#             ("⬇ EXPORT CSV", self._export,  GREEN_DIM,  GREEN2),
#             ("✕ CLOSE",     self.destroy,  BORDER,     TEXT2)]:
#             b = tk.Button(rf, text=txt, font=("Courier", 9, "bold"), relief=tk.FLAT,
#                           bg=bg_, fg=fg_, cursor="hand2", padx=14, pady=6, command=cmd)
#             b.pack(side=tk.LEFT, padx=(0, 6))

#         # ── notebook tabs ────────────────────────────────────────────
#         style = ttk.Style(self); style.theme_use("default")
#         style.configure("Admin.TNotebook",        background="#ffffff", borderwidth=0)
#         style.configure("Admin.TNotebook.Tab",    background="#e2e8f0", foreground="#6c757d",
#                         font=("Courier", 9, "bold"), padding=[18, 8])
#         style.map("Admin.TNotebook.Tab",
#                   background=[("selected", "#ffffff")],
#                   foreground=[("selected", "#1d4ed8")])

#         nb = ttk.Notebook(self, style="Admin.TNotebook")
#         nb.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

#         # Tab 1 — All Records
#         self._tab_records = tk.Frame(nb, bg="#ffffff")
#         nb.add(self._tab_records, text="⚙  ALL RECORDS")

#         # Tab 2 — Daily Report
#         self._tab_report = tk.Frame(nb, bg="#ffffff")
#         nb.add(self._tab_report, text="📋  DAILY REPORT")

#         self._build_records_tab(self._tab_records)
#         self._build_report_tab(self._tab_report)

#     # ================================================================
#     #  TAB 1 — ALL RECORDS
#     # ================================================================
#     def _build_records_tab(self, parent):
#         sf = tk.Frame(parent, bg="#ffffff", padx=20, pady=8); sf.pack(fill=tk.X)
#         tk.Label(sf, text="SEARCH:", font=("Courier", 8, "bold"), bg="#ffffff", fg="#adb5bd").pack(side=tk.LEFT)
#         self._search_var = tk.StringVar()
#         self._search_var.trace_add("write", lambda *_: self._apply_filter())
#         tk.Entry(sf, textvariable=self._search_var, font=("Courier", 10),
#                  bg="#f1f3f5", fg="#212529", insertbackground="#d97706", bd=0, width=30
#                  ).pack(side=tk.LEFT, padx=(8, 0), ipady=4)
#         self._count_lbl = tk.Label(sf, text="", font=("Courier", 8), bg="#ffffff", fg="#adb5bd")
#         self._count_lbl.pack(side=tk.RIGHT)

#         self.kpi_fr = tk.Frame(parent, bg="#ffffff", padx=20, pady=10); self.kpi_fr.pack(fill=tk.X)
#         _make_sep(parent, BORDER2)

#         tw = tk.Frame(parent, bg="#ffffff", padx=20, pady=10); tw.pack(fill=tk.BOTH, expand=True)
#         style = ttk.Style(self); style.theme_use("default")
#         style.configure("Cmd.Treeview", background="#f1f3f5", foreground="#212529",
#                          fieldbackground="#f1f3f5", rowheight=28,
#                          font=("Courier", 9), borderwidth=0)
#         style.configure("Cmd.Treeview.Heading", background="#e2e8f0",
#                          foreground="#1d4ed8", font=("Courier", 9, "bold"),
#                          relief="flat", borderwidth=1)
#         style.map("Cmd.Treeview",
#                   background=[("selected", "#dbeafe")],
#                   foreground=[("selected", "#1d4ed8")])

#         cols    = ("ID", "Name", "Check-In", "Check-Out", "Hours", "OT", "Early?", "Late", "Status")
#         widths  = (60, 220, 100, 100, 70, 70, 70, 75, 90)
#         minws   = (60, 220,  90,  90, 60, 60, 60, 65, 80)
#         anchors = ("center", "center", "center", "center", "center",
#                    "center", "center", "center", "center")
#         stretches = (False, True, False, False, False, False, False, False, False)
#         self.tree = ttk.Treeview(tw, columns=cols, show="headings",
#                                   style="Cmd.Treeview", selectmode="browse")
#         for col, w, mw, a, st in zip(cols, widths, minws, anchors, stretches):
#             self.tree.heading(col, text=col.upper(),
#                               command=lambda c=col: self._sort_by(c))
#             self.tree.column(col, width=w, minwidth=mw, anchor=a, stretch=st)
#         for tag, col in [("late", "#b45309"), ("ot", "#7c3aed"), ("complete", "#059669"),
#                          ("still_in", "#1d4ed8"), ("early", "#0891b2"),
#                          ("auto", "#7c3aed"), ("alt", "#212529")]:
#             self.tree.tag_configure(
#                 tag,
#                 foreground=col,
#                 background="#f1f3f5" if tag == "alt" else "")

#         vsb = ttk.Scrollbar(tw, orient="vertical", command=self.tree.yview)
#         self.tree.configure(yscrollcommand=vsb.set)
#         self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         vsb.pack(side=tk.RIGHT, fill=tk.Y)

#     # ================================================================
#     #  TAB 2 — DAILY REPORT  (Late Arrivals & Early Checkouts)
#     # ================================================================
#     def _build_report_tab(self, parent):
#         # sub-header with refresh
#         hdr = tk.Frame(parent, bg="#f8f9fa", padx=20, pady=10); hdr.pack(fill=tk.X)
#         tk.Frame(hdr, bg=GOLD, height=2).pack(fill=tk.X, side=tk.TOP)
#         hi = tk.Frame(hdr, bg="#f8f9fa"); hi.pack(fill=tk.X, pady=(6, 0))
#         lf = tk.Frame(hi, bg="#f8f9fa"); lf.pack(side=tk.LEFT)
#         tk.Label(lf, text="📋 DAILY REPORT — Late Arrivals & Early Checkouts",
#                  font=("Courier", 11, "bold"), bg="#f8f9fa", fg="#212529").pack(anchor="w")
#         self._report_sub_lbl = tk.Label(lf, text="", font=("Courier", 8), bg="#f8f9fa", fg="#6c757d")
#         self._report_sub_lbl.pack(anchor="w", pady=(2, 0))
#         rf = tk.Frame(hi, bg="#f8f9fa"); rf.pack(side=tk.RIGHT)
#         b = tk.Button(rf, text="↻ REFRESH REPORT", font=("Courier", 9, "bold"),
#                       relief=tk.FLAT, bg=ACCENT_DIM, fg=ACCENT2, cursor="hand2",
#                       padx=14, pady=6, command=self._refresh_report)
#         b.pack()
#         _btn_hover(b, ACCENT2, BG, ACCENT_DIM, ACCENT2)

#         # KPI strip
#         self._report_kpi_fr = tk.Frame(parent, bg="#ffffff", padx=20, pady=10)
#         self._report_kpi_fr.pack(fill=tk.X)
#         tk.Frame(parent, bg="#ced4da", height=1).pack(fill=tk.X)

#         # scrollable body
#         body_wrap = tk.Frame(parent, bg="#ffffff"); body_wrap.pack(fill=tk.BOTH, expand=True)
#         self._report_canvas = tk.Canvas(body_wrap, bg="#ffffff", highlightthickness=0)
#         vsb = ttk.Scrollbar(body_wrap, orient="vertical",
#                              command=self._report_canvas.yview)
#         self._report_canvas.configure(yscrollcommand=vsb.set)
#         vsb.pack(side=tk.RIGHT, fill=tk.Y)
#         self._report_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         self._report_body     = tk.Frame(self._report_canvas, bg="#ffffff")
#         self._report_body_win = self._report_canvas.create_window(
#             (0, 0), window=self._report_body, anchor="nw")
#         self._report_body.bind("<Configure>",   self._on_report_body_resize)
#         self._report_canvas.bind("<Configure>", self._on_report_canvas_resize)
#         self._report_canvas.bind_all("<MouseWheel>",
#             lambda e: self._report_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
#         self._report_canvas.bind_all("<Button-4>",
#             lambda e: self._report_canvas.yview_scroll(-1, "units"))
#         self._report_canvas.bind_all("<Button-5>",
#             lambda e: self._report_canvas.yview_scroll( 1, "units"))

#     def _on_report_body_resize(self, _=None):
#         self._report_canvas.configure(
#             scrollregion=self._report_canvas.bbox("all"))

#     def _on_report_canvas_resize(self, event):
#         self._report_canvas.itemconfig(self._report_body_win, width=event.width)

#     def _make_report_section(self, parent, title, accent, icon, rows, col_defs):
#         sec_hdr = tk.Frame(parent, bg="#f1f3f5"); sec_hdr.pack(fill=tk.X)
#         tk.Frame(sec_hdr, bg=accent, width=6).pack(side=tk.LEFT, fill=tk.Y)
#         inner_hdr = tk.Frame(sec_hdr, bg="#f1f3f5", padx=24, pady=14)
#         inner_hdr.pack(side=tk.LEFT, fill=tk.X, expand=True)
#         tk.Label(inner_hdr, text=f"{icon} {title}",
#                  font=("Courier", 14, "bold"), bg="#f1f3f5", fg=accent).pack(anchor="w")
#         self._report_count_labels[title] = tk.Label(
#             inner_hdr, text="", font=("Courier", 9), bg="#f1f3f5", fg="#6c757d")
#         self._report_count_labels[title].pack(anchor="w", pady=(2, 0))
#         tk.Frame(parent, bg=accent, height=2).pack(fill=tk.X)

#         grid_wrap = tk.Frame(parent, bg="#ffffff"); grid_wrap.pack(fill=tk.X)
#         grid_wrap.columnconfigure(0, minsize=6)
#         for ci, (_, _, minw, wt) in enumerate(col_defs):
#             grid_wrap.columnconfigure(ci+1, minsize=minw, weight=wt)

#         tk.Frame(grid_wrap, bg=accent, width=6).grid(row=0, column=0, sticky="nsew")
#         for ci, (lbl, _, _, _) in enumerate(col_defs):
#             cell = tk.Frame(grid_wrap, bg="#f8f9fa", padx=14, pady=9)
#             cell.grid(row=0, column=ci+1, sticky="nsew")
#             tk.Label(cell, text=lbl, font=("Courier", 9, "bold"),
#                      bg="#f8f9fa", fg=accent, anchor="w").pack(fill=tk.X)
#         tk.Frame(grid_wrap, bg=accent, height=1).grid(
#             row=1, column=0, columnspan=len(col_defs)+1, sticky="ew")

#         if not rows:
#             empty = tk.Frame(grid_wrap, bg="#ffffff")
#             empty.grid(row=2, column=0, columnspan=len(col_defs)+1, sticky="ew")
#             tk.Label(empty, text=f"  No {title.lower()} recorded today.",
#                      font=("Courier", 11), bg="#ffffff", fg="#adb5bd", pady=20
#                      ).pack(anchor="w", padx=24)
#         else:
#             for ri, row in enumerate(rows):
#                 grid_row = ri + 2
#                 row_bg   = "#f1f3f5" if ri % 2 == 0 else "#f8f9fa"
#                 tk.Frame(grid_wrap, bg=accent, width=6).grid(
#                     row=grid_row, column=0, sticky="nsew")
#                 for ci, (_, key, _, _) in enumerate(col_defs):
#                     val  = str(row.get(key, "—"))
#                     fg_  = "#212529"
#                     if key == "zk_id":  fg_ = GOLD
#                     if key == "name":   fg_ = "#212529"
#                     if key == "status": fg_ = accent
#                     bold = key in ("zk_id", "name")
#                     cell = tk.Frame(grid_wrap, bg=row_bg, padx=14, pady=11)
#                     cell.grid(row=grid_row, column=ci+1, sticky="nsew")
#                     tk.Label(cell, text=val,
#                              font=("Courier", 11, "bold" if bold else "normal"),
#                              bg=row_bg, fg=fg_, anchor="w").pack(fill=tk.X)
#                 tk.Frame(grid_wrap, bg="#dee2e6", height=1).grid(
#                     row=grid_row, column=0, columnspan=len(col_defs)+1, sticky="sew")

#         tk.Frame(parent, bg="#ced4da", height=1).pack(fill=tk.X)
#         tk.Frame(parent, bg="#ffffff", height=24).pack()

#     def _refresh_report(self):
#         for w in self._report_body.winfo_children(): w.destroy()
#         self._report_count_labels = {}
#         lock  = load_lock()
#         now   = datetime.now()
#         cin   = lock.get("checked_in",  {})
#         cout  = lock.get("checked_out", {})
#         early_limit  = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                                    second=0, microsecond=0)
#         late_rows  = []
#         early_rows = []
#         all_workers = {**cin, **cout}

#         for zk_id, info in sorted(all_workers.items(),
#             key=lambda x: (x[1].get("time","") or x[1].get("checkin_time",""))
#                           if isinstance(x[1], dict) else ""):
#             if not isinstance(info, dict): continue
#             if not info.get("is_late", False): continue
#             name   = info.get("name", zk_id)
#             ci_raw = info.get("time","") or info.get("checkin_time","")
#             is_out = zk_id in cout
#             try:
#                 ci_disp = datetime.strptime(ci_raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M:%S")
#             except Exception:
#                 ci_disp = ci_raw[-8:] if len(ci_raw) >= 8 else ci_raw or "—"
#             status = "✔ OUT" if is_out else "● ACTIVE"
#             late_rows.append({"zk_id": zk_id, "name": name,
#                               "checkin": ci_disp,
#                               "late_note": info.get("late_note",""),
#                               "status": status})

#         for zk_id, info in sorted(cout.items(),
#             key=lambda x: x[1].get("time","") if isinstance(x[1], dict) else ""):
#             if not isinstance(info, dict): continue
#             co_raw = info.get("time","")
#             try:
#                 co_dt    = datetime.strptime(co_raw, "%H:%M:%S").replace(
#                     year=now.year, month=now.month, day=now.day)
#                 is_early = co_dt < early_limit
#             except Exception:
#                 is_early = False
#             if not is_early: continue
#             name   = info.get("name", zk_id)
#             ci_raw = info.get("checkin_time","")
#             try:
#                 ci_disp = datetime.strptime(ci_raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M:%S")
#             except Exception:
#                 ci_disp = ci_raw[-8:] if len(ci_raw) >= 8 else ci_raw or "—"
#             hrs   = info.get("total_hours", 0)
#             h_str = (f"{int(hrs)}h {int((hrs%1)*60):02d}m"
#                      if isinstance(hrs, (int, float)) else "—")
#             early_rows.append({"zk_id": zk_id, "name": name,
#                                 "checkin": ci_disp, "checkout": co_raw or "—",
#                                 "hours": h_str, "status": "⚡ LEFT EARLY"})

#         # KPI tiles
#         for w in self._report_kpi_fr.winfo_children(): w.destroy()
#         total_in = len(cin) + len(cout)
#         for label, val, fg, border in [
#             ("TOTAL IN TODAY",   total_in,        "#212529", "#ced4da"),
#             ("STILL ON-SITE",    len(cin),         "#1d4ed8", "#bfdbfe"),
#             ("CHECKED OUT",      len(cout),        "#059669", "#a7f3d0"),
#             ("LATE ARRIVALS",    len(late_rows),   "#b45309", "#fde68a"),
#             ("EARLY CHECKOUTS",  len(early_rows),  "#0891b2", "#a5f3fc"),
#         ]:
#             tile = tk.Frame(self._report_kpi_fr, bg="#ffffff", padx=20, pady=10,
#                             highlightbackground=border, highlightthickness=1, relief="flat")
#             tile.pack(side=tk.LEFT, padx=(0, 10), fill=tk.Y)
#             tk.Label(tile, text=str(val),
#                      font=("Courier", 28, "bold"), bg="#ffffff", fg=fg).pack()
#             tk.Label(tile, text=label,
#                      font=("Courier", 7, "bold"),  bg="#ffffff", fg="#6c757d").pack()

#         self._make_report_section(
#             self._report_body, title="LATE ARRIVALS",
#             accent=ORANGE2, icon="⚠", rows=late_rows,
#             col_defs=[("ZK ID","zk_id",80,0),("FULL NAME","name",260,1),
#                       ("CHECKED IN","checkin",120,0),
#                       ("LATE BY","late_note",160,0),
#                       ("STATUS","status",120,0)])
#         self._make_report_section(
#             self._report_body, title="EARLY CHECKOUTS",
#             accent=CYAN2, icon="⚡", rows=early_rows,
#             col_defs=[("ZK ID","zk_id",80,0),("FULL NAME","name",260,1),
#                       ("CHECKED IN","checkin",120,0),
#                       ("CHECKED OUT","checkout",120,0),
#                       ("HOURS","hours",100,0),
#                       ("STATUS","status",140,0)])

#         now_str = now.strftime("%H:%M:%S")
#         self._report_sub_lbl.config(text=(
#             f"Date: {lock.get('date', now.strftime('%Y-%m-%d'))}  "
#             f"Shift start: {SHIFT_START_H:02d}:{SHIFT_START_M:02d}  "
#             f"Early threshold: before {EARLY_CHECKOUT_H:02d}:{EARLY_CHECKOUT_M:02d}  "
#             f"Last refresh: {now_str}"))

#         if "LATE ARRIVALS" in self._report_count_labels:
#             self._report_count_labels["LATE ARRIVALS"].config(
#                 text=f"{len(late_rows)} worker{'s' if len(late_rows)!=1 else ''} arrived late today")
#         if "EARLY CHECKOUTS" in self._report_count_labels:
#             self._report_count_labels["EARLY CHECKOUTS"].config(
#                 text=f"{len(early_rows)} worker{'s' if len(early_rows)!=1 else ''} "
#                      f"left before {EARLY_CHECKOUT_H:02d}:{EARLY_CHECKOUT_M:02d}")

#         self._report_canvas.update_idletasks()
#         self._report_canvas.configure(
#             scrollregion=self._report_canvas.bbox("all"))

#     # ================================================================
#     #  SHARED RECORDS TAB METHODS
#     # ================================================================
#     def _sort_by(self, col):
#         self._sort_asc = not self._sort_asc if self._sort_col == col else True
#         self._sort_col = col; self._apply_filter()

#     def _apply_filter(self):
#         q = self._search_var.get().strip().lower()
#         visible = [r for r in self._all_rows
#                    if not q or any(q in str(v).lower() for v in r["values"])]
#         if self._sort_col:
#             cols = ["ID", "Name", "Check-In", "Check-Out",
#                     "Hours", "OT", "Early?", "Late", "Status"]
#             idx  = cols.index(self._sort_col) if self._sort_col in cols else 0
#             visible.sort(key=lambda r: str(r["values"][idx]),
#                          reverse=not self._sort_asc)
#         self.tree.delete(*self.tree.get_children())
#         for i, r in enumerate(visible):
#             tags = list(r["tags"]) + ["alt"] if i % 2 == 1 else list(r["tags"])
#             self.tree.insert("", tk.END, values=r["values"], tags=tuple(tags))
#         self._count_lbl.config(text=f"{len(visible)}/{len(self._all_rows)} records")

#     def refresh(self):
#         self._all_rows = []
#         lock  = load_lock()
#         cin   = lock.get("checked_in",  {})
#         cout  = lock.get("checked_out", {})
#         late_count = ot_count = early_count = auto_count = 0
#         now   = datetime.now()
#         early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
#                                   second=0, microsecond=0)

#         for zk_id, info in sorted(cout.items(),
#             key=lambda x: x[1].get("checkin_time", "") if isinstance(x[1], dict) else ""):
#             if not isinstance(info, dict): continue
#             name  = info.get("name", zk_id)
#             ci    = info.get("checkin_time", "---"); ci_s = ci[-8:] if len(ci) > 8 else ci
#             co    = info.get("time", "---")
#             hrs   = info.get("total_hours",    0)
#             ot    = info.get("overtime_hours", 0)
#             late  = info.get("is_late",  False)
#             auto  = info.get("auto_checkout", False)
#             h_str = (f"{int(hrs)}h {int((hrs%1)*60):02d}m"
#                      if isinstance(hrs, (int, float)) else str(hrs))
#             o_str = (f"{int(ot)}h {int((ot%1)*60):02d}m" if ot else "---")
#             is_early = False
#             try:
#                 co_dt    = datetime.strptime(co, "%H:%M:%S").replace(
#                     year=now.year, month=now.month, day=now.day)
#                 is_early = co_dt < early_limit
#             except Exception: pass
#             if late:     late_count  += 1
#             if ot > 0:   ot_count    += 1
#             if is_early: early_count += 1
#             if auto:     auto_count  += 1
#             tags = []
#             if late:     tags.append("late")
#             if ot > 0:   tags.append("ot")
#             if is_early: tags.append("early")
#             if auto:     tags.append("auto")
#             tags.append("complete")
#             self._all_rows.append({"values": (
#                 zk_id, name, ci_s, co, h_str, o_str,
#                 "⚡ YES" if is_early else "---",
#                 "⚠ LATE" if late else "---",
#                 "AUTO" if auto else "✔ DONE"), "tags": tags})

#         for zk_id, info in sorted(cin.items(),
#             key=lambda x: x[1].get("time", "") if isinstance(x[1], dict) else ""):
#             if not isinstance(info, dict): continue
#             name = info.get("name", zk_id)
#             ci   = info.get("time", "---"); late = info.get("is_late", False)
#             try:
#                 dt_in   = datetime.strptime(ci, "%d-%b-%Y %H:%M:%S")
#                 elapsed = (now - dt_in).total_seconds() / 3600
#                 h_str   = f"{int(elapsed)}h {int((elapsed%1)*60):02d}m"
#             except Exception:
#                 h_str = "---"
#             ci_s = ci[-8:] if len(ci) > 8 else ci
#             if late: late_count += 1
#             tags = ["late"] if late else []
#             tags.append("still_in")
#             self._all_rows.append({"values": (
#                 zk_id, name, ci_s, "---", h_str, "---", "---",
#                 "⚠ LATE" if late else "---", "● ACTIVE"), "tags": tags})

#         self._apply_filter()
#         for w in self.kpi_fr.winfo_children(): w.destroy()
#         total = len(cin) + len(cout)
#         for label, val, fg, border in [
#             ("TOTAL",       total,       "#212529", "#ced4da"),
#             ("CHECKED IN",  total,       "#1d4ed8", "#bfdbfe"),
#             ("CHECKED OUT", len(cout),   "#059669", "#a7f3d0"),
#             ("AUTO-OUT",    auto_count,  "#7c3aed", "#ddd6fe"),
#             ("EARLY OUT",   early_count, "#0891b2", "#a5f3fc"),
#             ("LATE",        late_count,  "#b45309", "#fde68a"),
#             ("OVERTIME",    ot_count,    "#7c3aed", "#ddd6fe")]:
#             tile = tk.Frame(self.kpi_fr, bg="#ffffff", padx=13, pady=8,
#                             highlightbackground=border, highlightthickness=1, relief="flat")
#             tile.pack(side=tk.LEFT, padx=(0, 8), fill=tk.Y)
#             tk.Label(tile, text=str(val), font=("Courier", 20, "bold"),
#                      bg="#ffffff", fg=fg).pack()
#             tk.Label(tile, text=label, font=("Courier", 6, "bold"),
#                      bg="#ffffff", fg="#6c757d").pack()

#         self.sub_lbl.config(text=(
#             f"Date:{lock.get('date','')}  "
#             f"Shift:{SHIFT_START_H:02d}:{SHIFT_START_M:02d}  "
#             f"Std:{SHIFT_HOURS}h  Grace:{GRACE_MINUTES}min  "
#             f"Auto-out:{AUTO_CHECKOUT_H:02d}:00  "
#             f"Refreshed:{datetime.now().strftime('%H:%M:%S')}"))

#         # also refresh the report tab data
#         self._refresh_report()

#     def _export(self):
#         fname = export_daily_summary()
#         if fname:
#             messagebox.showinfo("Exported", f"Saved:\n{os.path.abspath(fname)}", parent=self)
#         else:
#             messagebox.showwarning("Nothing to Export", "No records for today.", parent=self)


# # ===========================================================
# # MAIN GUI
# # ===========================================================
# class FingerprintGUI:
#     def __init__(self, root):
#         self.root   = root
#         self.root.title("Wavemark Properties — Attendance Terminal")
#         self.root.configure(bg=BG)
#         self.root.resizable(False, False)
#         self._busy         = False
#         self._debounce_job = None
#         self._log_lines    = 0
#         self._gui_q: queue.Queue = queue.Queue()
#         sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
#         W, H   = min(sw, 980), min(sh, 800)
#         self.root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
#         self._build_ui()
#         self._tick_clock()
#         self._tick_stats()
#         self._tick_autocheckout()
#         self._drain_q()
#         self.root.protocol("WM_DELETE_WINDOW", self._on_close)

#         # Startup check — warn user immediately if .env is broken
#         self.root.after(1500, self._startup_token_check)

#     def _startup_token_check(self):
#         def _check():
#             token = get_access_token()
#             if not token:
#                 self._gui(lambda: self.log(
#                     "⚠ WARNING: Could not connect to Zoho — "
#                     "check CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN in .env\n"
#                     "  Visit https://api-console.zoho.com to regenerate credentials.", "err"))
#         threading.Thread(target=_check, daemon=True).start()

#     def _drain_q(self):
#         try:
#             while True: self._gui_q.get_nowait()()
#         except queue.Empty: pass
#         self.root.after(50, self._drain_q)

#     def _gui(self, fn):
#         self._gui_q.put(fn)

#     # ------ UI BUILD ------
#     def _build_ui(self):
#         self._build_header(); self._build_body()
#         self._build_footer(); self._build_flash()

#     def _build_header(self):
#         hdr = tk.Frame(self.root, bg=CARD); hdr.pack(fill=tk.X)
#         tk.Frame(hdr, bg=GOLD, height=3).pack(fill=tk.X)
#         hi  = tk.Frame(hdr, bg=CARD, padx=28, pady=14); hi.pack(fill=tk.X)
#         lf  = tk.Frame(hi, bg=CARD); lf.pack(side=tk.LEFT)
#         # ── Animated marquee for company name ──────────────────────
#         self._marquee_canvas = tk.Canvas(lf, bg=CARD, highlightthickness=0,
#                                          height=26, width=340)
#         self._marquee_canvas.pack(anchor="w")
#         self._marquee_text = self._marquee_canvas.create_text(
#             340, 13, text="WAVEMARK PROPERTIES LIMITED   ✦   WAVEMARK PROPERTIES LIMITED   ✦   ",
#             font=("Courier", 11, "bold"), fill=GOLD, anchor="w")
#         self._marquee_x = 340
#         self._marquee_speed = 2
#         self._animate_marquee()
#         # ── Static subtitle ─────────────────────────────────────────
#         tk.Label(lf, text="Biometric Attendance Terminal · v5.3 · 2000-user edition",
#                  font=("Courier", 8), bg=CARD, fg=MUTED).pack(anchor="w", pady=(1, 0))
#         rf = tk.Frame(hi, bg=CARD); rf.pack(side=tk.RIGHT)
#         btn_row = tk.Frame(rf, bg=CARD); btn_row.pack(anchor="e", pady=(0, 6))
#         btn_refresh = tk.Button(btn_row, text="↻ REFRESH",
#                                 font=("Courier", 8, "bold"), relief=tk.FLAT,
#                                 bg=ACCENT_DIM, fg=ACCENT2,
#                                 activebackground=ACCENT, activeforeground=WHITE,
#                                 cursor="hand2", padx=10, pady=5,
#                                 command=self._refresh_main)
#         btn_refresh.pack(side=tk.LEFT, padx=(0, 6))
#         _btn_hover(btn_refresh, ACCENT, WHITE, ACCENT_DIM, ACCENT2)
#         btn_admin = tk.Button(btn_row, text="⚙ ADMIN PANEL",
#                               font=("Courier", 8, "bold"), relief=tk.FLAT,
#                               bg=PURPLE_DIM, fg=PURPLE,
#                               activebackground=PURPLE, activeforeground=WHITE,
#                               cursor="hand2", padx=10, pady=5,
#                               command=self._open_admin)
#         btn_admin.pack(side=tk.LEFT)
#         _btn_hover(btn_admin, PURPLE, WHITE, PURPLE_DIM, PURPLE)
#         self.date_lbl  = tk.Label(rf, text="", font=("Courier", 8),  bg=CARD, fg=TEXT2)
#         self.date_lbl.pack(anchor="e")
#         self.clock_lbl = tk.Label(rf, text="", font=("Courier", 24, "bold"), bg=CARD, fg=WHITE)
#         self.clock_lbl.pack(anchor="e")
#         _make_sep(self.root, BORDER2)
#         sbar = tk.Frame(self.root, bg=CARD2, padx=28, pady=6); sbar.pack(fill=tk.X)
#         tk.Label(sbar, text=(f"SHIFT {SHIFT_START_H:02d}:{SHIFT_START_M:02d} · "
#                              f"STD {SHIFT_HOURS}H · GRACE {GRACE_MINUTES}MIN · "
#                              f"EARLY<{EARLY_CHECKOUT_H:02d}:00 · AUTO@{AUTO_CHECKOUT_H:02d}:00"),
#                  font=("Courier", 8), bg=CARD2, fg=WHITE).pack(side=tk.LEFT)
#         tk.Label(sbar, text="ENTER → auto-action   ESC → clear",
#                  font=("Courier", 8), bg=CARD2, fg=WHITE).pack(side=tk.RIGHT)

#     def _build_body(self):
#         body = tk.Frame(self.root, bg=BG, padx=24, pady=14)
#         body.pack(fill=tk.BOTH, expand=True)
#         cols = tk.Frame(body, bg=BG); cols.pack(fill=tk.BOTH, expand=True)
#         left  = tk.Frame(cols, bg=BG); left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         tk.Frame(cols, bg=BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y, padx=16)
#         right = tk.Frame(cols, bg=BG, width=300); right.pack(side=tk.LEFT, fill=tk.Y)
#         self._build_left(left); self._build_right(right)

#     def _build_left(self, parent):
#         id_card = tk.Frame(parent, bg=CARD2, highlightbackground=BORDER2, highlightthickness=1)
#         id_card.pack(fill=tk.X, pady=(0, 12))
#         ch = tk.Frame(id_card, bg=CARD, padx=18, pady=10); ch.pack(fill=tk.X)
#         tk.Label(ch, text="WORKER IDENTIFICATION",
#                  font=("Courier", 8, "bold"), bg=CARD, fg=TEXT2).pack(side=tk.LEFT)
#         self._led = PulseLED(ch, MUTED); self._led.pack(side=tk.RIGHT, padx=(0, 2))
#         _make_sep(id_card, BORDER)
#         ci = tk.Frame(id_card, bg=CARD2, padx=18, pady=14); ci.pack(fill=tk.X)
#         er = tk.Frame(ci, bg=CARD2); er.pack(fill=tk.X)
#         tk.Label(er, text="ID", font=("Courier", 8, "bold"),
#                  bg=CARD2, fg=MUTED, width=3, anchor="w").pack(side=tk.LEFT)
#         eb = tk.Frame(er, bg=GOLD, padx=1, pady=1); eb.pack(side=tk.LEFT, padx=(6, 0))
#         ei = tk.Frame(eb, bg="#09101a"); ei.pack()
#         self.user_entry = tk.Entry(ei, font=("Courier", 28, "bold"), width=9, bd=0,
#                                    bg="#09101a", fg=WHITE, insertbackground=GOLD,
#                                    selectbackground=GOLD2, selectforeground=BG)
#         self.user_entry.pack(padx=14, pady=8)
#         self.user_entry.bind("<KeyRelease>", self._on_key)
#         self.user_entry.bind("<Return>",     self._on_enter)
#         self.user_entry.bind("<Escape>",     lambda _: self._reset_ui())
#         self.user_entry.focus_set()
#         btn_clr = tk.Button(er, text="✕", font=("Courier", 10, "bold"), relief=tk.FLAT,
#                             bg=BORDER, fg=MUTED,
#                             activebackground=RED_DIM, activeforeground=RED,
#                             cursor="hand2", padx=8, pady=4, command=self._reset_ui)
#         btn_clr.pack(side=tk.LEFT, padx=(10, 0))
#         _btn_hover(btn_clr, RED_DIM, RED, BORDER, MUTED)

#         idf = tk.Frame(ci, bg=CARD2); idf.pack(fill=tk.X, pady=(12, 0))
#         self._avatar_cv = tk.Canvas(idf, width=48, height=48,
#                                     bg=CARD2, highlightthickness=0)
#         self._avatar_cv.pack(side=tk.LEFT, padx=(0, 12))
#         self._avatar_circle = self._avatar_cv.create_oval(2, 2, 46, 46,
#                                                            fill=BORDER, outline="")
#         self._avatar_text   = self._avatar_cv.create_text(24, 24, text="",
#                                                            font=("Courier", 13, "bold"),
#                                                            fill=MUTED)
#         info_col = tk.Frame(idf, bg=CARD2); info_col.pack(side=tk.LEFT, fill=tk.X)
#         self.name_lbl = tk.Label(info_col, text="—",
#                                   font=("Courier", 16, "bold"), bg=CARD2, fg=MUTED)
#         self.name_lbl.pack(anchor="w")
#         self.hint_lbl = tk.Label(info_col, text="Enter a Worker ID above",
#                                   font=("Courier", 9), bg=CARD2, fg=MUTED)
#         self.hint_lbl.pack(anchor="w", pady=(2, 0))

#         self.sf = tk.Frame(parent, bg=ACCENT_DIM,
#                            highlightbackground=ACCENT, highlightthickness=1)
#         self.sf.pack(fill=tk.X, pady=(0, 12))
#         sb_inner = tk.Frame(self.sf, bg=ACCENT_DIM); sb_inner.pack(fill=tk.X, padx=16, pady=10)
#         self._status_led = PulseLED(sb_inner, ACCENT)
#         self._status_led.pack(side=tk.LEFT, padx=(0, 8))
#         self.sl = tk.Label(sb_inner, text="Awaiting Worker ID",
#                            font=("Courier", 10, "bold"),
#                            bg=ACCENT_DIM, fg=ACCENT, anchor="w")
#         self.sl.pack(side=tk.LEFT, fill=tk.X)

#         # ── action buttons (Daily Report button REMOVED) ──
#         br = tk.Frame(parent, bg=BG); br.pack(fill=tk.X, pady=(0, 12))
#         self.btn_in = tk.Button(br, text="▶ CHECK IN",
#                                 font=("Courier", 12, "bold"), width=13,
#                                 relief=tk.FLAT, bg=GREEN_DIM, fg=MUTED,
#                                 activebackground=GREEN, activeforeground=BG,
#                                 cursor="hand2", state=tk.DISABLED,
#                                 command=lambda: self._trigger("checkin"))
#         self.btn_in.pack(side=tk.LEFT, ipady=12, padx=(0, 6))

#         self.btn_forgot = tk.Button(br, text="🔍 FORGOT ID",
#                                     font=("Courier", 9, "bold"), relief=tk.FLAT,
#                                     bg=TEAL_DIM, fg=TEAL,
#                                     activebackground=TEAL, activeforeground=BG,
#                                     cursor="hand2", padx=10,
#                                     command=self._open_forgotten_id)
#         self.btn_forgot.pack(side=tk.LEFT, ipady=12, padx=(0, 6))
#         _btn_hover(self.btn_forgot, TEAL, BG, TEAL_DIM, TEAL)

#         self.btn_out = tk.Button(br, text="■ CHECK OUT",
#                                  font=("Courier", 12, "bold"), width=13,
#                                  relief=tk.FLAT, bg=RED_DIM, fg=MUTED,
#                                  activebackground=RED, activeforeground=WHITE,
#                                  cursor="hand2", state=tk.DISABLED,
#                                  command=lambda: self._trigger("checkout"))
#         self.btn_out.pack(side=tk.LEFT, ipady=12, padx=(0, 6))

#         btn_exp = tk.Button(br, text="⬇ CSV", font=("Courier", 9, "bold"), relief=tk.FLAT,
#                             bg=BORDER, fg=TEXT2, cursor="hand2", padx=10,
#                             command=self._quick_export)
#         btn_exp.pack(side=tk.RIGHT, ipady=12)
#         _btn_hover(btn_exp, GREEN_DIM, GREEN2, BORDER, TEXT2)

#         _make_sep(parent, BORDER); tk.Frame(parent, bg=BG, height=8).pack()
#         lh = tk.Frame(parent, bg=BG); lh.pack(fill=tk.X, pady=(0, 6))
#         tk.Label(lh, text="ACTIVITY LOG",
#                  font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(side=tk.LEFT)
#         self._log_count_lbl = tk.Label(lh, text="", font=("Courier", 7), bg=BG, fg=MUTED)
#         self._log_count_lbl.pack(side=tk.LEFT, padx=(8, 0))
#         btn_clrlog = tk.Button(lh, text="CLEAR", font=("Courier", 7, "bold"),
#                                relief=tk.FLAT, bg=BORDER, fg=MUTED,
#                                padx=8, pady=2, cursor="hand2",
#                                command=self._clear_log)
#         btn_clrlog.pack(side=tk.RIGHT)
#         _btn_hover(btn_clrlog, BORDER2, TEXT2, BORDER, MUTED)

#         lw = tk.Frame(parent, bg=CARD, highlightbackground=BORDER2, highlightthickness=1)
#         lw.pack(fill=tk.BOTH, expand=True)
#         sb = tk.Scrollbar(lw, bg=BORDER, troughcolor=CARD); sb.pack(side=tk.RIGHT, fill=tk.Y)
#         self.log_box = tk.Text(lw, font=("Courier", 9), bg=CARD, fg=TEXT2, relief=tk.FLAT,
#                                padx=14, pady=10, yscrollcommand=sb.set,
#                                state=tk.DISABLED, cursor="arrow")
#         self.log_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
#         sb.config(command=self.log_box.yview)
#         for tag, col in [("ok", GREEN2), ("err", RED2), ("warn", ORANGE2),
#                          ("info", ACCENT2), ("ts", MUTED), ("div", BORDER2),
#                          ("late", ORANGE), ("ot", PURPLE), ("early", CYAN2)]:
#             self.log_box.tag_config(tag, foreground=col)

#     def _build_right(self, parent):
#         tk.Label(parent, text="BIOMETRIC SCANNER",
#                  font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 8))
#         sc       = tk.Frame(parent, bg=CARD2, highlightbackground=BORDER2, highlightthickness=1)
#         sc.pack(fill=tk.X, pady=(0, 14))
#         sc_inner = tk.Frame(sc, bg=CARD2, pady=16); sc_inner.pack()
#         self._fp       = FingerprintCanvas(sc_inner); self._fp.pack(pady=(0, 8))
#         self._scan_lbl = tk.Label(sc_inner, text="READY",
#                                   font=("Courier", 9, "bold"), bg=CARD2, fg=MUTED)
#         self._scan_lbl.pack()
#         self._scan_sub = tk.Label(sc_inner, text="Place finger when prompted",
#                                   font=("Courier", 7), bg=CARD2, fg=MUTED, wraplength=200)
#         self._scan_sub.pack(pady=(2, 0))

#         tk.Label(parent, text="LIVE DASHBOARD",
#                  font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 8))
#         dash = tk.Frame(parent, bg=BG); dash.pack(fill=tk.X)
#         row1 = tk.Frame(dash, bg=BG); row1.pack(fill=tk.X, pady=(0, 8))
#         self._tile_cin  = self._make_tile(row1, "CHECKED IN TODAY", "0", ACCENT2, "#0d1f3f")
#         self._tile_cout = self._make_tile(row1, "CHECKED OUT",      "0", GREEN2,  "#0a3321")
#         row2 = tk.Frame(dash, bg=BG); row2.pack(fill=tk.X, pady=(0, 8))
#         self._tile_early = self._make_tile(
#             row2, f"EARLY OUT (<{EARLY_CHECKOUT_H:02d}:00)", "0", CYAN2, CYAN_DIM, full=True)
#         row3 = tk.Frame(dash, bg=BG); row3.pack(fill=tk.X, pady=(0, 8))
#         self._tile_late = self._make_tile(row3, "LATE ARRIVALS", "0", ORANGE2, "#3d1f00")
#         self._tile_ot   = self._make_tile(row3, "OVERTIME",       "0", PURPLE,  "#1e0a40")

#         dr_frame = tk.Frame(parent, bg=CARD2, highlightbackground=BORDER, highlightthickness=1)
#         dr_frame.pack(fill=tk.X, pady=(0, 10))
#         dr_inner = tk.Frame(dr_frame, bg=CARD2, pady=10, padx=16); dr_inner.pack(fill=tk.X)
#         tk.Label(dr_inner, text="COMPLETION RATE",
#                  font=("Courier", 7, "bold"), bg=CARD2, fg=MUTED).pack(anchor="w", pady=(0, 6))
#         dr_row = tk.Frame(dr_inner, bg=CARD2); dr_row.pack(fill=tk.X)
#         self._donut = DonutRing(dr_row); self._donut.pack(side=tk.LEFT, padx=(0, 14))
#         dr_leg = tk.Frame(dr_row, bg=CARD2); dr_leg.pack(side=tk.LEFT, fill=tk.Y)
#         self._legend_lbl = tk.Label(dr_leg, text="0 of 0 workers\nhave checked out",
#                                     font=("Courier", 8), bg=CARD2, fg=TEXT2, justify=tk.LEFT)
#         self._legend_lbl.pack(anchor="w")
#         self._early_lbl  = tk.Label(dr_leg, text="",
#                                     font=("Courier", 8), bg=CARD2, fg=CYAN2, justify=tk.LEFT)
#         self._early_lbl.pack(anchor="w", pady=(6, 0))

#         tk.Label(parent, text="RECENT EVENTS",
#                  font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(8, 6))
#         ev_fr = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
#         ev_fr.pack(fill=tk.BOTH, expand=True)
#         self._event_box = tk.Text(ev_fr, font=("Courier", 8), bg=CARD, fg=TEXT2,
#                                   relief=tk.FLAT, padx=10, pady=8,
#                                   state=tk.DISABLED, cursor="arrow", height=7)
#         self._event_box.pack(fill=tk.BOTH, expand=True)
#         for tag, col in [("in", GREEN2), ("out", ACCENT2),
#                          ("warn", ORANGE2), ("ts", MUTED), ("early", CYAN2)]:
#             self._event_box.tag_config(tag, foreground=col)

#     def _make_tile(self, parent, label, value, fg, bg2, full=False):
#         tile = tk.Frame(parent, bg=CARD2, padx=14, pady=10,
#                         highlightbackground=bg2, highlightthickness=1)
#         kw = {"fill": tk.X, "expand": True}
#         if not full: kw["padx"] = (0, 6)
#         tile.pack(side=tk.LEFT, **kw)
#         val_lbl = tk.Label(tile, text=value, font=("Courier", 26, "bold"), bg=CARD2, fg=fg)
#         val_lbl.pack()
#         tk.Label(tile, text=label, font=("Courier", 6, "bold"), bg=CARD2, fg=TEXT2).pack()
#         return val_lbl

#     def _build_footer(self):
#         _make_sep(self.root, BORDER2)
#         foot = tk.Frame(self.root, bg=CARD, padx=28, pady=7)
#         foot.pack(fill=tk.X, side=tk.BOTTOM)
#         self._foot_lbl = tk.Label(foot, text="", font=("Courier", 8), bg=CARD, fg=MUTED)
#         self._foot_lbl.pack(side=tk.LEFT)
#         tk.Label(foot, text=(f"Shift {SHIFT_START_H:02d}:{SHIFT_START_M:02d}–"
#                              f"{(SHIFT_START_H+SHIFT_HOURS)%24:02d}:{SHIFT_START_M:02d} "
#                              f"· {SHIFT_HOURS}h std · {GRACE_MINUTES}min grace "
#                              f"· early<{EARLY_CHECKOUT_H:02d}:00 "
#                              f"· auto@{AUTO_CHECKOUT_H:02d}:00"),
#                  font=("Courier", 8), bg=CARD, fg=MUTED).pack(side=tk.RIGHT)

#     def _build_flash(self):
#         self.flash = tk.Frame(self.root, bg=ACCENT)
#         self.fi = tk.Label(self.flash, font=("Courier", 60, "bold"), bg=ACCENT, fg=WHITE)
#         self.fi.place(relx=0.5, rely=0.22, anchor="center")
#         self.fm = tk.Label(self.flash, font=("Courier", 22, "bold"),
#                            bg=ACCENT, fg=WHITE, wraplength=740)
#         self.fm.place(relx=0.5, rely=0.40, anchor="center")
#         self.fs = tk.Label(self.flash, font=("Courier", 22, "bold"),
#                            bg=ACCENT, fg=WHITE, wraplength=740, justify=tk.CENTER)
#         self.fs.place(relx=0.5, rely=0.56, anchor="center")
#         self.fx = tk.Label(self.flash, font=("Courier", 11, "bold"),
#                            bg=ACCENT, fg=GOLD2, wraplength=740)
#         self.fx.place(relx=0.5, rely=0.72, anchor="center")

#     # ------ TICKERS ------
#     def _tick_clock(self):
#         n = datetime.now()
#         self.date_lbl.config(text=n.strftime("%A, %d %B %Y"))
#         self.clock_lbl.config(text=n.strftime("%H:%M:%S"))
#         self.root.after(1000, self._tick_clock)

#     def _tick_stats(self):
#         lock  = load_lock()
#         cin   = lock.get("checked_in",  {})
#         cout  = lock.get("checked_out", {})
#         total = len(cin) + len(cout)
#         early = count_early_checkouts(lock)
#         late  = sum(1 for v in {**cin, **cout}.values()
#                     if isinstance(v, dict) and v.get("is_late"))
#         ot    = sum(1 for v in cout.values()
#                     if isinstance(v, dict) and v.get("overtime_hours", 0) > 0)
#         self._tile_cin.config(text=str(total))
#         self._tile_cout.config(text=str(len(cout)))
#         self._tile_early.config(text=str(early))
#         self._tile_late.config(text=str(late))
#         self._tile_ot.config(text=str(ot))
#         fraction   = len(cout) / total if total > 0 else 0
#         donut_col  = GREEN2 if fraction >= 0.8 else ORANGE2 if fraction >= 0.4 else ACCENT2
#         self._donut.set_value(fraction, donut_col)
#         self._legend_lbl.config(text=f"{len(cout)} of {total} workers\nhave checked out")
#         self._early_lbl.config(
#             text=f"⚡ {early} left before {EARLY_CHECKOUT_H:02d}:00" if early else "")
#         self._foot_lbl.config(
#             text=f"In:{total}  Out:{len(cout)}  On-site:{len(cin)}  "
#                  f"Early:{early}  Late:{late}  OT:{ot}")
#         self.root.after(STATS_REFRESH_MS, self._tick_stats)

#     def _tick_autocheckout(self):
#         now = datetime.now()
#         if (now.hour > AUTO_CHECKOUT_H or
#                 (now.hour == AUTO_CHECKOUT_H and now.minute >= AUTO_CHECKOUT_M)):
#             lock    = load_lock()
#             pending = {k: v for k, v in lock.get("checked_in", {}).items()
#                        if isinstance(v, dict)}
#             if pending:
#                 self.log(f"AUTO-CHECKOUT triggered @ {now.strftime('%H:%M')} "
#                          f"— {len(pending)} worker(s)", "warn")
#                 threading.Thread(
#                     target=run_auto_checkout,
#                     kwargs={"gui_log_fn": self.log, "done_cb": self._auto_checkout_done},
#                     daemon=True).start()
#             return
#         self.root.after(30_000, self._tick_autocheckout)

#     def _auto_checkout_done(self, success_names, fail_names):
#         def _u():
#             self._tick_stats()
#             n     = len(success_names)
#             names = ", ".join(success_names[:5]) + ("..." if len(success_names) > 5 else "")
#             extra = f"Failed: {', '.join(fail_names)}" if fail_names else ""
#             self._show_flash(">>", f"Auto-Checkout @ {datetime.now().strftime('%H:%M')}",
#                              f"{n} worker(s) checked out\n{names}", extra, "#1e0a40")
#             for name in success_names:
#                 self._add_event("AUTO-OUT", name, "warn")
#         self._gui(_u)

#     # ------ PANEL OPENERS ------
#     def _animate_marquee(self):
#         try:
#             self._marquee_x -= self._marquee_speed
#             # Get the bounding box of the text to know its full width
#             bbox = self._marquee_canvas.bbox(self._marquee_text)
#             if bbox:
#                 text_width = bbox[2] - bbox[0]
#                 # Reset when the full text has scrolled off the left edge
#                 if self._marquee_x < -text_width // 2:
#                     self._marquee_x = 340
#             self._marquee_canvas.coords(self._marquee_text, self._marquee_x, 13)
#             self.root.after(30, self._animate_marquee)
#         except Exception:
#             pass  # window was destroyed

#     def _open_admin(self):           AdminPanel(self.root)

#     def _refresh_main(self):
#         """Destroy and fully rebuild the entire main window."""
#         self.root.destroy()
#         root = tk.Tk()
#         FingerprintGUI(root)
#         root.mainloop()

#     def _open_forgotten_id(self):
#         def _on_select(zk_id: str):
#             self.user_entry.delete(0, tk.END)
#             self.user_entry.insert(0, zk_id)
#             self.user_entry.focus_set()
#             self._apply_status(get_worker_status(zk_id))
#             threading.Thread(target=self._validate, args=(zk_id,), daemon=True).start()
#             self.log(f"Forgotten ID resolved → ZK#{zk_id}", "info")
#         ForgottenIDDialog(self.root, on_select=_on_select)

#     def _quick_export(self):
#         def _do():
#             fname = export_daily_summary()
#             if fname:
#                 self._gui(lambda: self.log(f"Exported → {os.path.abspath(fname)}", "ok"))
#             else:
#                 self._gui(lambda: self.log("Nothing to export.", "warn"))
#         threading.Thread(target=_do, daemon=True).start()

#     # ------ LOGGING ------
#     def log(self, msg: str, tag: str = "info"):
#         def _do():
#             self.log_box.config(state=tk.NORMAL)
#             if self._log_lines >= LOG_MAX_LINES:
#                 self.log_box.delete("1.0", "50.0")
#                 self._log_lines = max(self._log_lines - 50, 0)
#             self.log_box.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] ", "ts")
#             self.log_box.insert(tk.END, f"{msg}\n", tag)
#             self.log_box.see(tk.END)
#             self.log_box.config(state=tk.DISABLED)
#             self._log_lines += 1
#             self._log_count_lbl.config(text=f"({self._log_lines})")
#         self._gui(_do)

#     def _clear_log(self):
#         self.log_box.config(state=tk.NORMAL)
#         self.log_box.delete("1.0", tk.END)
#         self.log_box.config(state=tk.DISABLED)
#         self._log_lines = 0
#         self._log_count_lbl.config(text="")

#     def _add_event(self, action: str, name: str, tag: str = "ts"):
#         def _do():
#             self._event_box.config(state=tk.NORMAL)
#             ts = datetime.now().strftime("%H:%M")
#             self._event_box.insert("1.0", f"{ts}  {action:<10}  {name}\n", tag)
#             lines = int(self._event_box.index("end-1c").split(".")[0])
#             if lines > 100:
#                 self._event_box.delete("80.0", tk.END)
#             self._event_box.config(state=tk.DISABLED)
#         self._gui(_do)

#     def _show_flash(self, icon, headline, sub, extra, color):
#         self.flash.config(bg=color)
#         for w, v in [(self.fi, icon), (self.fm, headline), (self.fs, sub), (self.fx, extra)]:
#             w.config(text=v, bg=color)
#         self.flash.place(x=0, y=0, relwidth=1, relheight=1)
#         self.flash.lift()
#         self.root.after(2400, self.flash.place_forget)

#     # ------ SCANNER STATES ------
#     def _scan_start(self):
#         self._fp.start()
#         self._scan_lbl.config(text="SCANNING…", fg=ORANGE2)
#         self._scan_sub.config(text="Place your finger on the reader now")

#     def _scan_ok(self):
#         self._fp.stop_ok()
#         self._scan_lbl.config(text="CAPTURED ✔", fg=GREEN2)
#         self._scan_sub.config(text="Processing…")

#     def _scan_err(self, msg="FAILED"):
#         self._fp.stop_err(msg)
#         self._scan_lbl.config(text=msg, fg=RED2)
#         self._scan_sub.config(text="Please try again")

#     def _scan_reset(self):
#         self._fp.reset()
#         self._scan_lbl.config(text="READY", fg=MUTED)
#         self._scan_sub.config(text="Place finger when prompted")

#     # ------ STATUS / BUTTONS ------
#     def _set_status(self, text, fg=ACCENT, bg=ACCENT_DIM, border=ACCENT):
#         self.sf.config(bg=bg, highlightbackground=border)
#         for w in self.sf.winfo_children():
#             for iw in [w] + list(w.winfo_children()):
#                 try: iw.config(bg=bg)
#                 except Exception: pass
#         self.sl.config(text=text, fg=fg, bg=bg)
#         try:
#             self._status_led.config(bg=bg)
#             self._status_led.set_color(fg)
#             self._led.set_color(fg)
#         except Exception: pass

#     def _set_buttons(self, in_s, out_s):
#         self.btn_in.config(state=in_s,
#                            bg=GREEN if in_s == tk.NORMAL else GREEN_DIM,
#                            fg=BG if in_s == tk.NORMAL else MUTED)
#         self.btn_out.config(state=out_s,
#                             bg=RED if out_s == tk.NORMAL else RED_DIM,
#                             fg=WHITE if out_s == tk.NORMAL else MUTED)

#     def _set_avatar(self, name=None, color=BORDER):
#         self._avatar_cv.itemconfig(self._avatar_circle, fill=color)
#         self._avatar_cv.itemconfig(self._avatar_text,
#                                    text=_initials(name) if name else "",
#                                    fill=WHITE if name else MUTED)

#     def _apply_status(self, status, name=None, ci_time=""):
#         if status == "done":
#             self._set_buttons(tk.DISABLED, tk.DISABLED)
#             self._set_status("Attendance complete — see you tomorrow", RED, RED_DIM, RED)
#             self._set_avatar(name, RED_DIM)
#         elif status == "checked_in":
#             self._set_buttons(tk.DISABLED, tk.NORMAL)
#             msg = (f"Already checked IN at {ci_time} — proceed to Check-Out"
#                    if ci_time else "Already checked IN — proceed to Check-Out")
#             self._set_status(msg, ORANGE, ORANGE_DIM, ORANGE)
#             self._set_avatar(name, ORANGE_DIM)
#         elif status == "none":
#             self._set_buttons(tk.NORMAL, tk.DISABLED)
#             self._set_status("Ready to CHECK IN", GREEN, GREEN_DIM, GREEN)
#             self._set_avatar(name, GREEN_DIM)
#         else:
#             self._set_buttons(tk.DISABLED, tk.DISABLED)
#             self._set_status("Awaiting Worker ID", ACCENT, ACCENT_DIM, ACCENT)
#             self._set_avatar(None, BORDER)

#     # ------ KEY / ENTER ------
#     def _on_key(self, _=None):
#         if self._debounce_job:
#             self.root.after_cancel(self._debounce_job)
#         uid = self.user_entry.get().strip()
#         if not uid:
#             self._soft_reset(); return
#         self._apply_status(get_worker_status(uid))
#         self._debounce_job = self.root.after(
#             650, lambda: threading.Thread(
#                 target=self._validate, args=(uid,), daemon=True).start())

#     def _validate(self, uid: str):
#         if self.user_entry.get().strip() != uid or self._busy:
#             return
#         worker = find_worker(uid)
#         def _upd():
#             if self.user_entry.get().strip() != uid:
#                 return
#             if not worker:
#                 self.name_lbl.config(text="Unknown ID", fg=RED2)
#                 self.hint_lbl.config(
#                     text=f"ID '{uid}' not found — check attendance.log for details", fg=RED)
#                 self._set_buttons(tk.DISABLED, tk.DISABLED)
#                 self._set_status(f"Worker ID {uid} not found — see log", RED, RED_DIM, RED)
#                 self._set_avatar(None, RED_DIM)
#                 self.log(f"Worker ID {uid} lookup failed — check attendance.log", "err")
#             else:
#                 name   = worker.get("Full_Name", "N/A")
#                 status = get_worker_status(uid)
#                 self.name_lbl.config(text=name, fg=WHITE)
#                 ci_time_hint = ""
#                 if status in ("checked_in", "done"):
#                     lk  = load_lock()
#                     rec = (lk.get("checked_in", {}).get(str(uid)) or
#                            lk.get("checked_out", {}).get(str(uid)))
#                     if isinstance(rec, dict):
#                         raw = rec.get("time", "") or rec.get("checkin_time", "")
#                         try:
#                             ci_time_hint = datetime.strptime(
#                                 raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M")
#                         except Exception:
#                             ci_time_hint = raw[-5:] if len(raw) >= 5 else raw
#                 hints = {
#                     "checked_in": (
#                         f"Checked in at {ci_time_hint} — use Check-Out"
#                         if ci_time_hint else "Checked in today — use Check-Out", ORANGE),
#                     "done": (
#                         f"Attendance complete — checked in at {ci_time_hint}"
#                         if ci_time_hint else "Attendance complete for today", RED),
#                     "none": ("Not yet checked in today", TEXT2),
#                 }
#                 htxt, hcol = hints.get(status, ("", TEXT2))
#                 self.hint_lbl.config(text=htxt, fg=hcol)
#                 self._apply_status(status, name, ci_time=ci_time_hint)
#         self.root.after(0, _upd)

#     def _on_enter(self, _=None):
#         uid = self.user_entry.get().strip()
#         if not uid or self._busy: return
#         s = get_worker_status(uid)
#         if s == "none":       self._trigger("checkin")
#         elif s == "checked_in": self._trigger("checkout")

#     # ------ PROCESS ------
#     def _trigger(self, action: str):
#         if self._busy: return
#         uid = self.user_entry.get().strip()
#         if not uid: return
#         self._busy = True
#         self._set_buttons(tk.DISABLED, tk.DISABLED)
#         verb = "CHECK IN" if action == "checkin" else "CHECK OUT"
#         self._set_status(f"Scanning fingerprint for {verb}…", ORANGE, ORANGE_DIM, ORANGE)
#         self.root.after(0, self._scan_start)
#         threading.Thread(target=self._process, args=(uid, action), daemon=True).start()

#     def _process(self, uid: str, action: str):
#         is_open = False; success = False; msg = ""; full_name = uid
#         try:
#             self.log(f"{'─'*16} {action.upper()} · ID {uid} {'─'*16}", "div")

#             if zk.GetDeviceCount() == 0:
#                 self.log("Scanner not connected", "err")
#                 self._gui(lambda: self._scan_err("NO DEVICE"))
#                 self._gui(lambda: self._show_flash(
#                     "⚠", "Scanner Not Connected",
#                     "Connect the fingerprint device and try again.", "", "#6d28d9"))
#                 return

#             zk.OpenDevice(0); is_open = True
#             self.log("Waiting for fingerprint…", "info")
#             capture = None
#             for _ in range(150):
#                 capture = zk.AcquireFingerprint()
#                 if capture: break
#                 time.sleep(0.2)

#             if not capture:
#                 self.log("Scan timed out", "err")
#                 self._gui(lambda: self._scan_err("TIMEOUT"))
#                 self._gui(lambda: self._show_flash(
#                     "⏱", "Scan Timeout", "No fingerprint detected.", "", "#92400e"))
#                 return

#             self._gui(self._scan_ok)
#             self.log("Fingerprint captured ✔", "ok")

#             _wcache_invalidate(uid)
#             worker = find_worker(uid, force_refresh=True)
#             if not worker:
#                 self.log(f"ID {uid} not found in Zoho — check attendance.log", "err")
#                 self._gui(lambda: self._scan_err("NOT FOUND"))
#                 self._gui(lambda: self._show_flash(
#                     "✗", "Worker Not Found",
#                     f"ID {uid} does not exist.\nCheck attendance.log for diagnostics.",
#                     "", RED_DIM))
#                 return

#             full_name = worker.get("Full_Name", uid)
#             self.log(f"Identity: {full_name}", "ok")

#             status = get_worker_status(uid)

#             if status == "done":
#                 self.log("Already complete", "warn")
#                 self._gui(lambda: self._show_flash(
#                     "🔒", "Already Complete", full_name, "Done for today.", "#1e0a40"))
#                 self.root.after(2600, lambda: self._apply_status("done", full_name))
#                 return

#             if status == "checked_in" and action == "checkin":
#                 _ci_rec = load_lock().get("checked_in", {}).get(str(uid), {})
#                 _ci_raw = _ci_rec.get("time", "") if isinstance(_ci_rec, dict) else ""
#                 try:
#                     _ci_t = datetime.strptime(_ci_raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M")
#                 except Exception:
#                     _ci_t = _ci_raw[-5:] if len(_ci_raw) >= 5 else _ci_raw
#                 _ci_msg = f"Checked in at {_ci_t}" if _ci_t else "Use Check-Out instead."
#                 self.log(f"Already checked IN at {_ci_t}", "warn")
#                 self._gui(lambda: self._show_flash(
#                     "↩", "Already Checked In", full_name, _ci_msg, "#3d1f00"))
#                 self.root.after(2600, lambda: self._apply_status(
#                     "checked_in", full_name, ci_time=_ci_t))
#                 return

#             if status == "none" and action == "checkout":
#                 self.log("Not checked IN yet", "warn")
#                 self._gui(lambda: self._show_flash(
#                     "⚠", "Not Checked In", full_name, "Check IN first.", "#1e0a40"))
#                 self.root.after(2600, lambda: self._apply_status("none", full_name))
#                 return

#             self.log(f"Posting {action.upper()} to Zoho…", "info")
#             pa  = worker.get("Projects_Assigned")
#             pid = pa.get("ID") if isinstance(pa, dict) else DEFAULT_PROJECT_ID
#             success, msg = log_attendance(
#                 worker["ID"], uid, pid, full_name, action, self.log)

#             tag = "ok" if success else "err"
#             for line in msg.splitlines():
#                 if line.strip():
#                     ltag = tag
#                     if "late"     in line.lower(): ltag = "late"
#                     if "overtime" in line.lower(): ltag = "ot"
#                     if "early"    in line.lower(): ltag = "early"
#                     self.log(line.strip(), ltag)

#             if success:
#                 verb      = "Checked IN" if action == "checkin" else "Checked OUT"
#                 sub       = datetime.now().strftime("Time: %H:%M:%S · %A, %d %B %Y")
#                 extra     = ""
#                 flash_col = "#1d4ed8"

#                 if action == "checkin" and is_late(datetime.now()):
#                     extra     = f"⚠ Late arrival — {late_by_str(datetime.now())}"
#                     flash_col = "#92400e"

#                 if action == "checkout":
#                     lock2  = load_lock()
#                     co     = lock2.get("checked_out", {}).get(str(uid), {})
#                     ot     = co.get("overtime_hours", 0) if isinstance(co, dict) else 0
#                     now_   = datetime.now()
#                     checkin_raw = co.get("checkin_time", "") if isinstance(co, dict) else ""
#                     try:
#                         ci_dt  = datetime.strptime(checkin_raw, "%d-%b-%Y %H:%M:%S")
#                         ci_disp = ci_dt.strftime("%H:%M:%S")
#                     except Exception:
#                         ci_disp = (checkin_raw[-8:] if len(checkin_raw) >= 8
#                                    else checkin_raw or "—")
#                     co_disp = now_.strftime("%H:%M:%S")
#                     sub  = (f"IN {ci_disp} → OUT {co_disp}"
#                             f"\n{now_.strftime('%A, %d %B %Y')}")
#                     if ot > 0:
#                         extra = f"⏱ Overtime: {int(ot)}h {int((ot%1)*60)}m"

#                 ev_tag = "in" if action == "checkin" else "out"
#                 _v, _s, _e, _fc = verb, sub, extra, flash_col
#                 self._gui(lambda: self._add_event(_v, full_name, ev_tag))
#                 self._gui(self._tick_stats)
#                 self._gui(lambda: self._show_flash(
#                     "✔", f"{_v} — {full_name}", _s, _e, _fc))
#             else:
#                 _m = msg.splitlines()[0][:80] if msg else "Unknown error"
#                 self._gui(lambda: self._scan_err("ERROR"))
#                 self._gui(lambda: self._show_flash("✗", "Action Failed", _m, "", RED_DIM))

#         except Exception as exc:
#             _log.exception(f"_process error: {exc}")
#             self.log(f"Unexpected error: {exc}", "err")
#         finally:
#             if is_open:
#                 try: zk.CloseDevice()
#                 except Exception: pass
#             self._busy = False
#             self.root.after(2600, self._scan_reset)
#             self.root.after(2600, lambda: self._reset_ui(clear_log=success))

#     def _reset_ui(self, clear_log=False):
#         self.user_entry.delete(0, tk.END)
#         self.name_lbl.config(text="—", fg=MUTED)
#         self.hint_lbl.config(text="Enter a Worker ID above", fg=MUTED)
#         self._set_avatar(None, BORDER)
#         self._set_buttons(tk.DISABLED, tk.DISABLED)
#         self._set_status("Awaiting Worker ID", ACCENT, ACCENT_DIM, ACCENT)
#         if clear_log:
#             self._clear_log()
#         self.log("Ready for next worker.", "div")
#         self.user_entry.focus_set()

#     def _soft_reset(self):
#         self.name_lbl.config(text="—", fg=MUTED)
#         self.hint_lbl.config(text="Enter a Worker ID above", fg=MUTED)
#         self._set_avatar(None, BORDER)
#         self._set_buttons(tk.DISABLED, tk.DISABLED)
#         self._set_status("Awaiting Worker ID", ACCENT, ACCENT_DIM, ACCENT)

#     def _on_close(self):
#         try: zk.Terminate()
#         except Exception: pass
#         self.root.destroy()

# # ===========================================================
# if __name__ == "__main__":
#     root = tk.Tk()
#     FingerprintGUI(root)
#     root.mainloop()



















































import os, time, json, csv, requests, threading, math, queue, logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pyzkfp import ZKFP2
import tkinter as tk
from tkinter import ttk, messagebox
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ===========================================================
# LOGGING
# ===========================================================
logging.basicConfig(
    filename="attendance.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S")
_log = logging.getLogger(__name__)

# ===========================================================
# CONFIGURATION
# ===========================================================
load_dotenv()

ZOHO_DOMAIN    = os.getenv("ZOHO_DOMAIN",    "zoho.com")
APP_OWNER      = os.getenv("APP_OWNER",      "wavemarkpropertieslimited")
APP_NAME       = os.getenv("APP_NAME",       "real-estate-wages-system")
CLIENT_ID      = os.getenv("ZOHO_CLIENT_ID")
CLIENT_SECRET  = os.getenv("ZOHO_CLIENT_SECRET")
REFRESH_TOKEN  = os.getenv("ZOHO_REFRESH_TOKEN")

WORKERS_REPORT    = "All_Workers"
ATTENDANCE_FORM   = "Daily_Attendance"
ATTENDANCE_REPORT = "Daily_Attendance_Report"
DEFAULT_PROJECT_ID = "4838902000000391493"

TOKEN_CACHE  = {"token": None, "expires_at": 0}
_TOKEN_LOCK  = threading.Lock()

# Derive the TLD from ZOHO_DOMAIN so EU/IN accounts work too
_ZOHO_TLD   = ZOHO_DOMAIN.split(".")[-1]          # "com", "eu", "in" …
ACCOUNTS_URL = f"https://accounts.zoho.{_ZOHO_TLD}"
API_DOMAIN   = f"https://creator.zoho.{_ZOHO_TLD}/api/v2"

CHECKIN_LOCK_FILE = "checkin_today.json"

# ── Shift policy ─────────────────────────────────────────
SHIFT_START_H   = 7
SHIFT_START_M   = 00
SHIFT_HOURS     = 8
GRACE_MINUTES   = 60
EARLY_CHECKOUT_H = 17
EARLY_CHECKOUT_M = 0
AUTO_CHECKOUT_H  = 19
AUTO_CHECKOUT_M  = 0

# ── Performance constants ────────────────────────────────
WORKER_CACHE_TTL = 3600
MAX_POOL_SIZE    = 20
ZOHO_TIMEOUT     = 30
STATS_REFRESH_MS = 8000
LOG_MAX_LINES    = 500
LOCK_WRITE_LOCK  = threading.Lock()

# ===========================================================
# GLOBAL SDK
# ===========================================================
zk = ZKFP2()
try:
    zk.Init()
except Exception as e:
    _log.error(f"Fingerprint SDK Init Error: {e}")
    print(f"Fingerprint SDK Init Error: {e}")

# ===========================================================
# HTTP SESSION — connection pooling + automatic retry
# ===========================================================
def _make_session():
    s = requests.Session()
    retry = Retry(
        total=3, backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PATCH"])
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=MAX_POOL_SIZE,
        pool_maxsize=MAX_POOL_SIZE,
        pool_block=False)
    s.mount("https://", adapter)
    s.mount("http://",  adapter)
    return s

_SESSION = _make_session()

def zoho_request(method, url, retries=3, **kwargs):
    kwargs.setdefault("timeout", ZOHO_TIMEOUT)
    for attempt in range(1, retries + 1):
        try:
            return _SESSION.request(method, url, **kwargs)
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError, OSError) as exc:
            _log.warning(f"zoho_request attempt {attempt}: {exc}")
            if attempt < retries:
                time.sleep(min(2 ** attempt, 8))
    return None


# ===========================================================
# AUTHENTICATION — thread-safe token refresh
# ===========================================================
def _validate_env():
    """Check that required .env variables are present before attempting auth."""
    missing = [k for k, v in {
        "ZOHO_CLIENT_ID":     CLIENT_ID,
        "ZOHO_CLIENT_SECRET": CLIENT_SECRET,
        "ZOHO_REFRESH_TOKEN": REFRESH_TOKEN,
    }.items() if not v]
    if missing:
        _log.error(f"Missing .env variables: {', '.join(missing)}")
        return False
    return True

def get_access_token():
    if not _validate_env():
        return None

    now = time.time()
    with _TOKEN_LOCK:
        if TOKEN_CACHE["token"] and now < TOKEN_CACHE["expires_at"] - 120:
            return TOKEN_CACHE["token"]
        TOKEN_CACHE["token"] = None

    url = f"{ACCOUNTS_URL}/oauth/v2/token"
    data = {
        "refresh_token": REFRESH_TOKEN,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type":    "refresh_token",
    }

    for attempt in range(3):
        r = zoho_request("POST", url, data=data, retries=1)
        if r is None:
            _log.error(f"Token refresh attempt {attempt+1}: no response / timeout")
            time.sleep(3)
            continue

        if r.status_code == 200:
            res = r.json()
            if "access_token" in res:
                with _TOKEN_LOCK:
                    TOKEN_CACHE["token"]      = res["access_token"]
                    TOKEN_CACHE["expires_at"] = now + int(res.get("expires_in", 3600))
                _log.info("Zoho token refreshed OK")
                return TOKEN_CACHE["token"]
            else:
                err = res.get("error", "unknown")
                _log.error(f"Token refresh attempt {attempt+1} HTTP 200 but error={err!r}. "
                           f"Full response: {res}")
                if err == "invalid_client":
                    _log.error(
                        ">>> invalid_client: Your CLIENT_ID or CLIENT_SECRET is wrong, "
                        "or the OAuth client was deleted/deauthorised in Zoho API Console "
                        "(https://api-console.zoho.com). Re-generate credentials and update .env.")
                    return None          # no point retrying
                if err in ("invalid_code", "access_denied"):
                    _log.error(
                        ">>> Refresh token revoked or expired. Re-authorise the app and "
                        "generate a new ZOHO_REFRESH_TOKEN.")
                    return None
        else:
            _log.error(f"Token refresh attempt {attempt+1} HTTP {r.status_code}: {r.text[:300]}")

        time.sleep(3)

    _log.error("Failed to refresh Zoho token after 3 attempts — "
               "check REFRESH_TOKEN / CLIENT_ID / CLIENT_SECRET in .env")
    return None

def auth_headers():
    token = get_access_token()
    if not token:
        _log.error("auth_headers: no token available — all Zoho calls will fail")
        return {}
    return {"Authorization": f"Zoho-oauthtoken {token}"}

# ===========================================================
# LOCAL STATE — in-memory cache + safe file persistence
# ===========================================================
_LOCK_MEM: dict = {}
_LOCK_MEM_DATE: str = ""

def load_lock() -> dict:
    global _LOCK_MEM, _LOCK_MEM_DATE
    today = datetime.now().strftime("%Y-%m-%d")
    if _LOCK_MEM_DATE == today and _LOCK_MEM:
        return _LOCK_MEM

    if os.path.exists(CHECKIN_LOCK_FILE):
        try:
            with open(CHECKIN_LOCK_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today:
                for key in ("checked_in", "checked_out"):
                    if not isinstance(data.get(key), dict):
                        data[key] = {}
                    data[key] = {k: v for k, v in data[key].items()
                                 if isinstance(v, dict)}
                _LOCK_MEM      = data
                _LOCK_MEM_DATE = today
                return _LOCK_MEM
        except Exception as exc:
            _log.warning(f"load_lock read error: {exc}")

    fresh = {"date": today, "checked_in": {}, "checked_out": {}}
    _LOCK_MEM      = fresh
    _LOCK_MEM_DATE = today
    save_lock(fresh)
    return _LOCK_MEM

def save_lock(data: dict):
    global _LOCK_MEM, _LOCK_MEM_DATE
    _LOCK_MEM      = data
    _LOCK_MEM_DATE = data.get("date", "")
    tmp = CHECKIN_LOCK_FILE + ".tmp"
    with LOCK_WRITE_LOCK:
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, CHECKIN_LOCK_FILE)
        except Exception as exc:
            _log.error(f"save_lock error: {exc}")

def get_worker_status(zk_id: str) -> str:
    lock = load_lock()
    key  = str(zk_id)
    if key in lock["checked_out"]:  return "done"
    if key in lock["checked_in"]:   return "checked_in"
    return "none"

def count_early_checkouts(lock=None) -> int:
    if lock is None:
        lock = load_lock()
    now         = datetime.now()
    early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
                              second=0, microsecond=0)
    count = 0
    for info in lock.get("checked_out", {}).values():
        if not isinstance(info, dict):
            continue
        try:
            co_dt = datetime.strptime(info.get("time", ""), "%H:%M:%S").replace(
                year=now.year, month=now.month, day=now.day)
            if co_dt < early_limit:
                count += 1
        except Exception:
            pass
    return count

# ===========================================================
# WORKER CACHE — TTL-based, evicts oldest when full
# ===========================================================
_WORKER_STORE: dict = {}
_WORKER_LOCK  = threading.Lock()

def _wcache_get(uid: str):
    with _WORKER_LOCK:
        e = _WORKER_STORE.get(str(uid))
        if e and (time.time() - e["ts"]) < WORKER_CACHE_TTL:
            return e["worker"]
    return None

def _wcache_set(uid: str, worker: dict):
    with _WORKER_LOCK:
        if len(_WORKER_STORE) >= 2000:
            oldest = sorted(_WORKER_STORE, key=lambda k: _WORKER_STORE[k]["ts"])
            for old_k in oldest[:200]:
                del _WORKER_STORE[old_k]
        _WORKER_STORE[str(uid)] = {"worker": worker, "ts": time.time()}

def _wcache_invalidate(uid: str):
    with _WORKER_LOCK:
        _WORKER_STORE.pop(str(uid), None)

# ===========================================================
# SHIFT HELPERS
# ===========================================================
def is_late(checkin_dt: datetime) -> bool:
    cutoff = checkin_dt.replace(
        hour=SHIFT_START_H, minute=SHIFT_START_M, second=0, microsecond=0
    ) + timedelta(minutes=GRACE_MINUTES)
    return checkin_dt > cutoff

def late_by_str(checkin_dt: datetime) -> str:
    shift_start = checkin_dt.replace(
        hour=SHIFT_START_H, minute=SHIFT_START_M, second=0, microsecond=0)
    delta = max((checkin_dt - shift_start).total_seconds(), 0)
    mins  = int(delta // 60)
    return f"{mins} min late" if mins else "on time"

def overtime_hours(total_hours: float) -> float:
    return max(round(total_hours - SHIFT_HOURS, 4), 0)

# ===========================================================
# ZOHO API
# ===========================================================
def find_worker(zk_user_id, force_refresh: bool = False):
    """
    Look up a worker in Zoho by their ZKTeco User ID.
    Tries multiple criteria formats before falling back to a full-list scan.
    """
    uid = str(zk_user_id).strip()

    if not force_refresh:
        cached = _wcache_get(uid)
        if cached:
            _log.debug(f"find_worker({uid}): cache hit")
            return cached

    hdrs = auth_headers()
    if not hdrs:
        _log.error(f"find_worker({uid}): aborting — no valid Zoho token. "
                   "Check REFRESH_TOKEN / CLIENT_ID / CLIENT_SECRET in .env")
        return None

    url = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/report/{WORKERS_REPORT}"

    try:
        int_id = int(uid)
    except ValueError:
        int_id = None

    criteria_attempts = []
    if int_id is not None:
        criteria_attempts += [
            f"(ZKTeco_User_ID2 == {int_id})",
            f'(ZKTeco_User_ID2 == "{int_id}")',
            f"(Worker_ID == {int_id})",
            f'(Worker_ID == "{int_id}")',
        ]
    criteria_attempts += [
        f'(ZKTeco_User_ID2 == "{uid}")',
        f'(Worker_ID == "{uid}")',
    ]

    for criteria in criteria_attempts:
        _log.info(f"find_worker({uid}): trying criteria={criteria!r}")
        r = zoho_request("GET", url, headers=hdrs, params={"criteria": criteria})
        if not r:
            _log.error(f"find_worker({uid}): request timed out on criteria={criteria!r}")
            continue
        if r.status_code == 401:
            _log.warning(f"find_worker: HTTP 401 for criteria: {criteria}")
            with _TOKEN_LOCK:
                TOKEN_CACHE["token"]      = None
                TOKEN_CACHE["expires_at"] = 0
            hdrs = auth_headers()         # try refreshing once
            if not hdrs:
                _log.error(f"find_worker({uid}): token refresh failed, aborting")
                return None
            r = zoho_request("GET", url, headers=hdrs, params={"criteria": criteria})
            if not r or r.status_code != 200:
                _log.warning(f"find_worker: criteria failed for ID '{uid}', trying full fetch…")
                continue
        if r.status_code != 200:
            _log.error(f"find_worker({uid}): HTTP {r.status_code} — {r.text[:300]}")
            continue

        data = r.json().get("data", [])
        if data:
            _log.info(f"find_worker({uid}): found via criteria={criteria!r}")
            _wcache_set(uid, data[0])
            return data[0]

    # ── Last resort: fetch ALL workers and match manually ──
    _log.warning(f"find_worker({uid}): all criteria failed — attempting full worker scan")
    r = zoho_request("GET", url, headers=hdrs)
    if r and r.status_code == 200:
        all_workers = r.json().get("data", [])
        _log.info(f"find_worker({uid}): full scan returned {len(all_workers)} worker(s)")
        for w in all_workers:
            zk_val  = str(w.get("ZKTeco_User_ID2", "")).strip()
            wid_val = str(w.get("Worker_ID",       "")).strip()
            zk_val_clean  = zk_val.split(".")[0]
            wid_val_clean = wid_val.split(".")[0]
            if uid in (zk_val, wid_val, zk_val_clean, wid_val_clean):
                _log.info(f"find_worker({uid}): matched via full scan "
                          f"(ZKTeco_User_ID2={zk_val!r}, Worker_ID={wid_val!r})")
                _wcache_set(uid, w)
                return w
    else:
        _log.error(f"find_worker({uid}): full scan HTTP "
                   f"{r.status_code if r else 'timeout'}")

    _log.error(f"find_worker({uid}): worker NOT found after all attempts. "
               f"Verify ZKTeco_User_ID2 / Worker_ID field in Zoho for ID={uid}")
    return None


def search_workers_by_name(name_query: str) -> list:
    """Search Zoho for workers whose Full_Name contains the query string."""
    url  = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/report/{WORKERS_REPORT}"
    hdrs = auth_headers()
    if not hdrs:
        _log.error("search_workers_by_name: no valid token — cannot search")
        return []

    q_lower = name_query.strip().lower()
    results = []

    # Try Zoho criteria-based search first
    for criteria in [
        f'(Full_Name contains "{name_query}")',
        f'(Full_Name starts_with "{name_query}")',
    ]:
        try:
            r = zoho_request("GET", url, headers=hdrs, params={"criteria": criteria})
            if r and r.status_code == 200:
                data = r.json().get("data", [])
                if data:
                    _log.info(f"search_workers_by_name: found {len(data)} via criteria={criteria!r}")
                    return data
        except Exception as exc:
            _log.warning(f"search_workers_by_name criteria error: {exc}")

    # Fallback: fetch ALL workers and filter locally
    try:
        _log.info("search_workers_by_name: falling back to full worker scan")
        r = zoho_request("GET", url, headers=hdrs)
        if r and r.status_code == 200:
            all_workers = r.json().get("data", [])
            _log.info(f"search_workers_by_name: full scan returned {len(all_workers)} workers")
            results = [
                w for w in all_workers
                if q_lower in str(w.get("Full_Name", "")).lower()
                or q_lower in str(w.get("ZKTeco_User_ID2", "")).lower()
                or q_lower in str(w.get("Worker_ID", "")).lower()
            ]
        elif r:
            _log.error(f"search_workers_by_name: full scan HTTP {r.status_code}: {r.text[:200]}")
        else:
            _log.error("search_workers_by_name: full scan timed out")
    except Exception as exc:
        _log.error(f"search_workers_by_name fallback error: {exc}")

    return results


def _extract_zoho_id(res_json):
    data = res_json.get("data")
    if isinstance(data, dict):
        return data.get("ID") or data.get("id")
    if isinstance(data, list) and data:
        return data[0].get("ID") or data[0].get("id")
    return res_json.get("ID") or res_json.get("id")


def _find_record_in_zoho(worker_id, today_display, today_iso, hdrs, _log_fn=None):
    def dbg(msg):
        _log.debug(f"[ZOHO SEARCH] {msg}")
        if _log_fn:
            _log_fn(f"[search] {msg}", "warn")

    report_url   = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/report/{ATTENDANCE_REPORT}"
    criteria_list = [
        f'(Worker_Name == "{worker_id}" && Date == "{today_display}")',
        f'(Worker_Name == "{worker_id}" && Date == "{today_iso}")',
        f'(Worker_ID_Lookup == "{worker_id}" && Date == "{today_display}")',
        f'(Worker_ID_Lookup == "{worker_id}" && Date == "{today_iso}")',
        f'(Worker_Name == "{worker_id}")',
        f'(Worker_ID_Lookup == "{worker_id}")',
    ]

    for crit in criteria_list:
        r = zoho_request("GET", report_url, headers=hdrs, params={"criteria": crit})
        if not r or r.status_code != 200:
            continue
        recs = r.json().get("data", [])
        if not recs:
            continue
        for rec in recs:
            d = str(rec.get("Date", rec.get("Date_field", ""))).strip()
            if d in (today_display, today_iso):
                return rec["ID"]
        if len(recs) == 1:
            return recs[0]["ID"]

    for date_val in (today_display, today_iso):
        r = zoho_request("GET", report_url, headers=hdrs,
                         params={"criteria": f'(Date == "{date_val}")'})
        if not r or r.status_code != 200:
            continue
        for rec in r.json().get("data", []):
            for field in ("Worker_Name", "Worker_ID_Lookup", "Worker",
                          "Worker_Name.ID", "Worker_ID"):
                val = rec.get(field)
                if isinstance(val, dict):
                    val = val.get("ID") or val.get("id") or val.get("display_value", "")
                if str(val).strip() == str(worker_id).strip():
                    return rec["ID"]

    dbg("All strategies exhausted — not found.")
    return None

# ===========================================================
# ATTENDANCE LOGIC
# ===========================================================
def log_attendance(worker_id, zk_id, project_id, full_name, action, _log_fn=None):
    now     = datetime.now()
    zk_key  = str(zk_id)
    today_display = now.strftime("%d-%b-%Y")
    today_iso     = now.strftime("%Y-%m-%d")

    if action == "checkin":
        form_url     = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/form/{ATTENDANCE_FORM}"
        checkin_time = now.strftime("%d-%b-%Y %H:%M:%S")
        hdrs         = auth_headers()
        if not hdrs:
            return False, "Could not refresh Zoho token."

        worker_late = is_late(now)
        late_note   = late_by_str(now)
        late_mins   = int(max(
            (now - now.replace(hour=SHIFT_START_H, minute=SHIFT_START_M,
                               second=0, microsecond=0)).total_seconds() // 60, 0
        )) if worker_late else 0

        payload = {"data": {
            "Worker_Name":      worker_id,
            "Projects":         project_id,
            "Date":             today_display,
            "First_In":         checkin_time,
            "Worker_Full_Name": full_name,
            "Is_Late":          "true" if worker_late else "false",
            "Late_By_Minutes":  late_mins,
        }}

        r = zoho_request("POST", form_url, headers=hdrs, json=payload)
        if r and r.status_code in (200, 201):
            res          = r.json()
            zoho_rec_id  = _extract_zoho_id(res)
            if not zoho_rec_id:
                zoho_rec_id = _find_record_in_zoho(
                    worker_id, today_display, today_iso, auth_headers(), _log_fn)

            lock = load_lock()
            lock["checked_in"][zk_key] = {
                "time":      checkin_time,
                "zoho_id":   zoho_rec_id,
                "worker_id": worker_id,
                "name":      full_name,
                "is_late":   worker_late,
                "late_note": late_note,
            }
            save_lock(lock)
            _log.info(f"CHECKIN OK: {full_name} late={worker_late}")
            status_line = f"⚠ {late_note}" if worker_late else "✓ On time"
            return True, (f"✅ {full_name} checked IN at {now.strftime('%H:%M')}\n"
                          f"   {status_line}")

        err = r.text[:200] if r else "Timeout"
        _log.error(f"CHECKIN FAIL: {full_name}: {err}")
        return False, f"Check-in failed: {err}"

    elif action == "checkout":
        lock = load_lock()
        info = lock["checked_in"].get(zk_key)
        if not info:
            return False, "No check-in record found for today."

        hdrs = auth_headers()
        if not hdrs:
            return False, "Could not refresh Zoho token."

        att_record_id  = info.get("zoho_id")
        stored_worker  = info.get("worker_id", worker_id)

        def dbg(msg):
            _log.debug(f"[CHECKOUT] {msg}")
            if _log_fn:
                _log_fn(f"[checkout] {msg}", "warn")

        if att_record_id:
            direct_url = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
                          f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
            r_chk = zoho_request("GET", direct_url, headers=hdrs)
            if not (r_chk and r_chk.status_code == 200):
                dbg("stored ID invalid — searching...")
                att_record_id = None

        if not att_record_id:
            att_record_id = _find_record_in_zoho(
                stored_worker, today_display, today_iso, hdrs, _log_fn)
            if att_record_id:
                lock["checked_in"][zk_key]["zoho_id"] = att_record_id
                save_lock(lock)

        if not att_record_id:
            form_index_url = f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}/form/{ATTENDANCE_FORM}"
            for date_val in (today_display, today_iso):
                crit = f'(Worker_Name == "{stored_worker}" && Date == "{date_val}")'
                r_f  = zoho_request("GET", form_index_url, headers=hdrs,
                                    params={"criteria": crit})
                if r_f and r_f.status_code == 200:
                    frecs = r_f.json().get("data", [])
                    if frecs:
                        att_record_id = frecs[0].get("ID")
                        lock["checked_in"][zk_key]["zoho_id"] = att_record_id
                        save_lock(lock)
                        break

        if not att_record_id:
            return False, (f"Could not locate attendance record in Zoho.\n"
                           f"Worker: {full_name}  Date: {today_display}\n"
                           "Check the log for [checkout] diagnostics.")

        try:
            dt_in = datetime.strptime(info.get("time", ""), "%d-%b-%Y %H:%M:%S")
        except Exception:
            dt_in = now

        total_hours = max((now - dt_in).total_seconds() / 3600, 0.01)
        ot_hours    = overtime_hours(total_hours)
        total_str   = f"{int(total_hours)}h {int((total_hours % 1) * 60)}m"
        ot_str      = f"{int(ot_hours)}h {int((ot_hours % 1) * 60)}m" if ot_hours else "None"
        total_hours_rounded = round(total_hours, 2)
        ot_hours_rounded    = round(ot_hours, 2)

        update_url = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
                      f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
        r_u = zoho_request("PATCH", update_url, headers=hdrs, json={"data": {
            "Last_Out":       now.strftime("%d-%b-%Y %H:%M:%S"),
            "Total_Hours":    total_hours_rounded,
            "Overtime_Hours": ot_hours_rounded,
        }})

        http_code = r_u.status_code if r_u else "timeout"
        body_raw  = r_u.text[:300]  if r_u else "No response"

        if r_u and r_u.status_code == 200:
            body = r_u.json()
            code = body.get("code")
            if code == 3000:
                checkout_hms = now.strftime("%H:%M:%S")
                lock["checked_in"].pop(zk_key, None)
                lock["checked_out"][zk_key] = {
                    "time":           checkout_hms,
                    "name":           full_name,
                    "total_hours":    total_hours_rounded,
                    "overtime_hours": ot_hours_rounded,
                    "is_late":        info.get("is_late", False),
                    "late_note":      info.get("late_note", ""),
                    "checkin_time":   info.get("time", ""),
                }
                save_lock(lock)
                _log.info(f"CHECKOUT OK: {full_name} hours={total_hours_rounded}")
                ot_line     = f"   Overtime: {ot_str}" if ot_hours else ""
                early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
                                          second=0, microsecond=0)
                early_note  = (f"\n   ⚠ Early checkout "
                               f"(before {EARLY_CHECKOUT_H:02d}:{EARLY_CHECKOUT_M:02d})"
                               if now < early_limit else "")
                return True, (f"🚪 {full_name} checked OUT at {now.strftime('%H:%M')}\n"
                              f"   Total time: {total_str}\n{ot_line}{early_note}")

            errors = body.get("error", body.get("message", ""))
            return False, (f"Zoho rejected update (code {code}).\nError: {errors}\n"
                           f"Worker: {full_name}  Hours: {total_hours_rounded}")

        _log.error(f"CHECKOUT FAIL: {full_name} HTTP {http_code}: {body_raw}")
        return False, f"Check-out PATCH failed (HTTP {http_code}): {body_raw}"

    return False, "Unknown action."

# ===========================================================
# AUTO-CHECKOUT — concurrent batch processing
# ===========================================================
def run_auto_checkout(gui_log_fn=None, done_cb=None):
    now           = datetime.now()
    today_display = now.strftime("%d-%b-%Y")
    today_iso     = now.strftime("%Y-%m-%d")
    checkout_ts   = now.strftime("%d-%b-%Y %H:%M:%S")
    checkout_hms  = now.strftime("%H:%M:%S")

    lock    = load_lock()
    pending = {k: v for k, v in lock.get("checked_in", {}).items()
               if isinstance(v, dict)}

    if not pending:
        if done_cb:
            done_cb([], [])
        return

    def info(msg):
        _log.info(msg)
        if gui_log_fn:
            gui_log_fn(msg, "warn")

    info(f"AUTO-CHECKOUT: {len(pending)} worker(s) at {now.strftime('%H:%M')}")

    success_names, fail_names = [], []
    result_lock = threading.Lock()
    sem         = threading.Semaphore(8)

    def _checkout_one(zk_key, winfo):
        with sem:
            full_name = winfo.get("name",      zk_key)
            worker_id = winfo.get("worker_id", zk_key)
            att_record_id = winfo.get("zoho_id")
            hdrs = auth_headers()

            if att_record_id:
                du = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
                      f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
                rc = zoho_request("GET", du, headers=hdrs)
                if not (rc and rc.status_code == 200):
                    att_record_id = None

            if not att_record_id:
                att_record_id = _find_record_in_zoho(
                    worker_id, today_display, today_iso, hdrs)

            if not att_record_id:
                info(f"  SKIP {full_name}: no Zoho record")
                with result_lock:
                    fail_names.append(full_name)
                return

            try:
                dt_in = datetime.strptime(winfo.get("time", ""), "%d-%b-%Y %H:%M:%S")
            except Exception:
                dt_in = now

            total_h = max((now - dt_in).total_seconds() / 3600, 0.01)
            ot_h    = overtime_hours(total_h)

            uu = (f"{API_DOMAIN}/{APP_OWNER}/{APP_NAME}"
                  f"/report/{ATTENDANCE_REPORT}/{att_record_id}")
            ru = zoho_request("PATCH", uu, headers=hdrs, json={"data": {
                "Last_Out":       checkout_ts,
                "Total_Hours":    round(total_h, 2),
                "Overtime_Hours": round(ot_h, 2),
            }})

            if ru and ru.status_code == 200 and ru.json().get("code") == 3000:
                lk = load_lock()
                lk["checked_in"].pop(zk_key, None)
                lk["checked_out"][zk_key] = {
                    "time":           checkout_hms,
                    "name":           full_name,
                    "total_hours":    round(total_h, 2),
                    "overtime_hours": round(ot_h, 2),
                    "is_late":        winfo.get("is_late", False),
                    "late_note":      winfo.get("late_note", ""),
                    "checkin_time":   winfo.get("time", ""),
                    "auto_checkout":  True,
                }
                save_lock(lk)
                h_str = f"{int(total_h)}h {int((total_h % 1) * 60)}m"
                info(f"  OK {full_name} -- {h_str}")
                with result_lock:
                    success_names.append(full_name)
            else:
                code = ru.status_code if ru else "timeout"
                info(f"  FAIL {full_name} HTTP {code}")
                with result_lock:
                    fail_names.append(full_name)

    threads = [threading.Thread(target=_checkout_one, args=(k, v), daemon=True)
               for k, v in pending.items()]
    for t in threads: t.start()
    for t in threads: t.join()

    info(f"AUTO-CHECKOUT done: {len(success_names)} OK, {len(fail_names)} failed")
    if done_cb:
        done_cb(success_names, fail_names)

# ===========================================================
# DAILY SUMMARY EXPORT
# ===========================================================
def export_daily_summary():
    lock     = load_lock()
    today    = lock.get("date", datetime.now().strftime("%Y-%m-%d"))
    filename = f"attendance_{today}.csv"
    rows     = []
    now      = datetime.now()
    early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
                              second=0, microsecond=0)

    for zk_id, info in lock.get("checked_out", {}).items():
        if not isinstance(info, dict):
            continue
        co_str   = info.get("time", "")
        is_early = False
        try:
            co_dt    = datetime.strptime(co_str, "%H:%M:%S").replace(
                year=now.year, month=now.month, day=now.day)
            is_early = co_dt < early_limit
        except Exception:
            pass
        rows.append({
            "ZK_ID":          zk_id,
            "Name":           info.get("name", ""),
            "Check-In":       info.get("checkin_time", ""),
            "Check-Out":      co_str,
            "Total Hours":    info.get("total_hours", ""),
            "Overtime Hours": info.get("overtime_hours", 0),
            "Late?":          "Yes" if info.get("is_late") else "No",
            "Late Note":      info.get("late_note", ""),
            "Early Checkout?":"Yes" if is_early else "No",
            "Auto Checkout?": "Yes" if info.get("auto_checkout") else "No",
            "Status":         "Complete",
        })

    for zk_id, info in lock.get("checked_in", {}).items():
        if not isinstance(info, dict):
            continue
        rows.append({
            "ZK_ID":          zk_id,
            "Name":           info.get("name", ""),
            "Check-In":       info.get("time", ""),
            "Check-Out":      "---",
            "Total Hours":    "---",
            "Overtime Hours": "---",
            "Late?":          "Yes" if info.get("is_late") else "No",
            "Late Note":      info.get("late_note", ""),
            "Early Checkout?":"---",
            "Auto Checkout?": "---",
            "Status":         "Still In",
        })

    if not rows:
        return None

    fieldnames = ["ZK_ID", "Name", "Check-In", "Check-Out", "Total Hours",
                  "Overtime Hours", "Late?", "Late Note", "Early Checkout?",
                  "Auto Checkout?", "Status"]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    _log.info(f"CSV exported: {filename} ({len(rows)} rows)")
    return filename

# ===========================================================
# COLOUR PALETTE
# ===========================================================
BG      = "#07090f"; CARD    = "#0c1018"; CARD2   = "#10151f"
BORDER  = "#1c2438"; BORDER2 = "#243048"
ACCENT  = "#3b82f6"; ACCENT_DIM = "#172554"; ACCENT2 = "#60a5fa"
GREEN   = "#10b981"; GREEN2  = "#34d399"; GREEN_DIM  = "#052e1c"
RED     = "#f43f5e"; RED2    = "#fb7185"; RED_DIM    = "#4c0519"
ORANGE  = "#f59e0b"; ORANGE2 = "#fbbf24"; ORANGE_DIM = "#3d1f00"
CYAN2   = "#67e8f9"; CYAN_DIM = "#083344"
TEXT    = "#e2e8f0"; TEXT2   = "#94a3b8"; MUTED   = "#3d4f69"
WHITE   = "#ffffff"; GOLD    = "#f59e0b"; GOLD2   = "#fde68a"
PURPLE  = "#a78bfa"; PURPLE_DIM = "#2e1065"
TEAL    = "#2dd4bf"; TEAL_DIM   = "#042f2e"

# ===========================================================
# UI HELPERS
# ===========================================================
def _btn_hover(btn, bg_on, fg_on, bg_off, fg_off):
    btn.bind("<Enter>", lambda _: btn.config(bg=bg_on,  fg=fg_on))
    btn.bind("<Leave>", lambda _: btn.config(bg=bg_off, fg=fg_off))

def _make_sep(parent, color=BORDER, height=1):
    tk.Frame(parent, bg=color, height=height).pack(fill=tk.X)

def _initials(name: str) -> str:
    parts = name.strip().split()
    if not parts:      return "??"
    if len(parts) == 1: return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()

# ===========================================================
# FORGOTTEN ID DIALOG
# ===========================================================
class ForgottenIDDialog(tk.Toplevel):
    def __init__(self, parent, on_select):
        super().__init__(parent)
        self.on_select  = on_select
        self._results   = []
        self._search_job = None
        self.title("Find Worker by Name")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.focus_force()
        W, H = 520, 460
        sw, sh = parent.winfo_screenwidth(), parent.winfo_screenheight()
        self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self._build()
        self.name_entry.focus_set()

    def _build(self):
        tk.Frame(self, bg=TEAL, height=3).pack(fill=tk.X)
        hdr = tk.Frame(self, bg=CARD, padx=20, pady=14); hdr.pack(fill=tk.X)
        tk.Label(hdr, text="🔍 FORGOTTEN ID LOOKUP",
                 font=("Courier", 11, "bold"), bg=CARD, fg=TEAL).pack(anchor="w")
        tk.Label(hdr, text="Type your name below — matching workers will appear instantly",
                 font=("Courier", 8), bg=CARD, fg=TEXT2).pack(anchor="w", pady=(3, 0))
        _make_sep(self, BORDER2)

        sf = tk.Frame(self, bg=BG, padx=20, pady=14); sf.pack(fill=tk.X)
        tk.Label(sf, text="NAME", font=("Courier", 8, "bold"),
                 bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 5))
        eb = tk.Frame(sf, bg=TEAL, padx=2, pady=2); eb.pack(fill=tk.X)
        ei = tk.Frame(eb, bg=CARD2); ei.pack(fill=tk.X)
        self._name_var = tk.StringVar()
        self._name_var.trace_add("write", lambda *_: self._on_type())
        self.name_entry = tk.Entry(ei, textvariable=self._name_var,
                                   font=("Courier", 16, "bold"),
                                   bg=CARD2, fg=WHITE, insertbackground=TEAL,
                                   bd=0, width=28)
        self.name_entry.pack(padx=12, pady=10)
        self.name_entry.bind("<Escape>", lambda _: self.destroy())
        self.name_entry.bind("<Down>",   self._focus_list)

        self._status_lbl = tk.Label(sf, text="Start typing to search…",
                                    font=("Courier", 8), bg=BG, fg=MUTED)
        self._status_lbl.pack(anchor="w", pady=(6, 0))
        _make_sep(self, BORDER)

        lf = tk.Frame(self, bg=BG, padx=20, pady=10); lf.pack(fill=tk.BOTH, expand=True)
        tk.Label(lf, text="RESULTS — click a name to load their ID",
                 font=("Courier", 7, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 6))

        style = ttk.Style(self); style.theme_use("default")
        style.configure("FID.Treeview", background=CARD2, foreground=TEXT,
                         fieldbackground=CARD2, rowheight=34,
                         font=("Courier", 10), borderwidth=0)
        style.configure("FID.Treeview.Heading", background=CARD,
                         foreground=TEAL, font=("Courier", 8, "bold"), relief="flat")
        style.map("FID.Treeview",
                  background=[("selected", TEAL_DIM)],
                  foreground=[("selected", TEAL)])

        cols = ("Name", "ZK ID", "Status")
        self._tree = ttk.Treeview(lf, columns=cols, show="headings",
                                  style="FID.Treeview", selectmode="browse", height=6)
        self._tree.heading("Name",   text="FULL NAME")
        self._tree.heading("ZK ID",  text="WORKER ID")
        self._tree.heading("Status", text="TODAY")
        self._tree.column("Name",   width=270, anchor="w",      stretch=True)
        self._tree.column("ZK ID",  width=90,  anchor="center")
        self._tree.column("Status", width=110, anchor="center")
        for tag, col in [("in", ORANGE2), ("out", GREEN2), ("none", ACCENT2)]:
            self._tree.tag_configure(tag, foreground=col)

        vsb = ttk.Scrollbar(lf, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.bind("<Double-1>",   self._on_select)
        self._tree.bind("<Return>",     self._on_select)
        self._tree.bind("<Up>",         self._up_to_entry)
        _make_sep(self, BORDER2)

        ft = tk.Frame(self, bg=CARD, padx=20, pady=10); ft.pack(fill=tk.X)
        btn_sel = tk.Button(ft, text="✔ USE SELECTED ID",
                            font=("Courier", 9, "bold"), relief=tk.FLAT,
                            bg=TEAL_DIM, fg=TEAL,
                            activebackground=TEAL, activeforeground=BG,
                            cursor="hand2", padx=14, pady=6, command=self._on_select)
        btn_sel.pack(side=tk.LEFT)
        _btn_hover(btn_sel, TEAL, BG, TEAL_DIM, TEAL)

        btn_cancel = tk.Button(ft, text="✕ CANCEL",
                               font=("Courier", 9, "bold"), relief=tk.FLAT,
                               bg=BORDER, fg=TEXT2,
                               activebackground=RED_DIM, activeforeground=RED,
                               cursor="hand2", padx=14, pady=6, command=self.destroy)
        btn_cancel.pack(side=tk.RIGHT)
        _btn_hover(btn_cancel, RED_DIM, RED, BORDER, TEXT2)

    def _focus_list(self, _=None):
        children = self._tree.get_children()
        if children:
            self._tree.focus(children[0])
            self._tree.selection_set(children[0])
            self._tree.focus_set()

    def _up_to_entry(self, _=None):
        idx = self._tree.index(self._tree.focus())
        if idx == 0:
            self.name_entry.focus_set()

    def _on_type(self):
        if self._search_job:
            self.after_cancel(self._search_job)
        query = self._name_var.get().strip()
        if len(query) < 2:
            self._status_lbl.config(text="Type at least 2 characters…", fg=MUTED)
            self._tree.delete(*self._tree.get_children())
            return
        self._status_lbl.config(text="Searching…", fg=ORANGE2)
        self._search_job = self.after(
            500, lambda: threading.Thread(
                target=self._do_search, args=(query,), daemon=True).start())

    def _do_search(self, query: str):
        try:
            workers = search_workers_by_name(query)
        except Exception as exc:
            _log.error(f"ForgottenIDDialog search error: {exc}")
            workers = []
        # schedule UI update safely — only if dialog still open
        try:
            self.after(0, lambda: self._populate(query, workers))
        except Exception:
            pass  # dialog was closed before callback scheduled

    def _populate(self, query: str, workers: list):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._results = workers
        self._tree.delete(*self._tree.get_children())
        if not workers:
            self._status_lbl.config(
                text=f'No workers found matching "{query}"', fg=RED2)
            return
        seen_ids = set()
        for w in workers:
            name  = w.get("Full_Name", "—")
            zk_id = str(w.get("ZKTeco_User_ID2", "")).strip()
            if not zk_id or zk_id in ("0", "None", ""):
                zk_id = str(w.get("Worker_ID", "—")).strip()
            # deduplicate by zk_id
            iid = zk_id if zk_id not in seen_ids else f"{zk_id}_{name}"
            seen_ids.add(zk_id)
            status = get_worker_status(zk_id)
            labels = {"checked_in": "⏱ IN", "done": "✔ OUT", "none": "— —"}
            tag    = {"checked_in": "in", "done": "out", "none": "none"}.get(status, "none")
            try:
                self._tree.insert("", tk.END,
                                  values=(name, zk_id, labels.get(status, "—")),
                                  tags=(tag,), iid=iid)
            except Exception:
                self._tree.insert("", tk.END,
                                  values=(name, zk_id, labels.get(status, "—")),
                                  tags=(tag,))
        count = len(workers)
        if count == 1 and query == self._name_var.get().strip():
            self._status_lbl.config(text="✔ 1 match found — filling ID automatically…", fg=TEAL)
            first = self._tree.get_children()[0]
            self._tree.selection_set(first)
            self._tree.focus(first)
            self.after(600, self._on_select)
            return
        self._status_lbl.config(
            text=f"Found {count} worker{'s' if count != 1 else ''} — double-click or Enter to select",
            fg=TEAL)

    def _on_select(self, _=None):
        sel = self._tree.selection()
        if not sel:
            return
        # Get ZK ID from the actual row values (column index 1), not the iid
        try:
            zk_id = self._tree.item(sel[0], "values")[1]
        except Exception:
            zk_id = sel[0]
        if zk_id and zk_id not in ("—", "", "None"):
            self.destroy()
            self.on_select(str(zk_id))

# ===========================================================
# FINGERPRINT CANVAS
# ===========================================================
class FingerprintCanvas(tk.Canvas):
    SIZE = 140
    def __init__(self, parent, **kwargs):
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                         bg=CARD2, highlightthickness=0, **kwargs)
        self._cx = self._cy = self.SIZE // 2
        self._angle = 0; self._state = "idle"; self._phase = 0
        self._arc_items = []
        self._draw_base(); self._animate()

    def _draw_base(self):
        cx, cy = self._cx, self._cy
        self.delete("fp")
        self.create_oval(cx-64, cy-64, cx+64, cy+64,
                         outline=BORDER2, width=1, tags="fp")
        arc_defs = [(10,0,300,2),(18,20,280,2),(26,30,270,1),
                    (34,15,290,1),(42,25,265,1),(50,10,285,1),(58,35,250,1)]
        self._arc_items = []
        for r, start, extent, w in arc_defs:
            item = self.create_arc(cx-r, cy-r, cx+r, cy+r,
                                   start=start, extent=extent,
                                   outline=MUTED, width=w,
                                   style="arc", tags="fp")
            self._arc_items.append(item)
        self._centre = self.create_oval(cx-5, cy-5, cx+5, cy+5,
                                        fill=MUTED, outline="", tags="fp")
        self._spin = self.create_arc(cx-58, cy-58, cx+58, cy+58,
                                     start=0, extent=0,
                                     outline=ACCENT, width=3,
                                     style="arc", tags="fp")

    def start(self):    self._state = "scanning"
    def stop_ok(self):
        self._state = "ok"
        for item in self._arc_items: self.itemconfig(item, outline=GREEN2)
        self.itemconfig(self._centre, fill=GREEN2)
        self.itemconfig(self._spin, extent=0)
    def stop_err(self, _=""):
        self._state = "error"
        for item in self._arc_items: self.itemconfig(item, outline=RED2)
        self.itemconfig(self._centre, fill=RED2)
        self.itemconfig(self._spin, extent=0)
    def reset(self):
        self._state = "idle"; self._angle = 0; self._draw_base()

    def _animate(self):
        self._phase = (self._phase + 1) % 120
        if self._state == "scanning":
            self._angle = (self._angle + 6) % 360
            sweep = int(200 * abs(math.sin(math.radians(self._angle))))
            self.itemconfig(self._spin, start=self._angle, extent=sweep, outline=ACCENT)
            for i, item in enumerate(self._arc_items):
                a  = 0.3 + 0.7 * abs(math.sin(math.radians((self._phase + i*10) * 4)))
                rv = int(int(ACCENT[1:3], 16) * a)
                gv = int(int(ACCENT[3:5], 16) * a)
                bv = int(int(ACCENT[5:7], 16) * a)
                self.itemconfig(item, outline=f"#{rv:02x}{gv:02x}{bv:02x}")
            a2 = 0.4 + 0.6 * abs(math.sin(math.radians(self._phase * 3)))
            rv = int(int(ACCENT[1:3], 16) * a2)
            gv = int(int(ACCENT[3:5], 16) * a2)
            bv = int(int(ACCENT[5:7], 16) * a2)
            self.itemconfig(self._centre, fill=f"#{rv:02x}{gv:02x}{bv:02x}")
        elif self._state == "ok":
            a  = 0.6 + 0.4 * abs(math.sin(math.radians(self._phase * 2)))
            rv = int(int(GREEN2[1:3], 16) * a)
            gv = int(int(GREEN2[3:5], 16) * a)
            bv = int(int(GREEN2[5:7], 16) * a)
            col = f"#{rv:02x}{gv:02x}{bv:02x}"
            for item in self._arc_items: self.itemconfig(item, outline=col)
            self.itemconfig(self._centre, fill=col)
        elif self._state == "error":
            a  = 0.4 + 0.6 * abs(math.sin(math.radians(self._phase * 6)))
            rv = int(int(RED2[1:3], 16) * a)
            gv = int(int(RED2[3:5], 16) * a)
            bv = int(int(RED2[5:7], 16) * a)
            col = f"#{rv:02x}{gv:02x}{bv:02x}"
            for item in self._arc_items: self.itemconfig(item, outline=col)
            self.itemconfig(self._centre, fill=col)
        else:
            a  = 0.25 + 0.20 * abs(math.sin(math.radians(self._phase * 1.5)))
            rv = min(int(int(MUTED[1:3], 16) * a * 2.5), 255)
            gv = min(int(int(MUTED[3:5], 16) * a * 2.5), 255)
            bv = min(int(int(MUTED[5:7], 16) * a * 2.5), 255)
            col = f"#{rv:02x}{gv:02x}{bv:02x}"
            for item in self._arc_items: self.itemconfig(item, outline=col)
            self.itemconfig(self._spin, extent=0)
        self.after(30, self._animate)

# ===========================================================
# PULSING LED
# ===========================================================
class PulseLED(tk.Canvas):
    SIZE = 12
    def __init__(self, parent, color=ACCENT):
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                         bg=parent.cget("bg"), highlightthickness=0)
        r = self.SIZE // 2
        self._dot   = self.create_oval(2, 2, r*2-2, r*2-2, fill=color, outline="")
        self._color = color; self._phase = 0
        self._pulse()

    def set_color(self, c):
        self._color = c
        self.itemconfig(self._dot, fill=c)

    def _pulse(self):
        self._phase = (self._phase + 1) % 60
        a = 0.55 + 0.45 * abs((self._phase % 60) - 30) / 30
        c = self._color
        try:
            rv = int(int(c[1:3], 16) * a)
            gv = int(int(c[3:5], 16) * a)
            bv = int(int(c[5:7], 16) * a)
            self.itemconfig(self._dot, fill=f"#{rv:02x}{gv:02x}{bv:02x}")
        except Exception:
            pass
        self.after(50, self._pulse)

# ===========================================================
# DONUT RING
# ===========================================================
class DonutRing(tk.Canvas):
    SIZE = 80
    def __init__(self, parent, **kwargs):
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                         bg=CARD2, highlightthickness=0, **kwargs)
        self._val = 0.0; self._color = GREEN2; self._phase = 0
        self._draw(0); self._tick()

    def set_value(self, fraction, color=GREEN2):
        self._val = max(0.0, min(1.0, fraction)); self._color = color

    def _draw(self, fraction):
        self.delete("all")
        cx = cy = self.SIZE // 2; r = cx - 6
        self.create_arc(cx-r, cy-r, cx+r, cy+r,
                        start=0, extent=359.9, outline=BORDER2, width=10, style="arc")
        if fraction > 0:
            self.create_arc(cx-r, cy-r, cx+r, cy+r,
                            start=90, extent=-(fraction * 359.9),
                            outline=self._color, width=10, style="arc")
        self.create_text(cx, cy, text=f"{int(fraction*100)}%",
                         font=("Courier", 11, "bold"),
                         fill=self._color if fraction > 0 else MUTED)

    def _tick(self):
        self._phase += 1; self._draw(self._val); self.after(150, self._tick)

# ===========================================================
# ADMIN PANEL  (includes Daily Report tab)
# ===========================================================
class AdminPanel(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Attendance Command Center")
        self.configure(bg="#ffffff"); self.resizable(True, True)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        W, H   = min(sw, 1200), min(sh, 760)
        self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self._all_rows  = []; self._sort_col = None; self._sort_asc = True
        self._build(); self.refresh()

    def _build(self):
        # ── header ──────────────────────────────────────────────────
        hdr = tk.Frame(self, bg="#f8f9fa"); hdr.pack(fill=tk.X)
        tk.Frame(hdr, bg=PURPLE, height=2).pack(fill=tk.X)
        hi  = tk.Frame(hdr, bg="#f8f9fa", padx=24, pady=14); hi.pack(fill=tk.X)
        lf  = tk.Frame(hi, bg="#f8f9fa"); lf.pack(side=tk.LEFT)
        tk.Label(lf, text="ATTENDANCE COMMAND CENTER",
                 font=("Courier", 13, "bold"), bg="#f8f9fa", fg="#212529").pack(anchor="w")
        self.sub_lbl = tk.Label(lf, text="", font=("Courier", 8), bg="#f8f9fa", fg="#6c757d")
        self.sub_lbl.pack(anchor="w", pady=(2, 0))
        rf = tk.Frame(hi, bg="#f8f9fa"); rf.pack(side=tk.RIGHT)
        for txt, cmd, bg_, fg_ in [
            ("↻ REFRESH",   self.refresh,  ACCENT_DIM, ACCENT2),
            ("⬇ EXPORT CSV", self._export,  GREEN_DIM,  GREEN2),
            ("✕ CLOSE",     self.destroy,  BORDER,     TEXT2)]:
            b = tk.Button(rf, text=txt, font=("Courier", 9, "bold"), relief=tk.FLAT,
                          bg=bg_, fg=fg_, cursor="hand2", padx=14, pady=6, command=cmd)
            b.pack(side=tk.LEFT, padx=(0, 6))

        # ── notebook tabs ────────────────────────────────────────────
        style = ttk.Style(self); style.theme_use("default")
        style.configure("Admin.TNotebook",        background="#ffffff", borderwidth=0)
        style.configure("Admin.TNotebook.Tab",    background="#e2e8f0", foreground="#6c757d",
                        font=("Courier", 9, "bold"), padding=[18, 8])
        style.map("Admin.TNotebook.Tab",
                  background=[("selected", "#ffffff")],
                  foreground=[("selected", "#1d4ed8")])

        nb = ttk.Notebook(self, style="Admin.TNotebook")
        nb.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # Tab 1 — All Records
        self._tab_records = tk.Frame(nb, bg="#ffffff")
        nb.add(self._tab_records, text="⚙  ALL RECORDS")

        # Tab 2 — Daily Report
        self._tab_report = tk.Frame(nb, bg="#ffffff")
        nb.add(self._tab_report, text="📋  DAILY REPORT")

        self._build_records_tab(self._tab_records)
        self._build_report_tab(self._tab_report)

    # ================================================================
    #  TAB 1 — ALL RECORDS
    # ================================================================
    def _build_records_tab(self, parent):
        sf = tk.Frame(parent, bg="#ffffff", padx=20, pady=8); sf.pack(fill=tk.X)
        tk.Label(sf, text="SEARCH:", font=("Courier", 8, "bold"), bg="#ffffff", fg="#adb5bd").pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_filter())
        tk.Entry(sf, textvariable=self._search_var, font=("Courier", 10),
                 bg="#f1f3f5", fg="#212529", insertbackground="#d97706", bd=0, width=30
                 ).pack(side=tk.LEFT, padx=(8, 0), ipady=4)
        self._count_lbl = tk.Label(sf, text="", font=("Courier", 8), bg="#ffffff", fg="#adb5bd")
        self._count_lbl.pack(side=tk.RIGHT)

        self.kpi_fr = tk.Frame(parent, bg="#ffffff", padx=20, pady=10); self.kpi_fr.pack(fill=tk.X)
        _make_sep(parent, BORDER2)

        tw = tk.Frame(parent, bg="#ffffff", padx=20, pady=10); tw.pack(fill=tk.BOTH, expand=True)
        style = ttk.Style(self); style.theme_use("default")
        style.configure("Cmd.Treeview", background="#f1f3f5", foreground="#212529",
                         fieldbackground="#f1f3f5", rowheight=28,
                         font=("Courier", 9), borderwidth=0)
        style.configure("Cmd.Treeview.Heading", background="#e2e8f0",
                         foreground="#1d4ed8", font=("Courier", 9, "bold"),
                         relief="flat", borderwidth=1)
        style.map("Cmd.Treeview",
                  background=[("selected", "#dbeafe")],
                  foreground=[("selected", "#1d4ed8")])

        cols    = ("ID", "Name", "Check-In", "Check-Out", "Hours", "OT", "Early?", "Late", "Status")
        widths  = (60, 220, 100, 100, 70, 70, 70, 75, 90)
        minws   = (60, 220,  90,  90, 60, 60, 60, 65, 80)
        anchors = ("center", "center", "center", "center", "center",
                   "center", "center", "center", "center")
        stretches = (False, True, False, False, False, False, False, False, False)
        self.tree = ttk.Treeview(tw, columns=cols, show="headings",
                                  style="Cmd.Treeview", selectmode="browse")
        for col, w, mw, a, st in zip(cols, widths, minws, anchors, stretches):
            self.tree.heading(col, text=col.upper(),
                              command=lambda c=col: self._sort_by(c))
            self.tree.column(col, width=w, minwidth=mw, anchor=a, stretch=st)
        for tag, col in [("late", "#b45309"), ("ot", "#7c3aed"), ("complete", "#059669"),
                         ("still_in", "#1d4ed8"), ("early", "#0891b2"),
                         ("auto", "#7c3aed"), ("alt", "#212529")]:
            self.tree.tag_configure(
                tag,
                foreground=col,
                background="#f1f3f5" if tag == "alt" else "")

        vsb = ttk.Scrollbar(tw, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    # ================================================================
    #  TAB 2 — DAILY REPORT  (Late Arrivals & Early Checkouts)
    # ================================================================
    def _build_report_tab(self, parent):
        # sub-header with refresh
        hdr = tk.Frame(parent, bg="#f8f9fa", padx=20, pady=10); hdr.pack(fill=tk.X)
        tk.Frame(hdr, bg=GOLD, height=2).pack(fill=tk.X, side=tk.TOP)
        hi = tk.Frame(hdr, bg="#f8f9fa"); hi.pack(fill=tk.X, pady=(6, 0))
        lf = tk.Frame(hi, bg="#f8f9fa"); lf.pack(side=tk.LEFT)
        tk.Label(lf, text="📋 DAILY REPORT — Late Arrivals & Early Checkouts",
                 font=("Courier", 11, "bold"), bg="#f8f9fa", fg="#212529").pack(anchor="w")
        self._report_sub_lbl = tk.Label(lf, text="", font=("Courier", 8), bg="#f8f9fa", fg="#6c757d")
        self._report_sub_lbl.pack(anchor="w", pady=(2, 0))
        rf = tk.Frame(hi, bg="#f8f9fa"); rf.pack(side=tk.RIGHT)
        b = tk.Button(rf, text="↻ REFRESH REPORT", font=("Courier", 9, "bold"),
                      relief=tk.FLAT, bg=ACCENT_DIM, fg=ACCENT2, cursor="hand2",
                      padx=14, pady=6, command=self._refresh_report)
        b.pack()
        _btn_hover(b, ACCENT2, BG, ACCENT_DIM, ACCENT2)

        # KPI strip
        self._report_kpi_fr = tk.Frame(parent, bg="#ffffff", padx=20, pady=10)
        self._report_kpi_fr.pack(fill=tk.X)
        tk.Frame(parent, bg="#ced4da", height=1).pack(fill=tk.X)

        # scrollable body
        body_wrap = tk.Frame(parent, bg="#ffffff"); body_wrap.pack(fill=tk.BOTH, expand=True)
        self._report_canvas = tk.Canvas(body_wrap, bg="#ffffff", highlightthickness=0)
        vsb = ttk.Scrollbar(body_wrap, orient="vertical",
                             command=self._report_canvas.yview)
        self._report_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._report_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._report_body     = tk.Frame(self._report_canvas, bg="#ffffff")
        self._report_body_win = self._report_canvas.create_window(
            (0, 0), window=self._report_body, anchor="nw")
        self._report_body.bind("<Configure>",   self._on_report_body_resize)
        self._report_canvas.bind("<Configure>", self._on_report_canvas_resize)
        self._report_canvas.bind_all("<MouseWheel>",
            lambda e: self._report_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        self._report_canvas.bind_all("<Button-4>",
            lambda e: self._report_canvas.yview_scroll(-1, "units"))
        self._report_canvas.bind_all("<Button-5>",
            lambda e: self._report_canvas.yview_scroll( 1, "units"))

    def _on_report_body_resize(self, _=None):
        self._report_canvas.configure(
            scrollregion=self._report_canvas.bbox("all"))

    def _on_report_canvas_resize(self, event):
        self._report_canvas.itemconfig(self._report_body_win, width=event.width)

    def _make_report_section(self, parent, title, accent, icon, rows, col_defs):
        sec_hdr = tk.Frame(parent, bg="#f1f3f5"); sec_hdr.pack(fill=tk.X)
        tk.Frame(sec_hdr, bg=accent, width=6).pack(side=tk.LEFT, fill=tk.Y)
        inner_hdr = tk.Frame(sec_hdr, bg="#f1f3f5", padx=24, pady=14)
        inner_hdr.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(inner_hdr, text=f"{icon} {title}",
                 font=("Courier", 14, "bold"), bg="#f1f3f5", fg=accent).pack(anchor="w")
        self._report_count_labels[title] = tk.Label(
            inner_hdr, text="", font=("Courier", 9), bg="#f1f3f5", fg="#6c757d")
        self._report_count_labels[title].pack(anchor="w", pady=(2, 0))
        tk.Frame(parent, bg=accent, height=2).pack(fill=tk.X)

        grid_wrap = tk.Frame(parent, bg="#ffffff"); grid_wrap.pack(fill=tk.X)
        grid_wrap.columnconfigure(0, minsize=6)
        for ci, (_, _, minw, wt) in enumerate(col_defs):
            grid_wrap.columnconfigure(ci+1, minsize=minw, weight=wt)

        tk.Frame(grid_wrap, bg=accent, width=6).grid(row=0, column=0, sticky="nsew")
        for ci, (lbl, _, _, _) in enumerate(col_defs):
            cell = tk.Frame(grid_wrap, bg="#f8f9fa", padx=14, pady=9)
            cell.grid(row=0, column=ci+1, sticky="nsew")
            tk.Label(cell, text=lbl, font=("Courier", 9, "bold"),
                     bg="#f8f9fa", fg=accent, anchor="w").pack(fill=tk.X)
        tk.Frame(grid_wrap, bg=accent, height=1).grid(
            row=1, column=0, columnspan=len(col_defs)+1, sticky="ew")

        if not rows:
            empty = tk.Frame(grid_wrap, bg="#ffffff")
            empty.grid(row=2, column=0, columnspan=len(col_defs)+1, sticky="ew")
            tk.Label(empty, text=f"  No {title.lower()} recorded today.",
                     font=("Courier", 11), bg="#ffffff", fg="#adb5bd", pady=20
                     ).pack(anchor="w", padx=24)
        else:
            for ri, row in enumerate(rows):
                grid_row = ri + 2
                row_bg   = "#f1f3f5" if ri % 2 == 0 else "#f8f9fa"
                tk.Frame(grid_wrap, bg=accent, width=6).grid(
                    row=grid_row, column=0, sticky="nsew")
                for ci, (_, key, _, _) in enumerate(col_defs):
                    val  = str(row.get(key, "—"))
                    fg_  = "#212529"
                    if key == "zk_id":  fg_ = GOLD
                    if key == "name":   fg_ = "#212529"
                    if key == "status": fg_ = accent
                    bold = key in ("zk_id", "name")
                    cell = tk.Frame(grid_wrap, bg=row_bg, padx=14, pady=11)
                    cell.grid(row=grid_row, column=ci+1, sticky="nsew")
                    tk.Label(cell, text=val,
                             font=("Courier", 11, "bold" if bold else "normal"),
                             bg=row_bg, fg=fg_, anchor="w").pack(fill=tk.X)
                tk.Frame(grid_wrap, bg="#dee2e6", height=1).grid(
                    row=grid_row, column=0, columnspan=len(col_defs)+1, sticky="sew")

        tk.Frame(parent, bg="#ced4da", height=1).pack(fill=tk.X)
        tk.Frame(parent, bg="#ffffff", height=24).pack()

    def _refresh_report(self):
        for w in self._report_body.winfo_children(): w.destroy()
        self._report_count_labels = {}
        lock  = load_lock()
        now   = datetime.now()
        cin   = lock.get("checked_in",  {})
        cout  = lock.get("checked_out", {})
        early_limit  = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
                                   second=0, microsecond=0)
        late_rows  = []
        early_rows = []
        all_workers = {**cin, **cout}

        for zk_id, info in sorted(all_workers.items(),
            key=lambda x: (x[1].get("time","") or x[1].get("checkin_time",""))
                          if isinstance(x[1], dict) else ""):
            if not isinstance(info, dict): continue
            if not info.get("is_late", False): continue
            name   = info.get("name", zk_id)
            ci_raw = info.get("time","") or info.get("checkin_time","")
            is_out = zk_id in cout
            try:
                ci_disp = datetime.strptime(ci_raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M:%S")
            except Exception:
                ci_disp = ci_raw[-8:] if len(ci_raw) >= 8 else ci_raw or "—"
            status = "✔ OUT" if is_out else "● ACTIVE"
            late_rows.append({"zk_id": zk_id, "name": name,
                              "checkin": ci_disp,
                              "late_note": info.get("late_note",""),
                              "status": status})

        for zk_id, info in sorted(cout.items(),
            key=lambda x: x[1].get("time","") if isinstance(x[1], dict) else ""):
            if not isinstance(info, dict): continue
            co_raw = info.get("time","")
            try:
                co_dt    = datetime.strptime(co_raw, "%H:%M:%S").replace(
                    year=now.year, month=now.month, day=now.day)
                is_early = co_dt < early_limit
            except Exception:
                is_early = False
            if not is_early: continue
            name   = info.get("name", zk_id)
            ci_raw = info.get("checkin_time","")
            try:
                ci_disp = datetime.strptime(ci_raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M:%S")
            except Exception:
                ci_disp = ci_raw[-8:] if len(ci_raw) >= 8 else ci_raw or "—"
            hrs   = info.get("total_hours", 0)
            h_str = (f"{int(hrs)}h {int((hrs%1)*60):02d}m"
                     if isinstance(hrs, (int, float)) else "—")
            early_rows.append({"zk_id": zk_id, "name": name,
                                "checkin": ci_disp, "checkout": co_raw or "—",
                                "hours": h_str, "status": "⚡ LEFT EARLY"})

        # KPI tiles
        for w in self._report_kpi_fr.winfo_children(): w.destroy()
        total_in = len(cin) + len(cout)
        for label, val, fg, border in [
            ("TOTAL IN TODAY",   total_in,        "#212529", "#ced4da"),
            ("STILL ON-SITE",    len(cin),         "#1d4ed8", "#bfdbfe"),
            ("CHECKED OUT",      len(cout),        "#059669", "#a7f3d0"),
            ("LATE ARRIVALS",    len(late_rows),   "#b45309", "#fde68a"),
            ("EARLY CHECKOUTS",  len(early_rows),  "#0891b2", "#a5f3fc"),
        ]:
            tile = tk.Frame(self._report_kpi_fr, bg="#ffffff", padx=20, pady=10,
                            highlightbackground=border, highlightthickness=1, relief="flat")
            tile.pack(side=tk.LEFT, padx=(0, 10), fill=tk.Y)
            tk.Label(tile, text=str(val),
                     font=("Courier", 28, "bold"), bg="#ffffff", fg=fg).pack()
            tk.Label(tile, text=label,
                     font=("Courier", 7, "bold"),  bg="#ffffff", fg="#6c757d").pack()

        self._make_report_section(
            self._report_body, title="LATE ARRIVALS",
            accent=ORANGE2, icon="⚠", rows=late_rows,
            col_defs=[("ZK ID","zk_id",80,0),("FULL NAME","name",260,1),
                      ("CHECKED IN","checkin",120,0),
                      ("LATE BY","late_note",160,0),
                      ("STATUS","status",120,0)])
        self._make_report_section(
            self._report_body, title="EARLY CHECKOUTS",
            accent=CYAN2, icon="⚡", rows=early_rows,
            col_defs=[("ZK ID","zk_id",80,0),("FULL NAME","name",260,1),
                      ("CHECKED IN","checkin",120,0),
                      ("CHECKED OUT","checkout",120,0),
                      ("HOURS","hours",100,0),
                      ("STATUS","status",140,0)])

        now_str = now.strftime("%H:%M:%S")
        self._report_sub_lbl.config(text=(
            f"Date: {lock.get('date', now.strftime('%Y-%m-%d'))}  "
            f"Shift start: {SHIFT_START_H:02d}:{SHIFT_START_M:02d}  "
            f"Early threshold: before {EARLY_CHECKOUT_H:02d}:{EARLY_CHECKOUT_M:02d}  "
            f"Last refresh: {now_str}"))

        if "LATE ARRIVALS" in self._report_count_labels:
            self._report_count_labels["LATE ARRIVALS"].config(
                text=f"{len(late_rows)} worker{'s' if len(late_rows)!=1 else ''} arrived late today")
        if "EARLY CHECKOUTS" in self._report_count_labels:
            self._report_count_labels["EARLY CHECKOUTS"].config(
                text=f"{len(early_rows)} worker{'s' if len(early_rows)!=1 else ''} "
                     f"left before {EARLY_CHECKOUT_H:02d}:{EARLY_CHECKOUT_M:02d}")

        self._report_canvas.update_idletasks()
        self._report_canvas.configure(
            scrollregion=self._report_canvas.bbox("all"))

    # ================================================================
    #  SHARED RECORDS TAB METHODS
    # ================================================================
    def _sort_by(self, col):
        self._sort_asc = not self._sort_asc if self._sort_col == col else True
        self._sort_col = col; self._apply_filter()

    def _apply_filter(self):
        q = self._search_var.get().strip().lower()
        visible = [r for r in self._all_rows
                   if not q or any(q in str(v).lower() for v in r["values"])]
        if self._sort_col:
            cols = ["ID", "Name", "Check-In", "Check-Out",
                    "Hours", "OT", "Early?", "Late", "Status"]
            idx  = cols.index(self._sort_col) if self._sort_col in cols else 0
            visible.sort(key=lambda r: str(r["values"][idx]),
                         reverse=not self._sort_asc)
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(visible):
            tags = list(r["tags"]) + ["alt"] if i % 2 == 1 else list(r["tags"])
            self.tree.insert("", tk.END, values=r["values"], tags=tuple(tags))
        self._count_lbl.config(text=f"{len(visible)}/{len(self._all_rows)} records")

    def refresh(self):
        self._all_rows = []
        lock  = load_lock()
        cin   = lock.get("checked_in",  {})
        cout  = lock.get("checked_out", {})
        late_count = ot_count = early_count = auto_count = 0
        now   = datetime.now()
        early_limit = now.replace(hour=EARLY_CHECKOUT_H, minute=EARLY_CHECKOUT_M,
                                  second=0, microsecond=0)

        for zk_id, info in sorted(cout.items(),
            key=lambda x: x[1].get("checkin_time", "") if isinstance(x[1], dict) else ""):
            if not isinstance(info, dict): continue
            name  = info.get("name", zk_id)
            ci    = info.get("checkin_time", "---"); ci_s = ci[-8:] if len(ci) > 8 else ci
            co    = info.get("time", "---")
            hrs   = info.get("total_hours",    0)
            ot    = info.get("overtime_hours", 0)
            late  = info.get("is_late",  False)
            auto  = info.get("auto_checkout", False)
            h_str = (f"{int(hrs)}h {int((hrs%1)*60):02d}m"
                     if isinstance(hrs, (int, float)) else str(hrs))
            o_str = (f"{int(ot)}h {int((ot%1)*60):02d}m" if ot else "---")
            is_early = False
            try:
                co_dt    = datetime.strptime(co, "%H:%M:%S").replace(
                    year=now.year, month=now.month, day=now.day)
                is_early = co_dt < early_limit
            except Exception: pass
            if late:     late_count  += 1
            if ot > 0:   ot_count    += 1
            if is_early: early_count += 1
            if auto:     auto_count  += 1
            tags = []
            if late:     tags.append("late")
            if ot > 0:   tags.append("ot")
            if is_early: tags.append("early")
            if auto:     tags.append("auto")
            tags.append("complete")
            self._all_rows.append({"values": (
                zk_id, name, ci_s, co, h_str, o_str,
                "⚡ YES" if is_early else "---",
                "⚠ LATE" if late else "---",
                "AUTO" if auto else "✔ DONE"), "tags": tags})

        for zk_id, info in sorted(cin.items(),
            key=lambda x: x[1].get("time", "") if isinstance(x[1], dict) else ""):
            if not isinstance(info, dict): continue
            name = info.get("name", zk_id)
            ci   = info.get("time", "---"); late = info.get("is_late", False)
            try:
                dt_in   = datetime.strptime(ci, "%d-%b-%Y %H:%M:%S")
                elapsed = (now - dt_in).total_seconds() / 3600
                h_str   = f"{int(elapsed)}h {int((elapsed%1)*60):02d}m"
            except Exception:
                h_str = "---"
            ci_s = ci[-8:] if len(ci) > 8 else ci
            if late: late_count += 1
            tags = ["late"] if late else []
            tags.append("still_in")
            self._all_rows.append({"values": (
                zk_id, name, ci_s, "---", h_str, "---", "---",
                "⚠ LATE" if late else "---", "● ACTIVE"), "tags": tags})

        self._apply_filter()
        for w in self.kpi_fr.winfo_children(): w.destroy()
        total = len(cin) + len(cout)
        for label, val, fg, border in [
            ("TOTAL",       total,       "#212529", "#ced4da"),
            ("CHECKED IN",  total,       "#1d4ed8", "#bfdbfe"),
            ("CHECKED OUT", len(cout),   "#059669", "#a7f3d0"),
            ("AUTO-OUT",    auto_count,  "#7c3aed", "#ddd6fe"),
            ("EARLY OUT",   early_count, "#0891b2", "#a5f3fc"),
            ("LATE",        late_count,  "#b45309", "#fde68a"),
            ("OVERTIME",    ot_count,    "#7c3aed", "#ddd6fe")]:
            tile = tk.Frame(self.kpi_fr, bg="#ffffff", padx=13, pady=8,
                            highlightbackground=border, highlightthickness=1, relief="flat")
            tile.pack(side=tk.LEFT, padx=(0, 8), fill=tk.Y)
            tk.Label(tile, text=str(val), font=("Courier", 20, "bold"),
                     bg="#ffffff", fg=fg).pack()
            tk.Label(tile, text=label, font=("Courier", 6, "bold"),
                     bg="#ffffff", fg="#6c757d").pack()

        self.sub_lbl.config(text=(
            f"Date:{lock.get('date','')}  "
            f"Shift:{SHIFT_START_H:02d}:{SHIFT_START_M:02d}  "
            f"Std:{SHIFT_HOURS}h  Grace:{GRACE_MINUTES}min  "
            f"Auto-out:{AUTO_CHECKOUT_H:02d}:00  "
            f"Refreshed:{datetime.now().strftime('%H:%M:%S')}"))

        # also refresh the report tab data
        self._refresh_report()

    def _export(self):
        fname = export_daily_summary()
        if fname:
            messagebox.showinfo("Exported", f"Saved:\n{os.path.abspath(fname)}", parent=self)
        else:
            messagebox.showwarning("Nothing to Export", "No records for today.", parent=self)


# ===========================================================
# MAIN GUI
# ===========================================================
class FingerprintGUI:
    def __init__(self, root):
        self.root   = root
        self.root.title("Wavemark Properties — Attendance Terminal")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.root.minsize(800, 600)
        self._busy         = False
        self._debounce_job = None
        self._log_lines    = 0
        self._gui_q: queue.Queue = queue.Queue()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        W, H   = min(sw, 980), min(sh - 60, 800)
        self.root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self._build_ui()
        self._tick_clock()
        self._tick_stats()
        self._tick_autocheckout()
        self._drain_q()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Startup check — warn user immediately if .env is broken
        self.root.after(1500, self._startup_token_check)

    def _startup_token_check(self):
        def _check():
            token = get_access_token()
            if not token:
                self._gui(lambda: self.log(
                    "⚠ WARNING: Could not connect to Zoho — "
                    "check CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN in .env\n"
                    "  Visit https://api-console.zoho.com to regenerate credentials.", "err"))
        threading.Thread(target=_check, daemon=True).start()

    def _drain_q(self):
        try:
            while True: self._gui_q.get_nowait()()
        except queue.Empty: pass
        self.root.after(50, self._drain_q)

    def _gui(self, fn):
        self._gui_q.put(fn)

    # ------ UI BUILD ------
    def _build_ui(self):
        self._build_header(); self._build_body()
        self._build_footer(); self._build_flash()

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=CARD); hdr.pack(fill=tk.X)
        tk.Frame(hdr, bg=GOLD, height=3).pack(fill=tk.X)
        hi  = tk.Frame(hdr, bg=CARD, padx=28, pady=14); hi.pack(fill=tk.X)
        lf  = tk.Frame(hi, bg=CARD); lf.pack(side=tk.LEFT)
        # ── Animated marquee for company name ──────────────────────
        self._marquee_canvas = tk.Canvas(lf, bg=CARD, highlightthickness=0, height=26)
        self._marquee_canvas.pack(anchor="w", fill=tk.X, expand=True)
        self._marquee_text = self._marquee_canvas.create_text(
            340, 13, text="WAVEMARK PROPERTIES LIMITED   ✦   WAVEMARK PROPERTIES LIMITED   ✦   ",
            font=("Courier", 11, "bold"), fill=GOLD, anchor="w")
        self._marquee_x = 340
        self._marquee_speed = 2
        self._animate_marquee()
        # ── Static subtitle ─────────────────────────────────────────
        tk.Label(lf, text="Biometric Attendance Terminal · v5.3 · 2000-user edition",
                 font=("Courier", 8), bg=CARD, fg=MUTED).pack(anchor="w", pady=(1, 0))
        rf = tk.Frame(hi, bg=CARD); rf.pack(side=tk.RIGHT)
        btn_row = tk.Frame(rf, bg=CARD); btn_row.pack(anchor="e", pady=(0, 6))
        btn_refresh = tk.Button(btn_row, text="↻ REFRESH",
                                font=("Courier", 8, "bold"), relief=tk.FLAT,
                                bg=ACCENT_DIM, fg=ACCENT2,
                                activebackground=ACCENT, activeforeground=WHITE,
                                cursor="hand2", padx=10, pady=5,
                                command=self._refresh_main)
        btn_refresh.pack(side=tk.LEFT, padx=(0, 6))
        _btn_hover(btn_refresh, ACCENT, WHITE, ACCENT_DIM, ACCENT2)
        btn_admin = tk.Button(btn_row, text="⚙ ADMIN PANEL",
                              font=("Courier", 8, "bold"), relief=tk.FLAT,
                              bg=PURPLE_DIM, fg=PURPLE,
                              activebackground=PURPLE, activeforeground=WHITE,
                              cursor="hand2", padx=10, pady=5,
                              command=self._open_admin)
        btn_admin.pack(side=tk.LEFT)
        _btn_hover(btn_admin, PURPLE, WHITE, PURPLE_DIM, PURPLE)
        self.date_lbl  = tk.Label(rf, text="", font=("Courier", 8),  bg=CARD, fg=TEXT2)
        self.date_lbl.pack(anchor="e")
        self.clock_lbl = tk.Label(rf, text="", font=("Courier", 24, "bold"), bg=CARD, fg=WHITE)
        self.clock_lbl.pack(anchor="e")
        powered_lbl = tk.Label(rf, text="⚡ Powered by Finlanza Team",
                               font=("Courier", 7), bg=CARD, fg=CYAN2, cursor="hand2")
        powered_lbl.pack(anchor="e", pady=(2, 0))
        powered_lbl.bind("<Button-1>", lambda e: __import__("webbrowser").open("https://finlanza.com/"))
        _make_sep(self.root, BORDER2)
        sbar = tk.Frame(self.root, bg=CARD2, padx=28, pady=6); sbar.pack(fill=tk.X)
        tk.Label(sbar, text=(f"SHIFT {SHIFT_START_H:02d}:{SHIFT_START_M:02d} · "
                             f"STD {SHIFT_HOURS}H · GRACE {GRACE_MINUTES}MIN · "
                             f"EARLY<{EARLY_CHECKOUT_H:02d}:00 · AUTO@{AUTO_CHECKOUT_H:02d}:00"),
                 font=("Courier", 8), bg=CARD2, fg=WHITE).pack(side=tk.LEFT)
        tk.Label(sbar, text="ENTER → auto-action   ESC → clear",
                 font=("Courier", 8), bg=CARD2, fg=WHITE).pack(side=tk.RIGHT)

    def _build_body(self):
        body = tk.Frame(self.root, bg=BG, padx=24, pady=14)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=3)   # left panel grows more
        body.columnconfigure(1, weight=0)   # divider fixed
        body.columnconfigure(2, weight=1)   # right panel grows
        body.rowconfigure(0, weight=1)
        left  = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew")
        tk.Frame(body, bg=BORDER, width=1).grid(row=0, column=1, sticky="ns", padx=16)
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=2, sticky="nsew")
        right.columnconfigure(0, weight=1)
        self._build_left(left); self._build_right(right)

    def _build_left(self, parent):
        id_card = tk.Frame(parent, bg=CARD2, highlightbackground=BORDER2, highlightthickness=1)
        id_card.pack(fill=tk.X, pady=(0, 12))
        ch = tk.Frame(id_card, bg=CARD, padx=18, pady=10); ch.pack(fill=tk.X)
        tk.Label(ch, text="WORKER IDENTIFICATION",
                 font=("Courier", 8, "bold"), bg=CARD, fg=TEXT2).pack(side=tk.LEFT)
        self._led = PulseLED(ch, MUTED); self._led.pack(side=tk.RIGHT, padx=(0, 2))
        _make_sep(id_card, BORDER)
        ci = tk.Frame(id_card, bg=CARD2, padx=18, pady=14); ci.pack(fill=tk.X)
        er = tk.Frame(ci, bg=CARD2); er.pack(fill=tk.X)
        tk.Label(er, text="ID", font=("Courier", 8, "bold"),
                 bg=CARD2, fg=MUTED, width=3, anchor="w").pack(side=tk.LEFT)
        eb = tk.Frame(er, bg=GOLD, padx=1, pady=1); eb.pack(side=tk.LEFT, padx=(6, 0))
        ei = tk.Frame(eb, bg="#09101a"); ei.pack()
        self.user_entry = tk.Entry(ei, font=("Courier", 28, "bold"), width=9, bd=0,
                                   bg="#09101a", fg=WHITE, insertbackground=GOLD,
                                   selectbackground=GOLD2, selectforeground=BG)
        self.user_entry.pack(padx=14, pady=8, fill=tk.X, expand=True)
        self.user_entry.bind("<KeyRelease>", self._on_key)
        self.user_entry.bind("<Return>",     self._on_enter)
        self.user_entry.bind("<Escape>",     lambda _: self._reset_ui())
        self.user_entry.focus_set()
        btn_clr = tk.Button(er, text="✕", font=("Courier", 10, "bold"), relief=tk.FLAT,
                            bg=BORDER, fg=MUTED,
                            activebackground=RED_DIM, activeforeground=RED,
                            cursor="hand2", padx=8, pady=4, command=self._reset_ui)
        btn_clr.pack(side=tk.LEFT, padx=(10, 0))
        _btn_hover(btn_clr, RED_DIM, RED, BORDER, MUTED)

        idf = tk.Frame(ci, bg=CARD2); idf.pack(fill=tk.X, pady=(12, 0))
        self._avatar_cv = tk.Canvas(idf, width=48, height=48,
                                    bg=CARD2, highlightthickness=0)
        self._avatar_cv.pack(side=tk.LEFT, padx=(0, 12))
        self._avatar_circle = self._avatar_cv.create_oval(2, 2, 46, 46,
                                                           fill=BORDER, outline="")
        self._avatar_text   = self._avatar_cv.create_text(24, 24, text="",
                                                           font=("Courier", 13, "bold"),
                                                           fill=MUTED)
        info_col = tk.Frame(idf, bg=CARD2); info_col.pack(side=tk.LEFT, fill=tk.X)
        self.name_lbl = tk.Label(info_col, text="—",
                                  font=("Courier", 16, "bold"), bg=CARD2, fg=MUTED)
        self.name_lbl.pack(anchor="w")
        self.hint_lbl = tk.Label(info_col, text="Enter a Worker ID above",
                                  font=("Courier", 9), bg=CARD2, fg=MUTED)
        self.hint_lbl.pack(anchor="w", pady=(2, 0))

        self.sf = tk.Frame(parent, bg=ACCENT_DIM,
                           highlightbackground=ACCENT, highlightthickness=1)
        self.sf.pack(fill=tk.X, pady=(0, 12))
        sb_inner = tk.Frame(self.sf, bg=ACCENT_DIM); sb_inner.pack(fill=tk.X, padx=16, pady=10)
        self._status_led = PulseLED(sb_inner, ACCENT)
        self._status_led.pack(side=tk.LEFT, padx=(0, 8))
        self.sl = tk.Label(sb_inner, text="Awaiting Worker ID",
                           font=("Courier", 10, "bold"),
                           bg=ACCENT_DIM, fg=ACCENT, anchor="w")
        self.sl.pack(side=tk.LEFT, fill=tk.X)

        # ── action buttons (Daily Report button REMOVED) ──
        br = tk.Frame(parent, bg=BG); br.pack(fill=tk.X, pady=(0, 12))
        self.btn_in = tk.Button(br, text="▶ CHECK IN",
                                font=("Courier", 12, "bold"), width=13,
                                relief=tk.FLAT, bg=GREEN_DIM, fg=MUTED,
                                activebackground=GREEN, activeforeground=BG,
                                cursor="hand2", state=tk.DISABLED,
                                command=lambda: self._trigger("checkin"))
        self.btn_in.pack(side=tk.LEFT, ipady=12, padx=(0, 6))

        self.btn_forgot = tk.Button(br, text="🔍 FORGOT ID",
                                    font=("Courier", 9, "bold"), relief=tk.FLAT,
                                    bg=TEAL_DIM, fg=TEAL,
                                    activebackground=TEAL, activeforeground=BG,
                                    cursor="hand2", padx=10,
                                    command=self._open_forgotten_id)
        self.btn_forgot.pack(side=tk.LEFT, ipady=12, padx=(0, 6))
        _btn_hover(self.btn_forgot, TEAL, BG, TEAL_DIM, TEAL)

        self.btn_out = tk.Button(br, text="■ CHECK OUT",
                                 font=("Courier", 12, "bold"), width=13,
                                 relief=tk.FLAT, bg=RED_DIM, fg=MUTED,
                                 activebackground=RED, activeforeground=WHITE,
                                 cursor="hand2", state=tk.DISABLED,
                                 command=lambda: self._trigger("checkout"))
        self.btn_out.pack(side=tk.LEFT, ipady=12, padx=(0, 6))

        btn_exp = tk.Button(br, text="⬇ CSV", font=("Courier", 9, "bold"), relief=tk.FLAT,
                            bg=BORDER, fg=TEXT2, cursor="hand2", padx=10,
                            command=self._quick_export)
        btn_exp.pack(side=tk.RIGHT, ipady=12)
        _btn_hover(btn_exp, GREEN_DIM, GREEN2, BORDER, TEXT2)

        _make_sep(parent, BORDER); tk.Frame(parent, bg=BG, height=8).pack()
        lh = tk.Frame(parent, bg=BG); lh.pack(fill=tk.X, pady=(0, 6))
        tk.Label(lh, text="ACTIVITY LOG",
                 font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(side=tk.LEFT)
        self._log_count_lbl = tk.Label(lh, text="", font=("Courier", 7), bg=BG, fg=MUTED)
        self._log_count_lbl.pack(side=tk.LEFT, padx=(8, 0))
        btn_clrlog = tk.Button(lh, text="CLEAR", font=("Courier", 7, "bold"),
                               relief=tk.FLAT, bg=BORDER, fg=MUTED,
                               padx=8, pady=2, cursor="hand2",
                               command=self._clear_log)
        btn_clrlog.pack(side=tk.RIGHT)
        _btn_hover(btn_clrlog, BORDER2, TEXT2, BORDER, MUTED)

        lw = tk.Frame(parent, bg=CARD, highlightbackground=BORDER2, highlightthickness=1)
        lw.pack(fill=tk.BOTH, expand=True)
        lw.rowconfigure(0, weight=1)
        lw.columnconfigure(0, weight=1)
        sb = tk.Scrollbar(lw, bg=BORDER, troughcolor=CARD); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_box = tk.Text(lw, font=("Courier", 9), bg=CARD, fg=TEXT2, relief=tk.FLAT,
                               padx=14, pady=10, yscrollcommand=sb.set,
                               state=tk.DISABLED, cursor="arrow")
        self.log_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.log_box.yview)
        for tag, col in [("ok", GREEN2), ("err", RED2), ("warn", ORANGE2),
                         ("info", ACCENT2), ("ts", MUTED), ("div", BORDER2),
                         ("late", ORANGE), ("ot", PURPLE), ("early", CYAN2)]:
            self.log_box.tag_config(tag, foreground=col)

    def _build_right(self, parent):
        tk.Label(parent, text="BIOMETRIC SCANNER",
                 font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 8))
        sc       = tk.Frame(parent, bg=CARD2, highlightbackground=BORDER2, highlightthickness=1)
        sc.pack(fill=tk.X, expand=False, pady=(0, 14))
        sc_inner = tk.Frame(sc, bg=CARD2, pady=16); sc_inner.pack()
        self._fp       = FingerprintCanvas(sc_inner); self._fp.pack(pady=(0, 8))
        self._scan_lbl = tk.Label(sc_inner, text="READY",
                                  font=("Courier", 9, "bold"), bg=CARD2, fg=MUTED)
        self._scan_lbl.pack()
        self._scan_sub = tk.Label(sc_inner, text="Place finger when prompted",
                                  font=("Courier", 7), bg=CARD2, fg=MUTED, wraplength=200)
        self._scan_sub.pack(pady=(2, 0))

        tk.Label(parent, text="LIVE DASHBOARD",
                 font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 8))
        dash = tk.Frame(parent, bg=BG); dash.pack(fill=tk.X, expand=False)
        dash.columnconfigure(0, weight=1); dash.columnconfigure(1, weight=1)
        row1 = tk.Frame(dash, bg=BG); row1.pack(fill=tk.X, pady=(0, 8))
        row1.columnconfigure(0, weight=1); row1.columnconfigure(1, weight=1)
        self._tile_cin  = self._make_tile(row1, "CHECKED IN TODAY", "0", ACCENT2, "#0d1f3f")
        self._tile_cout = self._make_tile(row1, "CHECKED OUT",      "0", GREEN2,  "#0a3321")
        row2 = tk.Frame(dash, bg=BG); row2.pack(fill=tk.X, pady=(0, 8))
        self._tile_early = self._make_tile(
            row2, f"EARLY OUT (<{EARLY_CHECKOUT_H:02d}:00)", "0", CYAN2, CYAN_DIM, full=True)
        row3 = tk.Frame(dash, bg=BG); row3.pack(fill=tk.X, pady=(0, 8))
        row3.columnconfigure(0, weight=1); row3.columnconfigure(1, weight=1)
        self._tile_late = self._make_tile(row3, "LATE ARRIVALS", "0", ORANGE2, "#3d1f00")
        self._tile_ot   = self._make_tile(row3, "OVERTIME",       "0", PURPLE,  "#1e0a40")

        dr_frame = tk.Frame(parent, bg=CARD2, highlightbackground=BORDER, highlightthickness=1)
        dr_frame.pack(fill=tk.X, pady=(0, 10))
        dr_inner = tk.Frame(dr_frame, bg=CARD2, pady=10, padx=16); dr_inner.pack(fill=tk.X)
        tk.Label(dr_inner, text="COMPLETION RATE",
                 font=("Courier", 7, "bold"), bg=CARD2, fg=MUTED).pack(anchor="w", pady=(0, 6))
        dr_row = tk.Frame(dr_inner, bg=CARD2); dr_row.pack(fill=tk.X)
        self._donut = DonutRing(dr_row); self._donut.pack(side=tk.LEFT, padx=(0, 14))
        dr_leg = tk.Frame(dr_row, bg=CARD2); dr_leg.pack(side=tk.LEFT, fill=tk.Y)
        self._legend_lbl = tk.Label(dr_leg, text="0 of 0 workers\nhave checked out",
                                    font=("Courier", 8), bg=CARD2, fg=TEXT2, justify=tk.LEFT)
        self._legend_lbl.pack(anchor="w")
        self._early_lbl  = tk.Label(dr_leg, text="",
                                    font=("Courier", 8), bg=CARD2, fg=CYAN2, justify=tk.LEFT)
        self._early_lbl.pack(anchor="w", pady=(6, 0))

        tk.Label(parent, text="RECENT EVENTS",
                 font=("Courier", 8, "bold"), bg=BG, fg=MUTED).pack(anchor="w", pady=(8, 6))
        ev_fr = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        ev_fr.pack(fill=tk.BOTH, expand=True)
        parent.rowconfigure(999, weight=1)
        self._event_box = tk.Text(ev_fr, font=("Courier", 8), bg=CARD, fg=TEXT2,
                                  relief=tk.FLAT, padx=10, pady=8,
                                  state=tk.DISABLED, cursor="arrow")
        self._event_box.pack(fill=tk.BOTH, expand=True)
        for tag, col in [("in", GREEN2), ("out", ACCENT2),
                         ("warn", ORANGE2), ("ts", MUTED), ("early", CYAN2)]:
            self._event_box.tag_config(tag, foreground=col)

    def _make_tile(self, parent, label, value, fg, bg2, full=False):
        tile = tk.Frame(parent, bg=CARD2, padx=14, pady=10,
                        highlightbackground=bg2, highlightthickness=1)
        kw = {"fill": tk.X, "expand": True}
        if not full: kw["padx"] = (0, 6)
        tile.pack(side=tk.LEFT, **kw)
        val_lbl = tk.Label(tile, text=value, font=("Courier", 26, "bold"), bg=CARD2, fg=fg)
        val_lbl.pack()
        tk.Label(tile, text=label, font=("Courier", 6, "bold"), bg=CARD2, fg=TEXT2).pack()
        return val_lbl

    def _build_footer(self):
        tk.Frame(self.root, bg=GOLD, height=3).pack(fill=tk.X, side=tk.BOTTOM)
        foot = tk.Frame(self.root, bg=CARD, padx=28, pady=12)
        foot.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Frame(self.root, bg=BORDER2, height=1).pack(fill=tk.X, side=tk.BOTTOM)
        # Left — live stats
        self._foot_lbl = tk.Label(foot, text="", font=("Courier", 10, "bold"), bg=CARD, fg=WHITE)
        self._foot_lbl.pack(side=tk.LEFT)
        # Right — shift policy
        tk.Label(foot, text=(f"Shift {SHIFT_START_H:02d}:{SHIFT_START_M:02d}–"
                             f"{(SHIFT_START_H+SHIFT_HOURS)%24:02d}:{SHIFT_START_M:02d} "
                             f"· {SHIFT_HOURS}h std · {GRACE_MINUTES}min grace "
                             f"· early<{EARLY_CHECKOUT_H:02d}:00 "
                             f"· auto@{AUTO_CHECKOUT_H:02d}:00"),
                 font=("Courier", 10, "bold"), bg=CARD, fg=GOLD).pack(side=tk.RIGHT)

    def _build_flash(self):
        self.flash = tk.Frame(self.root, bg=ACCENT)
        self.fi = tk.Label(self.flash, font=("Courier", 60, "bold"), bg=ACCENT, fg=WHITE)
        self.fi.place(relx=0.5, rely=0.22, anchor="center")
        self.fm = tk.Label(self.flash, font=("Courier", 22, "bold"),
                           bg=ACCENT, fg=WHITE, wraplength=740)
        self.fm.place(relx=0.5, rely=0.40, anchor="center")
        self.fs = tk.Label(self.flash, font=("Courier", 22, "bold"),
                           bg=ACCENT, fg=WHITE, wraplength=740, justify=tk.CENTER)
        self.fs.place(relx=0.5, rely=0.56, anchor="center")
        self.fx = tk.Label(self.flash, font=("Courier", 11, "bold"),
                           bg=ACCENT, fg=GOLD2, wraplength=740)
        self.fx.place(relx=0.5, rely=0.72, anchor="center")

    # ------ TICKERS ------
    def _tick_clock(self):
        n = datetime.now()
        self.date_lbl.config(text=n.strftime("%A, %d %B %Y"))
        self.clock_lbl.config(text=n.strftime("%H:%M:%S"))
        self.root.after(1000, self._tick_clock)

    def _tick_stats(self):
        lock  = load_lock()
        cin   = lock.get("checked_in",  {})
        cout  = lock.get("checked_out", {})
        total = len(cin) + len(cout)
        early = count_early_checkouts(lock)
        late  = sum(1 for v in {**cin, **cout}.values()
                    if isinstance(v, dict) and v.get("is_late"))
        ot    = sum(1 for v in cout.values()
                    if isinstance(v, dict) and v.get("overtime_hours", 0) > 0)
        self._tile_cin.config(text=str(total))
        self._tile_cout.config(text=str(len(cout)))
        self._tile_early.config(text=str(early))
        self._tile_late.config(text=str(late))
        self._tile_ot.config(text=str(ot))
        fraction   = len(cout) / total if total > 0 else 0
        donut_col  = GREEN2 if fraction >= 0.8 else ORANGE2 if fraction >= 0.4 else ACCENT2
        self._donut.set_value(fraction, donut_col)
        self._legend_lbl.config(text=f"{len(cout)} of {total} workers\nhave checked out")
        self._early_lbl.config(
            text=f"⚡ {early} left before {EARLY_CHECKOUT_H:02d}:00" if early else "")
        self._foot_lbl.config(
            text=f"In:{total}  Out:{len(cout)}  On-site:{len(cin)}  "
                 f"Early:{early}  Late:{late}  OT:{ot}")
        self.root.after(STATS_REFRESH_MS, self._tick_stats)

    def _tick_autocheckout(self):
        now = datetime.now()
        if (now.hour > AUTO_CHECKOUT_H or
                (now.hour == AUTO_CHECKOUT_H and now.minute >= AUTO_CHECKOUT_M)):
            lock    = load_lock()
            pending = {k: v for k, v in lock.get("checked_in", {}).items()
                       if isinstance(v, dict)}
            if pending:
                self.log(f"AUTO-CHECKOUT triggered @ {now.strftime('%H:%M')} "
                         f"— {len(pending)} worker(s)", "warn")
                threading.Thread(
                    target=run_auto_checkout,
                    kwargs={"gui_log_fn": self.log, "done_cb": self._auto_checkout_done},
                    daemon=True).start()
            return
        self.root.after(30_000, self._tick_autocheckout)

    def _auto_checkout_done(self, success_names, fail_names):
        def _u():
            self._tick_stats()
            n     = len(success_names)
            names = ", ".join(success_names[:5]) + ("..." if len(success_names) > 5 else "")
            extra = f"Failed: {', '.join(fail_names)}" if fail_names else ""
            self._show_flash(">>", f"Auto-Checkout @ {datetime.now().strftime('%H:%M')}",
                             f"{n} worker(s) checked out\n{names}", extra, "#1e0a40")
            for name in success_names:
                self._add_event("AUTO-OUT", name, "warn")
        self._gui(_u)

    # ------ PANEL OPENERS ------
    def _animate_marquee(self):
        try:
            self._marquee_x -= self._marquee_speed
            # Get the bounding box of the text to know its full width
            bbox = self._marquee_canvas.bbox(self._marquee_text)
            if bbox:
                text_width = bbox[2] - bbox[0]
                # Reset when the full text has scrolled off the left edge
                if self._marquee_x < -text_width // 2:
                    self._marquee_x = 340
            self._marquee_canvas.coords(self._marquee_text, self._marquee_x, 13)
            self.root.after(30, self._animate_marquee)
        except Exception:
            pass  # window was destroyed

    def _open_admin(self):           AdminPanel(self.root)

    def _refresh_main(self):
        """Destroy and fully rebuild the entire main window."""
        self.root.destroy()
        root = tk.Tk()
        FingerprintGUI(root)
        root.mainloop()

    def _open_forgotten_id(self):
        def _on_select(zk_id: str):
            self.user_entry.delete(0, tk.END)
            self.user_entry.insert(0, zk_id)
            self.user_entry.focus_set()
            self._apply_status(get_worker_status(zk_id))
            threading.Thread(target=self._validate, args=(zk_id,), daemon=True).start()
            self.log(f"Forgotten ID resolved → ZK#{zk_id}", "info")
        ForgottenIDDialog(self.root, on_select=_on_select)

    def _quick_export(self):
        def _do():
            fname = export_daily_summary()
            if fname:
                self._gui(lambda: self.log(f"Exported → {os.path.abspath(fname)}", "ok"))
            else:
                self._gui(lambda: self.log("Nothing to export.", "warn"))
        threading.Thread(target=_do, daemon=True).start()

    # ------ LOGGING ------
    def log(self, msg: str, tag: str = "info"):
        def _do():
            self.log_box.config(state=tk.NORMAL)
            if self._log_lines >= LOG_MAX_LINES:
                self.log_box.delete("1.0", "50.0")
                self._log_lines = max(self._log_lines - 50, 0)
            self.log_box.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] ", "ts")
            self.log_box.insert(tk.END, f"{msg}\n", tag)
            self.log_box.see(tk.END)
            self.log_box.config(state=tk.DISABLED)
            self._log_lines += 1
            self._log_count_lbl.config(text=f"({self._log_lines})")
        self._gui(_do)

    def _clear_log(self):
        self.log_box.config(state=tk.NORMAL)
        self.log_box.delete("1.0", tk.END)
        self.log_box.config(state=tk.DISABLED)
        self._log_lines = 0
        self._log_count_lbl.config(text="")

    def _add_event(self, action: str, name: str, tag: str = "ts"):
        def _do():
            self._event_box.config(state=tk.NORMAL)
            ts = datetime.now().strftime("%H:%M")
            self._event_box.insert("1.0", f"{ts}  {action:<10}  {name}\n", tag)
            lines = int(self._event_box.index("end-1c").split(".")[0])
            if lines > 100:
                self._event_box.delete("80.0", tk.END)
            self._event_box.config(state=tk.DISABLED)
        self._gui(_do)

    def _show_flash(self, icon, headline, sub, extra, color):
        self.flash.config(bg=color)
        for w, v in [(self.fi, icon), (self.fm, headline), (self.fs, sub), (self.fx, extra)]:
            w.config(text=v, bg=color)
        self.flash.place(x=0, y=0, relwidth=1, relheight=1)
        self.flash.lift()
        self.root.after(2400, self.flash.place_forget)

    # ------ SCANNER STATES ------
    def _scan_start(self):
        self._fp.start()
        self._scan_lbl.config(text="SCANNING…", fg=ORANGE2)
        self._scan_sub.config(text="Place your finger on the reader now")

    def _scan_ok(self):
        self._fp.stop_ok()
        self._scan_lbl.config(text="CAPTURED ✔", fg=GREEN2)
        self._scan_sub.config(text="Processing…")

    def _scan_err(self, msg="FAILED"):
        self._fp.stop_err(msg)
        self._scan_lbl.config(text=msg, fg=RED2)
        self._scan_sub.config(text="Please try again")

    def _scan_reset(self):
        self._fp.reset()
        self._scan_lbl.config(text="READY", fg=MUTED)
        self._scan_sub.config(text="Place finger when prompted")

    # ------ STATUS / BUTTONS ------
    def _set_status(self, text, fg=ACCENT, bg=ACCENT_DIM, border=ACCENT):
        self.sf.config(bg=bg, highlightbackground=border)
        for w in self.sf.winfo_children():
            for iw in [w] + list(w.winfo_children()):
                try: iw.config(bg=bg)
                except Exception: pass
        self.sl.config(text=text, fg=fg, bg=bg)
        try:
            self._status_led.config(bg=bg)
            self._status_led.set_color(fg)
            self._led.set_color(fg)
        except Exception: pass

    def _set_buttons(self, in_s, out_s):
        self.btn_in.config(state=in_s,
                           bg=GREEN if in_s == tk.NORMAL else GREEN_DIM,
                           fg=BG if in_s == tk.NORMAL else MUTED)
        self.btn_out.config(state=out_s,
                            bg=RED if out_s == tk.NORMAL else RED_DIM,
                            fg=WHITE if out_s == tk.NORMAL else MUTED)

    def _set_avatar(self, name=None, color=BORDER):
        self._avatar_cv.itemconfig(self._avatar_circle, fill=color)
        self._avatar_cv.itemconfig(self._avatar_text,
                                   text=_initials(name) if name else "",
                                   fill=WHITE if name else MUTED)

    def _apply_status(self, status, name=None, ci_time=""):
        if status == "done":
            self._set_buttons(tk.DISABLED, tk.DISABLED)
            self._set_status("Attendance complete — see you tomorrow", RED, RED_DIM, RED)
            self._set_avatar(name, RED_DIM)
        elif status == "checked_in":
            self._set_buttons(tk.DISABLED, tk.NORMAL)
            msg = (f"Already checked IN at {ci_time} — proceed to Check-Out"
                   if ci_time else "Already checked IN — proceed to Check-Out")
            self._set_status(msg, ORANGE, ORANGE_DIM, ORANGE)
            self._set_avatar(name, ORANGE_DIM)
        elif status == "none":
            self._set_buttons(tk.NORMAL, tk.DISABLED)
            self._set_status("Ready to CHECK IN", GREEN, GREEN_DIM, GREEN)
            self._set_avatar(name, GREEN_DIM)
        else:
            self._set_buttons(tk.DISABLED, tk.DISABLED)
            self._set_status("Awaiting Worker ID", ACCENT, ACCENT_DIM, ACCENT)
            self._set_avatar(None, BORDER)

    # ------ KEY / ENTER ------
    def _on_key(self, _=None):
        if self._debounce_job:
            self.root.after_cancel(self._debounce_job)
        uid = self.user_entry.get().strip()
        if not uid:
            self._soft_reset(); return
        self._apply_status(get_worker_status(uid))
        self._debounce_job = self.root.after(
            650, lambda: threading.Thread(
                target=self._validate, args=(uid,), daemon=True).start())

    def _validate(self, uid: str):
        if self.user_entry.get().strip() != uid or self._busy:
            return
        worker = find_worker(uid)
        def _upd():
            if self.user_entry.get().strip() != uid:
                return
            if not worker:
                self.name_lbl.config(text="Unknown ID", fg=RED2)
                self.hint_lbl.config(
                    text=f"ID '{uid}' not found — check attendance.log for details", fg=RED)
                self._set_buttons(tk.DISABLED, tk.DISABLED)
                self._set_status(f"Worker ID {uid} not found — see log", RED, RED_DIM, RED)
                self._set_avatar(None, RED_DIM)
                self.log(f"Worker ID {uid} lookup failed — check attendance.log", "err")
            else:
                name   = worker.get("Full_Name", "N/A")
                status = get_worker_status(uid)
                self.name_lbl.config(text=name, fg=WHITE)
                ci_time_hint = ""
                if status in ("checked_in", "done"):
                    lk  = load_lock()
                    rec = (lk.get("checked_in", {}).get(str(uid)) or
                           lk.get("checked_out", {}).get(str(uid)))
                    if isinstance(rec, dict):
                        raw = rec.get("time", "") or rec.get("checkin_time", "")
                        try:
                            ci_time_hint = datetime.strptime(
                                raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M")
                        except Exception:
                            ci_time_hint = raw[-5:] if len(raw) >= 5 else raw
                hints = {
                    "checked_in": (
                        f"Checked in at {ci_time_hint} — use Check-Out"
                        if ci_time_hint else "Checked in today — use Check-Out", ORANGE),
                    "done": (
                        f"Attendance complete — checked in at {ci_time_hint}"
                        if ci_time_hint else "Attendance complete for today", RED),
                    "none": ("Not yet checked in today", TEXT2),
                }
                htxt, hcol = hints.get(status, ("", TEXT2))
                self.hint_lbl.config(text=htxt, fg=hcol)
                self._apply_status(status, name, ci_time=ci_time_hint)
        self.root.after(0, _upd)

    def _on_enter(self, _=None):
        uid = self.user_entry.get().strip()
        if not uid or self._busy: return
        s = get_worker_status(uid)
        if s == "none":       self._trigger("checkin")
        elif s == "checked_in": self._trigger("checkout")

    # ------ PROCESS ------
    def _trigger(self, action: str):
        if self._busy: return
        uid = self.user_entry.get().strip()
        if not uid: return
        self._busy = True
        self._set_buttons(tk.DISABLED, tk.DISABLED)
        verb = "CHECK IN" if action == "checkin" else "CHECK OUT"
        self._set_status(f"Scanning fingerprint for {verb}…", ORANGE, ORANGE_DIM, ORANGE)
        self.root.after(0, self._scan_start)
        threading.Thread(target=self._process, args=(uid, action), daemon=True).start()

    def _process(self, uid: str, action: str):
        is_open = False; success = False; msg = ""; full_name = uid
        try:
            self.log(f"{'─'*16} {action.upper()} · ID {uid} {'─'*16}", "div")

            if zk.GetDeviceCount() == 0:
                self.log("Scanner not connected", "err")
                self._gui(lambda: self._scan_err("NO DEVICE"))
                self._gui(lambda: self._show_flash(
                    "⚠", "Scanner Not Connected",
                    "Connect the fingerprint device and try again.", "", "#6d28d9"))
                return

            zk.OpenDevice(0); is_open = True
            self.log("Waiting for fingerprint…", "info")
            capture = None
            for _ in range(150):
                capture = zk.AcquireFingerprint()
                if capture: break
                time.sleep(0.2)

            if not capture:
                self.log("Scan timed out", "err")
                self._gui(lambda: self._scan_err("TIMEOUT"))
                self._gui(lambda: self._show_flash(
                    "⏱", "Scan Timeout", "No fingerprint detected.", "", "#92400e"))
                return

            self._gui(self._scan_ok)
            self.log("Fingerprint captured ✔", "ok")

            _wcache_invalidate(uid)
            worker = find_worker(uid, force_refresh=True)
            if not worker:
                self.log(f"ID {uid} not found in Zoho — check attendance.log", "err")
                self._gui(lambda: self._scan_err("NOT FOUND"))
                self._gui(lambda: self._show_flash(
                    "✗", "Worker Not Found",
                    f"ID {uid} does not exist.\nCheck attendance.log for diagnostics.",
                    "", RED_DIM))
                return

            full_name = worker.get("Full_Name", uid)
            self.log(f"Identity: {full_name}", "ok")

            status = get_worker_status(uid)

            if status == "done":
                self.log("Already complete", "warn")
                self._gui(lambda: self._show_flash(
                    "🔒", "Already Complete", full_name, "Done for today.", "#1e0a40"))
                self.root.after(2600, lambda: self._apply_status("done", full_name))
                return

            if status == "checked_in" and action == "checkin":
                _ci_rec = load_lock().get("checked_in", {}).get(str(uid), {})
                _ci_raw = _ci_rec.get("time", "") if isinstance(_ci_rec, dict) else ""
                try:
                    _ci_t = datetime.strptime(_ci_raw, "%d-%b-%Y %H:%M:%S").strftime("%H:%M")
                except Exception:
                    _ci_t = _ci_raw[-5:] if len(_ci_raw) >= 5 else _ci_raw
                _ci_msg = f"Checked in at {_ci_t}" if _ci_t else "Use Check-Out instead."
                self.log(f"Already checked IN at {_ci_t}", "warn")
                self._gui(lambda: self._show_flash(
                    "↩", "Already Checked In", full_name, _ci_msg, "#3d1f00"))
                self.root.after(2600, lambda: self._apply_status(
                    "checked_in", full_name, ci_time=_ci_t))
                return

            if status == "none" and action == "checkout":
                self.log("Not checked IN yet", "warn")
                self._gui(lambda: self._show_flash(
                    "⚠", "Not Checked In", full_name, "Check IN first.", "#1e0a40"))
                self.root.after(2600, lambda: self._apply_status("none", full_name))
                return

            self.log(f"Posting {action.upper()} to Zoho…", "info")
            pa  = worker.get("Projects_Assigned")
            pid = pa.get("ID") if isinstance(pa, dict) else DEFAULT_PROJECT_ID
            success, msg = log_attendance(
                worker["ID"], uid, pid, full_name, action, self.log)

            tag = "ok" if success else "err"
            for line in msg.splitlines():
                if line.strip():
                    ltag = tag
                    if "late"     in line.lower(): ltag = "late"
                    if "overtime" in line.lower(): ltag = "ot"
                    if "early"    in line.lower(): ltag = "early"
                    self.log(line.strip(), ltag)

            if success:
                verb      = "Checked IN" if action == "checkin" else "Checked OUT"
                sub       = datetime.now().strftime("Time: %H:%M:%S · %A, %d %B %Y")
                extra     = ""
                flash_col = "#1d4ed8"

                if action == "checkin" and is_late(datetime.now()):
                    extra     = f"⚠ Late arrival — {late_by_str(datetime.now())}"
                    flash_col = "#92400e"

                if action == "checkout":
                    lock2  = load_lock()
                    co     = lock2.get("checked_out", {}).get(str(uid), {})
                    ot     = co.get("overtime_hours", 0) if isinstance(co, dict) else 0
                    now_   = datetime.now()
                    checkin_raw = co.get("checkin_time", "") if isinstance(co, dict) else ""
                    try:
                        ci_dt  = datetime.strptime(checkin_raw, "%d-%b-%Y %H:%M:%S")
                        ci_disp = ci_dt.strftime("%H:%M:%S")
                    except Exception:
                        ci_disp = (checkin_raw[-8:] if len(checkin_raw) >= 8
                                   else checkin_raw or "—")
                    co_disp = now_.strftime("%H:%M:%S")
                    sub  = (f"IN {ci_disp} → OUT {co_disp}"
                            f"\n{now_.strftime('%A, %d %B %Y')}")
                    if ot > 0:
                        extra = f"⏱ Overtime: {int(ot)}h {int((ot%1)*60)}m"

                ev_tag = "in" if action == "checkin" else "out"
                _v, _s, _e, _fc = verb, sub, extra, flash_col
                self._gui(lambda: self._add_event(_v, full_name, ev_tag))
                self._gui(self._tick_stats)
                self._gui(lambda: self._show_flash(
                    "✔", f"{_v} — {full_name}", _s, _e, _fc))
            else:
                _m = msg.splitlines()[0][:80] if msg else "Unknown error"
                self._gui(lambda: self._scan_err("ERROR"))
                self._gui(lambda: self._show_flash("✗", "Action Failed", _m, "", RED_DIM))

        except Exception as exc:
            _log.exception(f"_process error: {exc}")
            self.log(f"Unexpected error: {exc}", "err")
        finally:
            if is_open:
                try: zk.CloseDevice()
                except Exception: pass
            self._busy = False
            self.root.after(2600, self._scan_reset)
            self.root.after(2600, lambda: self._reset_ui(clear_log=success))

    def _reset_ui(self, clear_log=False):
        self.user_entry.delete(0, tk.END)
        self.name_lbl.config(text="—", fg=MUTED)
        self.hint_lbl.config(text="Enter a Worker ID above", fg=MUTED)
        self._set_avatar(None, BORDER)
        self._set_buttons(tk.DISABLED, tk.DISABLED)
        self._set_status("Awaiting Worker ID", ACCENT, ACCENT_DIM, ACCENT)
        if clear_log:
            self._clear_log()
        self.log("Ready for next worker.", "div")
        self.user_entry.focus_set()

    def _soft_reset(self):
        self.name_lbl.config(text="—", fg=MUTED)
        self.hint_lbl.config(text="Enter a Worker ID above", fg=MUTED)
        self._set_avatar(None, BORDER)
        self._set_buttons(tk.DISABLED, tk.DISABLED)
        self._set_status("Awaiting Worker ID", ACCENT, ACCENT_DIM, ACCENT)

    def _on_close(self):
        try: zk.Terminate()
        except Exception: pass
        self.root.destroy()

# ===========================================================
if __name__ == "__main__":
    root = tk.Tk()
    FingerprintGUI(root)
    root.mainloop()