# """
# fp_store.py — Fingerprint Storage & Verification
# =================================================
# Stores fingerprint templates in SQLite locally.
# Typed Worker ID MUST match the scanned finger — otherwise BLOCKED.

# HOW TO USE
# ----------
# 1.  Drop this file next to your main attendance script.

# 2.  After zk.Init() add:
#         import fp_store
#         fp_store.init(zk, zoho_request, auth_headers,
#                       API_DOMAIN, APP_OWNER, APP_NAME, WORKERS_REPORT)

# 3.  In FingerprintGUI._process() REPLACE the scanner block
#     (from "zk.OpenDevice(0)" to "zk.CloseDevice()") with:

#         self.log("Place finger on scanner…", "info")
#         ok, msg, full_name = fp_store.verify(uid)
#         if not ok:
#             self.log(msg, "err")
#             self._gui(lambda: self._scan_err("BLOCKED"))
#             self._gui(lambda: self._show_flash("✗", "Access Denied", msg, "", RED_DIM))
#             return
#         self._gui(self._scan_ok)
#         self.log(f"Verified: {full_name} ✔", "ok")

# 4.  In AdminPanel._build() after creating the notebook add:
#         fp_store.build_enroll_tab(nb, self, find_worker)
# """

# import os, time, sqlite3, base64, threading, logging, tkinter as tk
# from tkinter import ttk
# from datetime import datetime
# from typing import Optional

# _log = logging.getLogger("fp_store")

# # ── globals set by init() ─────────────────────────────────────────────────────
# _zk             = None
# _zoho_request   = None
# _auth_headers   = None
# _API_DOMAIN     = ""
# _APP_OWNER      = ""
# _APP_NAME       = ""
# _WORKERS_REPORT = "All_Workers"

# DB_PATH         = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fp_templates.db")
# _DB_LOCK        = threading.Lock()
# MATCH_THRESHOLD = 50        # ZKTeco score 0–100; ≥50 = same finger

# # colours matching your main script
# BG="#07090f";  CARD="#0c1018";    CARD2="#10151f";  BORDER="#1c2438"
# BORDER2="#243048"; ACCENT2="#60a5fa"
# GREEN2="#34d399";  GREEN_DIM="#052e1c"
# RED="#f43f5e";     RED2="#fb7185";  RED_DIM="#4c0519"
# ORANGE2="#fbbf24"; ORANGE_DIM="#3d1f00"
# TEAL="#2dd4bf";    TEAL_DIM="#042f2e"
# TEXT="#e2e8f0";    TEXT2="#94a3b8"; MUTED="#3d4f69"; WHITE="#ffffff"


# # =============================================================================
# # INIT
# # =============================================================================

# def init(zk_instance, zoho_request_fn, auth_headers_fn,
#          api_domain, app_owner, app_name, workers_report="All_Workers"):
#     """Call once after zk.Init() at startup."""
#     global _zk, _zoho_request, _auth_headers
#     global _API_DOMAIN, _APP_OWNER, _APP_NAME, _WORKERS_REPORT
#     _zk             = zk_instance
#     _zoho_request   = zoho_request_fn
#     _auth_headers   = auth_headers_fn
#     _API_DOMAIN     = api_domain
#     _APP_OWNER      = app_owner
#     _APP_NAME       = app_name
#     _WORKERS_REPORT = workers_report
#     _create_db()
#     n = count_enrolled()
#     _log.info("fp_store ready | DB: %s | enrolled: %d", DB_PATH, n)
#     print(f"[fp_store] Ready — {n} workers enrolled in SQLite")


# # =============================================================================
# # VERIFICATION  (call this in _process)
# # =============================================================================

# def verify(zk_user_id: str, timeout_seconds: int = 20) -> tuple:
#     """
#     Gate check — typed ID must match scanned finger.

#     Returns
#     -------
#     (True,  "",    worker_name)  →  identity confirmed, allow attendance
#     (False, msg,   "")           →  blocked, show msg on screen
#     """
#     uid = str(zk_user_id).strip()

#     # ── 1. check enrolled ────────────────────────────────────────────────────
#     stored_b64, worker_name = _get_stored(uid)
#     if not stored_b64:
#         msg = (f"❌  Worker ID {uid} has no fingerprint stored.\n"
#                f"Ask a supervisor to enrol your fingerprint first.")
#         _log.warning("verify: ID %s not enrolled", uid)
#         return False, msg, ""

#     # ── 2. scanner ready ─────────────────────────────────────────────────────
#     if _zk is None:
#         return False, "Fingerprint system not initialised.", ""
#     if _zk.GetDeviceCount() == 0:
#         return False, "Scanner not connected — contact IT support.", ""

#     # ── 3. scan finger ───────────────────────────────────────────────────────
#     _zk.OpenDevice(0)
#     try:
#         capture = None
#         for _ in range(timeout_seconds * 5):
#             capture = _zk.AcquireFingerprint()
#             if capture:
#                 break
#             time.sleep(0.2)

#         if not capture:
#             return False, "Scan timed out — please try again.", ""

#         # ── 4. compare scan vs stored template ───────────────────────────────
#         stored = base64.b64decode(stored_b64)
#         score  = _zk.DBMatch(capture, stored)

#         _log.info("verify | ID=%s | worker=%s | score=%d | threshold=%d",
#                   uid, worker_name, score, MATCH_THRESHOLD)

#         if score >= MATCH_THRESHOLD:
#             return True, "", worker_name
#         else:
#             msg = (f"❌  Fingerprint does NOT match ID {uid}.\n"
#                    f"Only {worker_name} can check in or out on this ID.")
#             return False, msg, ""

#     except Exception as e:
#         _log.exception("verify error: %s", e)
#         return False, f"Scanner error: {e}", ""
#     finally:
#         try: _zk.CloseDevice()
#         except Exception: pass


# # =============================================================================
# # ENROLMENT
# # =============================================================================

# def enroll_worker(zk_user_id: str, zoho_worker_id: str, worker_name: str,
#                   samples: int = 3, progress_cb=None) -> tuple:
#     """
#     Scan finger `samples` times, merge, save to SQLite, push to Zoho.
#     Returns (True, "success msg") or (False, "error msg").
#     """
#     def _p(msg, tag="info"):
#         _log.info("enroll [%s]: %s", worker_name, msg)
#         if progress_cb:
#             try:    progress_cb(msg, tag)
#             except TypeError:
#                 try: progress_cb(msg)
#                 except Exception: pass

#     if _zk is None:          return False, "fp_store not initialised."
#     if _zk.GetDeviceCount() == 0: return False, "Scanner not connected."

#     _zk.OpenDevice(0)
#     try:
#         captures = []
#         for i in range(1, samples + 1):
#             _p(f"Scan {i} of {samples} — place finger on scanner…", "info")
#             cap = None
#             for _ in range(150):
#                 cap = _zk.AcquireFingerprint()
#                 if cap: break
#                 time.sleep(0.2)
#             if not cap:
#                 return False, f"Scan {i} timed out — please try again."
#             _p(f"Scan {i} captured ✔  — lift finger", "ok")
#             captures.append(cap)
#             time.sleep(0.8)

#         merged = _merge(captures)
#         if not merged:
#             return False, "Template merge failed — please try again."

#         template_b64 = base64.b64encode(merged).decode()
#         _save(zk_user_id, zoho_worker_id, worker_name, template_b64)
#         _p("Saved to SQLite ✔", "ok")
#         _push_zoho_bg(zoho_worker_id, template_b64, worker_name)
#         _p(f"Enrolment complete for {worker_name} ✔", "ok")
#         return True, f"{worker_name} enrolled successfully."

#     except Exception as e:
#         _log.exception("enroll_worker: %s", e)
#         return False, f"Enrolment error: {e}"
#     finally:
#         try: _zk.CloseDevice()
#         except Exception: pass


# def sync_from_zoho(progress_cb=None) -> tuple:
#     """
#     Pull ALL worker records from Zoho and import any fingerprint templates.
#     Called automatically at startup in a background thread.
#     Returns (imported, skipped).
#     """
#     def _p(msg):
#         _log.info("sync_from_zoho: %s", msg)
#         if progress_cb:
#             try: progress_cb(msg)
#             except Exception: pass

#     if not (_zoho_request and _auth_headers and _API_DOMAIN):
#         _p("Skipping Zoho sync — fp_store not fully initialised")
#         return 0, 0

#     hdrs = _auth_headers()
#     if not hdrs:
#         _p("Skipping Zoho sync — no valid token")
#         return 0, 0

#     url = f"{_API_DOMAIN}/{_APP_OWNER}/{_APP_NAME}/report/{_WORKERS_REPORT}"
#     r   = _zoho_request("GET", url, headers=hdrs)
#     if not (r and r.status_code == 200):
#         _p(f"Zoho sync failed — HTTP {r.status_code if r else 'timeout'}")
#         return 0, 0

#     records = r.json().get("data", [])
#     _p(f"Fetched {len(records)} worker record(s) from Zoho")
#     return load_from_records(records)


# def load_from_records(records: list) -> tuple:
#     """
#     Bulk-load existing templates from Zoho/ZK worker dicts.
#     Handles both 'template_b64' (base-64) and 'template' (hex) fields.
#     Returns (imported, skipped).
#     """
#     imported = skipped = 0
#     for rec in records:
#         tmpl = _extract_template(rec)
#         if not tmpl:
#             skipped += 1; continue
#         zk_id = str(
#             rec.get("Worker_ID") or rec.get("ZKTeco_User_ID2") or
#             rec.get("fid") or rec.get("zoho_id") or rec.get("ID") or ""
#         ).strip().split(".")[0]
#         if not zk_id or zk_id in ("0", "None", ""):
#             skipped += 1; continue
#         zoho_id = str(rec.get("ID") or rec.get("zoho_id") or zk_id)
#         name    = rec.get("Full_Name") or rec.get("worker_name") or f"Worker {zk_id}"
#         _save(zk_id, zoho_id, name, tmpl)
#         imported += 1
#     _log.info("load_from_records: %d imported, %d skipped", imported, skipped)
#     return imported, skipped


# # =============================================================================
# # DB HELPERS
# # =============================================================================

# def is_enrolled(zk_user_id: str) -> bool:
#     return _get_stored(str(zk_user_id))[0] is not None

# def count_enrolled() -> int:
#     with _DB_LOCK:
#         c = _open_db()
#         try:    return c.execute("SELECT COUNT(*) FROM fp_templates").fetchone()[0]
#         finally: c.close()

# def list_enrolled() -> list:
#     with _DB_LOCK:
#         c = _open_db()
#         try:
#             rows = c.execute(
#                 "SELECT zk_user_id, worker_name, enrolled_at, updated_at "
#                 "FROM fp_templates ORDER BY worker_name").fetchall()
#             return [{"zk_user_id": r[0], "worker_name": r[1],
#                      "enrolled_at": r[2], "updated_at": r[3]} for r in rows]
#         finally: c.close()

# def delete_template(zk_user_id: str):
#     with _DB_LOCK:
#         c = _open_db()
#         try:
#             c.execute("DELETE FROM fp_templates WHERE zk_user_id=?", (str(zk_user_id),))
#             c.commit()
#         finally: c.close()


# # =============================================================================
# # ADMIN PANEL — FINGERPRINTS TAB
# # =============================================================================

# def build_enroll_tab(notebook: ttk.Notebook, parent_win, find_worker_fn=None):
#     """
#     Adds '👆 FINGERPRINTS' tab to Admin Panel notebook.

#         fp_store.build_enroll_tab(nb, self, find_worker)
#     """
#     tab = tk.Frame(notebook, bg=BG)
#     notebook.add(tab, text="👆  FINGERPRINTS")
#     _EnrollTab(tab, parent_win, find_worker_fn)
#     return tab


# class _EnrollTab:
#     def __init__(self, parent, win, find_worker_fn):
#         self._win    = win
#         self._fw     = find_worker_fn
#         self._busy   = False
#         self._build(parent)
#         self._refresh()

#     def _build(self, p):
#         # header bar
#         tk.Frame(p, bg=TEAL, height=3).pack(fill=tk.X)
#         hdr = tk.Frame(p, bg=CARD, padx=20, pady=12); hdr.pack(fill=tk.X)
#         lf  = tk.Frame(hdr, bg=CARD); lf.pack(side=tk.LEFT)
#         tk.Label(lf, text="FINGERPRINT ENROLMENT",
#                  font=("Courier", 12, "bold"), bg=CARD, fg=TEAL).pack(anchor="w")
#         tk.Label(lf, text="Workers must be enrolled here before they can check in or out.",
#                  font=("Courier", 8), bg=CARD, fg=TEXT2).pack(anchor="w", pady=(2,0))
#         self._count_lbl = tk.Label(hdr, text="", font=("Courier", 9, "bold"),
#                                    bg=CARD, fg=TEAL)
#         self._count_lbl.pack(side=tk.RIGHT)
#         tk.Frame(p, bg=BORDER2, height=1).pack(fill=tk.X)

#         # body
#         body = tk.Frame(p, bg=BG, padx=20, pady=16)
#         body.pack(fill=tk.BOTH, expand=True)
#         body.columnconfigure(0, weight=1); body.columnconfigure(1, weight=2)

#         # ── LEFT: form ───────────────────────────────────────────────────────
#         L = tk.Frame(body, bg=CARD, highlightbackground=BORDER2,
#                      highlightthickness=1, padx=16, pady=14)
#         L.grid(row=0, column=0, sticky="nsew", padx=(0,12))

#         tk.Label(L, text="WORKER ID", font=("Courier", 7, "bold"),
#                  bg=CARD, fg=MUTED).pack(anchor="w")
#         bf = tk.Frame(L, bg=TEAL, padx=1, pady=1); bf.pack(fill=tk.X, pady=(4,10))
#         bi = tk.Frame(bf, bg=CARD2);                bi.pack(fill=tk.X)
#         self._id_var = tk.StringVar()
#         self._id_var.trace_add("write", lambda *_: self._on_id())
#         self._id_ent = tk.Entry(bi, textvariable=self._id_var,
#                                 font=("Courier", 22, "bold"),
#                                 bg=CARD2, fg=WHITE, insertbackground=TEAL, bd=0)
#         self._id_ent.pack(padx=10, pady=8, fill=tk.X)
#         self._id_ent.focus_set()

#         self._name_lbl = tk.Label(L, text="Enter an ID above",
#                                   font=("Courier", 10), bg=CARD, fg=MUTED)
#         self._name_lbl.pack(anchor="w", pady=(0,4))

#         self._status_lbl = tk.Label(L, text="", font=("Courier", 8, "bold"),
#                                     bg=CARD, fg=MUTED)
#         self._status_lbl.pack(anchor="w", pady=(0,12))

#         # scans selector
#         tk.Label(L, text="NUMBER OF SCANS", font=("Courier", 7, "bold"),
#                  bg=CARD, fg=MUTED).pack(anchor="w")
#         sr = tk.Frame(L, bg=CARD); sr.pack(anchor="w", pady=(4,14))
#         self._samples = tk.IntVar(value=3)
#         for n in (2, 3, 4):
#             tk.Radiobutton(sr, text=str(n), variable=self._samples, value=n,
#                            font=("Courier", 11, "bold"), bg=CARD, fg=TEAL,
#                            selectcolor=CARD2, activebackground=CARD
#                            ).pack(side=tk.LEFT, padx=(0,14))

#         # action buttons
#         self._btn_enrol = self._btn(L, "👆  ENROL (new)",        TEAL_DIM,    TEAL,   self._do_enrol)
#         self._btn_enrol.pack(fill=tk.X, pady=(0,6))
#         self._btn_reenrol = self._btn(L, "🔄  RE-ENROL (replace)", ORANGE_DIM, ORANGE2, self._do_reenrol)
#         self._btn_reenrol.pack(fill=tk.X, pady=(0,6))
#         self._btn_delete  = self._btn(L, "🗑  DELETE TEMPLATE",    RED_DIM,    RED2,    self._do_delete)
#         self._btn_delete.pack(fill=tk.X)

#         tk.Frame(L, bg=BORDER, height=1).pack(fill=tk.X, pady=12)

#         tk.Label(L, text="PROGRESS", font=("Courier", 7, "bold"),
#                  bg=CARD, fg=MUTED).pack(anchor="w")
#         self._log_box = tk.Text(L, font=("Courier", 8), bg=CARD2, fg=TEXT2,
#                                 height=9, relief=tk.FLAT, padx=8, pady=6, state=tk.DISABLED)
#         self._log_box.pack(fill=tk.X, pady=(4,0))
#         for tag, col in [("ok",GREEN2),("err",RED2),("warn",ORANGE2),("info",ACCENT2)]:
#             self._log_box.tag_config(tag, foreground=col)

#         # ── RIGHT: enrolled list ─────────────────────────────────────────────
#         R = tk.Frame(body, bg=BG); R.grid(row=0, column=1, sticky="nsew")
#         R.rowconfigure(1, weight=1); R.columnconfigure(0, weight=1)

#         rh = tk.Frame(R, bg=BG); rh.grid(row=0, column=0, sticky="ew", pady=(0,8))
#         tk.Label(rh, text="ENROLLED WORKERS", font=("Courier", 9, "bold"),
#                  bg=BG, fg=MUTED).pack(side=tk.LEFT)
#         tk.Button(rh, text="↻ REFRESH", font=("Courier", 8, "bold"),
#                   relief=tk.FLAT, bg=BORDER, fg=TEXT2, cursor="hand2",
#                   padx=8, pady=4, command=self._refresh).pack(side=tk.RIGHT)

#         style = ttk.Style()
#         style.configure("FP.Treeview", background=CARD2, foreground=TEXT,
#                         fieldbackground=CARD2, rowheight=30,
#                         font=("Courier", 9), borderwidth=0)
#         style.configure("FP.Treeview.Heading", background=CARD,
#                         foreground=TEAL, font=("Courier", 8, "bold"), relief="flat")
#         style.map("FP.Treeview",
#                   background=[("selected", TEAL_DIM)],
#                   foreground=[("selected", TEAL)])

#         self._tree = ttk.Treeview(R, columns=("ID","Name","Enrolled","Updated"),
#                                   show="headings", style="FP.Treeview", selectmode="browse")
#         for col, w, anc, stretch in [
#             ("ID",70,"center",False), ("Name",220,"w",True),
#             ("Enrolled",140,"center",False), ("Updated",140,"center",False)]:
#             self._tree.heading(col, text=col.upper())
#             self._tree.column(col, width=w, anchor=anc, stretch=stretch)
#         self._tree.grid(row=1, column=0, sticky="nsew")
#         self._tree.bind("<<TreeviewSelect>>", self._on_select)

#         vsb = ttk.Scrollbar(R, orient="vertical", command=self._tree.yview)
#         self._tree.configure(yscrollcommand=vsb.set)
#         vsb.grid(row=1, column=1, sticky="ns")

#     def _btn(self, parent, text, bg, fg, cmd):
#         return tk.Button(parent, text=text, font=("Courier", 10, "bold"),
#                          relief=tk.FLAT, bg=bg, fg=fg,
#                          activebackground=fg, activeforeground=BG,
#                          cursor="hand2", pady=10, state=tk.DISABLED, command=cmd)

#     # ── events ────────────────────────────────────────────────────────────────

#     def _on_id(self):
#         uid = self._id_var.get().strip()
#         if not uid:
#             self._name_lbl.config(text="Enter an ID above", fg=MUTED)
#             self._status_lbl.config(text="")
#             self._set_btns(None); return

#         enrolled = is_enrolled(uid)
#         self._status_lbl.config(
#             text="● ENROLLED — fingerprint on file" if enrolled else "○ NOT YET ENROLLED",
#             fg=GREEN2 if enrolled else ORANGE2)
#         self._set_btns(uid)

#         if self._fw:
#             threading.Thread(target=self._lookup, args=(uid,), daemon=True).start()

#     def _lookup(self, uid):
#         try:    w = self._fw(uid)
#         except: w = None
#         def _u():
#             if self._id_var.get().strip() != uid: return
#             if w:   self._name_lbl.config(text=w.get("Full_Name", uid), fg=WHITE)
#             else:   self._name_lbl.config(text=f"ID {uid} not found in Zoho", fg=RED2)
#         try: self._win.after(0, _u)
#         except Exception: pass

#     def _on_select(self, _=None):
#         sel = self._tree.selection()
#         if sel: self._id_var.set(self._tree.item(sel[0], "values")[0])

#     def _set_btns(self, uid):
#         if uid and not self._busy:
#             e = is_enrolled(uid)
#             self._btn_enrol.config(
#                 state=tk.NORMAL if not e else tk.DISABLED,
#                 bg=TEAL_DIM if not e else BORDER, fg=TEAL if not e else MUTED)
#             self._btn_reenrol.config(
#                 state=tk.NORMAL if e else tk.DISABLED,
#                 bg=ORANGE_DIM if e else BORDER, fg=ORANGE2 if e else MUTED)
#             self._btn_delete.config(
#                 state=tk.NORMAL if e else tk.DISABLED,
#                 bg=RED_DIM if e else BORDER, fg=RED2 if e else MUTED)
#         else:
#             for b in (self._btn_enrol, self._btn_reenrol, self._btn_delete):
#                 b.config(state=tk.DISABLED, bg=BORDER, fg=MUTED)

#     # ── actions ───────────────────────────────────────────────────────────────

#     def _resolve(self):
#         uid = self._id_var.get().strip()
#         if not uid:
#             self._plog("Enter a Worker ID first.", "warn")
#             return None, None, None
#         name = self._name_lbl.cget("text")
#         zoho_id = uid
#         if self._fw:
#             try:
#                 w = self._fw(uid)
#                 if w:
#                     name    = w.get("Full_Name", uid)
#                     zoho_id = w.get("ID", uid)
#             except Exception: pass
#         return uid, zoho_id, name

#     def _do_enrol(self):
#         uid, zoho_id, name = self._resolve()
#         if not uid: return
#         if is_enrolled(uid):
#             self._plog(f"{name} already enrolled — use Re-Enrol.", "warn"); return
#         self._run(uid, zoho_id, name)

#     def _do_reenrol(self):
#         uid, zoho_id, name = self._resolve()
#         if not uid: return
#         delete_template(uid)
#         self._plog(f"Old template removed for {name}.", "warn")
#         self._run(uid, zoho_id, name)

#     def _do_delete(self):
#         uid, _, name = self._resolve()
#         if not uid: return
#         delete_template(uid)
#         self._plog(f"Template deleted for {name} (ID {uid}).", "warn")
#         self._status_lbl.config(text="○ NOT YET ENROLLED", fg=ORANGE2)
#         self._set_btns(uid); self._refresh()

#     def _run(self, uid, zoho_id, name):
#         self._busy = True
#         self._set_btns(None)
#         self._plog(f"Starting enrolment for {name}…", "info")

#         def _thread():
#             ok, msg = enroll_worker(
#                 zk_user_id=uid, zoho_worker_id=zoho_id,
#                 worker_name=name, samples=self._samples.get(),
#                 progress_cb=lambda m, t="info": self._go(lambda: self._plog(m, t)))
#             def _done():
#                 self._plog(msg, "ok" if ok else "err")
#                 self._busy = False
#                 self._set_btns(uid); self._refresh()
#                 self._status_lbl.config(
#                     text="● ENROLLED — fingerprint on file" if ok else "✗ Enrolment failed",
#                     fg=GREEN2 if ok else RED2)
#             self._go(_done)

#         threading.Thread(target=_thread, daemon=True).start()

#     # ── helpers ───────────────────────────────────────────────────────────────

#     def _refresh(self):
#         self._tree.delete(*self._tree.get_children())
#         for w in list_enrolled():
#             self._tree.insert("", tk.END, values=(
#                 w["zk_user_id"], w["worker_name"],
#                 w["enrolled_at"][:16], w["updated_at"][:16]))
#         n = count_enrolled()
#         self._count_lbl.config(text=f"{n} worker{'s' if n!=1 else ''} enrolled")

#     def _plog(self, msg, tag="info"):
#         self._log_box.config(state=tk.NORMAL)
#         self._log_box.insert(tk.END,
#                              f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n", tag)
#         self._log_box.see(tk.END)
#         self._log_box.config(state=tk.DISABLED)

#     def _go(self, fn):
#         try: self._win.after(0, fn)
#         except Exception: pass


# # =============================================================================
# # PRIVATE HELPERS
# # =============================================================================

# def _get_stored(zk_user_id: str):
#     """Returns (template_b64, worker_name) or (None, '')."""
#     with _DB_LOCK:
#         c = _open_db()
#         try:
#             row = c.execute(
#                 "SELECT template_b64, worker_name FROM fp_templates WHERE zk_user_id=?",
#                 (str(zk_user_id),)).fetchone()
#             return (row[0], row[1]) if row else (None, "")
#         finally: c.close()

# def _extract_template(rec: dict) -> Optional[str]:
#     """Accept template_b64 (base-64) or template (hex) from Zoho records."""
#     b64 = rec.get("template_b64", "")
#     if b64 and len(b64) > 20:
#         try:
#             if len(base64.b64decode(b64)) > 10: return b64
#         except Exception: pass
#     h = rec.get("template", "")
#     if h and len(h) > 20:
#         try:
#             raw = bytes.fromhex(h)
#             if len(raw) > 10: return base64.b64encode(raw).decode()
#         except Exception: pass
#     return None

# def _save(zk_user_id, zoho_worker_id, worker_name, template_b64):
#     now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#     with _DB_LOCK:
#         c = _open_db()
#         try:
#             c.execute("""
#                 INSERT INTO fp_templates
#                     (zk_user_id, zoho_worker_id, worker_name, template_b64, enrolled_at, updated_at)
#                 VALUES (?,?,?,?,?,?)
#                 ON CONFLICT(zk_user_id) DO UPDATE SET
#                     zoho_worker_id = excluded.zoho_worker_id,
#                     worker_name    = excluded.worker_name,
#                     template_b64   = excluded.template_b64,
#                     updated_at     = excluded.updated_at
#             """, (str(zk_user_id), str(zoho_worker_id),
#                   str(worker_name), template_b64, now, now))
#             c.commit()
#             _log.info("Saved template: %s (ID %s)", worker_name, zk_user_id)
#         except Exception as e:
#             _log.error("_save error: %s", e)
#         finally: c.close()

# def _merge(captures):
#     if not captures: return None
#     if len(captures) == 1: return captures[0]
#     try:
#         t1, t2 = captures[0], captures[1]
#         t3 = captures[2] if len(captures) >= 3 else captures[1]
#         merged = _zk.DBMerge(t1, t2, t3)
#         return merged if merged else captures[0]
#     except Exception as e:
#         _log.warning("DBMerge failed (%s) — using first capture", e)
#         return captures[0]

# def _push_zoho_bg(zoho_worker_id, template_b64, worker_name):
#     def _run():
#         if not (_zoho_request and _auth_headers and _API_DOMAIN): return
#         hdrs = _auth_headers()
#         if not hdrs: return
#         url = f"{_API_DOMAIN}/{_APP_OWNER}/{_APP_NAME}/report/{_WORKERS_REPORT}/{zoho_worker_id}"
#         r   = _zoho_request("PATCH", url, headers=hdrs,
#                              json={"data": {"Fingerprint_Template": template_b64}})
#         ok  = r and r.status_code == 200 and r.json().get("code") == 3000
#         _log.info("Zoho push %s: %s", worker_name, "✔" if ok else "failed")
#     threading.Thread(target=_run, daemon=True).start()

# def _create_db():
#     with _DB_LOCK:
#         c = _open_db()
#         c.executescript("""
#             CREATE TABLE IF NOT EXISTS fp_templates (
#                 zk_user_id      TEXT PRIMARY KEY,
#                 zoho_worker_id  TEXT NOT NULL,
#                 worker_name     TEXT NOT NULL,
#                 template_b64    TEXT NOT NULL,
#                 enrolled_at     TEXT NOT NULL,
#                 updated_at      TEXT NOT NULL
#             );
#             CREATE INDEX IF NOT EXISTS idx_zoho ON fp_templates(zoho_worker_id);
#         """)
#         c.commit(); c.close()

# def _open_db():
#     return sqlite3.connect(DB_PATH, check_same_thread=False)