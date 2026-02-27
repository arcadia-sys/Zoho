"""
fp_store.py  —  Fingerprint Storage + ID Verification
======================================================
Ensures the typed Worker ID matches the finger on the scanner.
Nobody can check in/out for someone else.

QUICK INTEGRATION
-----------------
1. Drop this file next to your main script.

2. After  zk.Init()  add:
       import fp_store
       fp_store.init(zk, zoho_request, auth_headers,
                     API_DOMAIN, APP_OWNER, APP_NAME, WORKERS_REPORT)

3. In  FingerprintGUI._process()  REPLACE the entire block
   from  "zk.OpenDevice(0)"  down to  "zk.CloseDevice()"  with:

       ok, msg, name = fp_store.verify_id_matches_finger(uid)
       if not ok:
           self.log(msg, "err")
           self._gui(lambda: self._scan_err("BLOCKED"))
           self._gui(lambda: self._show_flash("✗", "Access Denied", msg, "", RED_DIM))
           return
       # identity confirmed — name is the worker's full name
       full_name = name

4. In  AdminPanel._build()  add the enrolment tab:
       fp_store.build_enroll_tab(nb, self, find_worker)
       # where nb is your ttk.Notebook and find_worker is your existing function
"""

import os, time, sqlite3, base64, threading, logging, tkinter as tk
from tkinter import ttk
from datetime import datetime
from typing import Optional

_log = logging.getLogger("fp_store")

# ── globals filled by init() ──────────────────────────────────────────────────
_zk             = None
_zoho_request   = None
_auth_headers   = None
_API_DOMAIN     = ""
_APP_OWNER      = ""
_APP_NAME       = ""
_WORKERS_REPORT = "All_Workers"

DB_PATH         = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fp_templates.db")
_DB_LOCK        = threading.Lock()
MATCH_THRESHOLD = 50          # ZKTeco 0-100 score; >= means same finger

# colour palette mirrors your main script
BG="#07090f"; CARD="#0c1018"; CARD2="#10151f"; BORDER="#1c2438"; BORDER2="#243048"
ACCENT="#3b82f6"; ACCENT_DIM="#172554"; ACCENT2="#60a5fa"
GREEN="#10b981"; GREEN2="#34d399"; GREEN_DIM="#052e1c"
RED="#f43f5e";   RED2="#fb7185";   RED_DIM="#4c0519"
ORANGE="#f59e0b"; ORANGE2="#fbbf24"; ORANGE_DIM="#3d1f00"
TEAL="#2dd4bf";  TEAL_DIM="#042f2e"
TEXT="#e2e8f0";  TEXT2="#94a3b8"; MUTED="#3d4f69"; WHITE="#ffffff"


# =============================================================================
# PUBLIC API
# =============================================================================

def init(zk_instance, zoho_request_fn, auth_headers_fn,
         api_domain, app_owner, app_name, workers_report="All_Workers"):
    """Call once immediately after zk.Init()."""
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
    _log.info("fp_store ready — DB: %s  enrolled: %d", DB_PATH, count_enrolled())


# ── CORE: typed ID must match scanned finger ──────────────────────────────────

def verify_id_matches_finger(zk_user_id: str,
                              timeout_seconds: int = 20) -> tuple:
    """
    THE MAIN GATE.  Call this in _process() instead of the raw scanner block.

    Flow:
      1. Look up the stored template for the typed ID.
         → If not enrolled: BLOCK immediately (no scan needed).
      2. Open scanner and wait for the worker to place their finger.
      3. Run ZKTeco DBMatch(live_scan, stored_template).
      4. If score >= MATCH_THRESHOLD: ALLOW.
         If score <  MATCH_THRESHOLD: BLOCK — wrong person.

    Returns
    -------
    (True,  "",          worker_name)   — identity confirmed, proceed
    (False, error_msg,   "")            — blocked, show error_msg to worker
    """
    uid = str(zk_user_id).strip()

    # ── Step 1: must be enrolled ──────────────────────────────────────────────
    stored_b64, worker_name = _get_template_and_name(uid)
    if not stored_b64:
        msg = (f"Worker ID {uid} has no fingerprint on file.\n"
               f"Please ask a supervisor to enrol your fingerprint first.")
        _log.warning("verify: ID %s not enrolled", uid)
        return False, msg, ""

    # ── Step 2: scanner must be present ──────────────────────────────────────
    if _zk is None:
        return False, "Fingerprint system not initialised — contact IT.", ""
    if _zk.GetDeviceCount() == 0:
        return False, "Scanner not connected — contact IT support.", ""

    _zk.OpenDevice(0)
    try:
        # ── Step 3: capture live scan ─────────────────────────────────────────
        capture = None
        for _ in range(timeout_seconds * 5):
            capture = _zk.AcquireFingerprint()
            if capture:
                break
            time.sleep(0.2)

        if not capture:
            return False, "Scan timed out — please try again.", ""

        # ── Step 4: compare against stored template ───────────────────────────
        stored  = base64.b64decode(stored_b64)
        score   = _zk.DBMatch(capture, stored)
        matched = score >= MATCH_THRESHOLD

        _log.info("verify ID=%s name=%s score=%d matched=%s",
                  uid, worker_name, score, matched)

        if matched:
            return True, "", worker_name
        else:
            msg = (f"Fingerprint does not match ID {uid}.\n"
                   f"Only {worker_name} may check in or out on this ID.\n"
                   f"(Confidence: {score} — needs {MATCH_THRESHOLD})")
            return False, msg, ""

    except Exception as exc:
        _log.exception("verify_id_matches_finger error: %s", exc)
        return False, f"Scanner error: {exc}", ""
    finally:
        try:
            _zk.CloseDevice()
        except Exception:
            pass


# ── ENROLMENT ─────────────────────────────────────────────────────────────────

def enroll_worker(zk_user_id: str, zoho_worker_id: str, worker_name: str,
                  samples: int = 3, progress_cb=None) -> tuple:
    """
    Capture `samples` scans, merge them, store locally and push to Zoho.
    Returns (True, "success") or (False, "error message").
    """
    def _p(msg, tag="info"):
        _log.info("enroll [%s]: %s", worker_name, msg)
        if progress_cb:
            try: progress_cb(msg, tag)
            except TypeError:
                try: progress_cb(msg)
                except Exception: pass

    if _zk is None:
        return False, "fp_store not initialised."
    if _zk.GetDeviceCount() == 0:
        return False, "Scanner not connected."

    _zk.OpenDevice(0)
    try:
        _p(f"Enrolling {worker_name} — {samples} scans needed", "info")
        captures = []

        for i in range(1, samples + 1):
            _p(f"Scan {i}/{samples}: place finger on scanner…", "info")
            capture = None
            for _ in range(150):
                capture = _zk.AcquireFingerprint()
                if capture: break
                time.sleep(0.2)
            if not capture:
                return False, f"Scan {i} timed out — please try again."
            _p(f"Scan {i} captured ✔ — lift finger", "ok")
            captures.append(capture)
            time.sleep(0.8)

        _p("Merging scans…", "info")
        merged = _merge(captures)
        if not merged:
            return False, "Merge failed — please try again."

        template_b64 = base64.b64encode(merged).decode()
        _save_to_db(zk_user_id, zoho_worker_id, worker_name, template_b64)
        _p(f"Saved locally ✔", "ok")
        _push_to_zoho_bg(zoho_worker_id, template_b64, worker_name)
        _p(f"Enrolment complete for {worker_name} ✔", "ok")
        return True, f"{worker_name} enrolled successfully."

    except Exception as exc:
        _log.exception("enroll_worker: %s", exc)
        return False, f"Enrolment error: {exc}"
    finally:
        try: _zk.CloseDevice()
        except Exception: pass


def load_from_records(records: list) -> tuple:
    """
    Bulk-import templates from existing worker dicts.
    Handles both 'template_b64' (base-64) and 'template' (hex) field formats.
    Returns (imported, skipped).
    """
    imported = skipped = 0
    for rec in records:
        tmpl = _extract_template(rec)
        if not tmpl:
            skipped += 1
            continue
        zk_id = str(
            rec.get("Worker_ID") or rec.get("ZKTeco_User_ID2") or
            rec.get("fid") or rec.get("zoho_id") or rec.get("ID") or ""
        ).strip().split(".")[0]
        if not zk_id or zk_id in ("0", "None", ""):
            skipped += 1
            continue
        zoho_id = str(rec.get("ID") or rec.get("zoho_id") or zk_id)
        name    = rec.get("Full_Name") or rec.get("worker_name") or f"Worker {zk_id}"
        _save_to_db(zk_id, zoho_id, name, tmpl)
        imported += 1
    _log.info("load_from_records: %d imported, %d skipped", imported, skipped)
    return imported, skipped


# ── DATABASE QUERIES ──────────────────────────────────────────────────────────

def is_enrolled(zk_user_id: str) -> bool:
    return _get_template_and_name(str(zk_user_id))[0] is not None

def count_enrolled() -> int:
    with _DB_LOCK:
        conn = _open_db()
        try:    return conn.execute("SELECT COUNT(*) FROM fp_templates").fetchone()[0]
        finally: conn.close()

def list_enrolled() -> list:
    with _DB_LOCK:
        conn = _open_db()
        try:
            rows = conn.execute(
                "SELECT zk_user_id, zoho_worker_id, worker_name, enrolled_at, updated_at "
                "FROM fp_templates ORDER BY worker_name"
            ).fetchall()
            return [{"zk_user_id": r[0], "zoho_worker_id": r[1], "worker_name": r[2],
                     "enrolled_at": r[3], "updated_at": r[4]} for r in rows]
        finally: conn.close()

def delete_template(zk_user_id: str) -> bool:
    with _DB_LOCK:
        conn = _open_db()
        try:
            conn.execute("DELETE FROM fp_templates WHERE zk_user_id=?", (str(zk_user_id),))
            conn.commit()
            _log.info("Deleted template for ZK ID %s", zk_user_id)
            return True
        except Exception as e:
            _log.error("delete_template: %s", e); return False
        finally: conn.close()


# =============================================================================
# ADMIN PANEL TAB
# =============================================================================

def build_enroll_tab(notebook: ttk.Notebook, parent_win: tk.Toplevel,
                     find_worker_fn=None):
    """
    Call inside AdminPanel._build() to add a Fingerprints tab.

        fp_store.build_enroll_tab(nb, self, find_worker)

    find_worker_fn is your existing  find_worker(uid)  function.
    """
    tab = tk.Frame(notebook, bg=BG)
    notebook.add(tab, text="👆  FINGERPRINTS")
    _EnrollTab(tab, parent_win, find_worker_fn)
    return tab


class _EnrollTab:
    def __init__(self, parent, win, find_worker_fn):
        self._win         = win
        self._find_worker = find_worker_fn
        self._busy        = False
        self._build(parent)
        self._refresh_list()

    def _build(self, parent):
        # ── header ────────────────────────────────────────────────────────────
        tk.Frame(parent, bg=TEAL, height=3).pack(fill=tk.X)
        hdr = tk.Frame(parent, bg=CARD, padx=20, pady=12); hdr.pack(fill=tk.X)
        lf  = tk.Frame(hdr, bg=CARD); lf.pack(side=tk.LEFT)
        tk.Label(lf, text="FINGERPRINT ENROLMENT",
                 font=("Courier", 12, "bold"), bg=CARD, fg=TEAL).pack(anchor="w")
        tk.Label(lf, text="Workers must be enrolled here before they can clock in or out.",
                 font=("Courier", 8), bg=CARD, fg=TEXT2).pack(anchor="w", pady=(2,0))
        self._count_lbl = tk.Label(hdr, text="", font=("Courier", 9, "bold"),
                                   bg=CARD, fg=TEAL)
        self._count_lbl.pack(side=tk.RIGHT)
        tk.Frame(parent, bg=BORDER2, height=1).pack(fill=tk.X)

        # ── two-column body ───────────────────────────────────────────────────
        body = tk.Frame(parent, bg=BG, padx=20, pady=16)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=2)

        # LEFT — enrol form
        left = tk.Frame(body, bg=CARD, highlightbackground=BORDER2,
                        highlightthickness=1, padx=16, pady=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,12))

        tk.Label(left, text="ENROL WORKER",
                 font=("Courier", 9, "bold"), bg=CARD, fg=TEAL).pack(anchor="w", pady=(0,10))

        tk.Label(left, text="WORKER ID",
                 font=("Courier", 7, "bold"), bg=CARD, fg=MUTED).pack(anchor="w")
        id_frame = tk.Frame(left, bg=TEAL, padx=1, pady=1); id_frame.pack(fill=tk.X, pady=(4,10))
        id_inner = tk.Frame(id_frame, bg=CARD2); id_inner.pack(fill=tk.X)
        self._id_var = tk.StringVar()
        self._id_var.trace_add("write", lambda *_: self._on_id_change())
        self._id_entry = tk.Entry(id_inner, textvariable=self._id_var,
                                  font=("Courier", 22, "bold"),
                                  bg=CARD2, fg=WHITE, insertbackground=TEAL, bd=0)
        self._id_entry.pack(padx=10, pady=8, fill=tk.X)
        self._id_entry.focus_set()

        self._name_lbl = tk.Label(left, text="Enter an ID above",
                                  font=("Courier", 10), bg=CARD, fg=MUTED)
        self._name_lbl.pack(anchor="w", pady=(0,6))

        self._status_lbl = tk.Label(left, text="", font=("Courier", 8, "bold"),
                                    bg=CARD, fg=MUTED)
        self._status_lbl.pack(anchor="w", pady=(0,12))

        # scans selector
        tk.Label(left, text="NUMBER OF SCANS",
                 font=("Courier", 7, "bold"), bg=CARD, fg=MUTED).pack(anchor="w")
        scan_row = tk.Frame(left, bg=CARD); scan_row.pack(anchor="w", pady=(4,14))
        self._samples = tk.IntVar(value=3)
        for n in (2, 3, 4):
            tk.Radiobutton(scan_row, text=str(n), variable=self._samples, value=n,
                           font=("Courier", 10, "bold"), bg=CARD, fg=TEAL,
                           selectcolor=CARD2, activebackground=CARD
                           ).pack(side=tk.LEFT, padx=(0,12))

        # buttons
        self._btn_enrol = tk.Button(
            left, text="👆 ENROL (new)",
            font=("Courier", 10, "bold"), relief=tk.FLAT,
            bg=TEAL_DIM, fg=TEAL, activebackground=TEAL, activeforeground=BG,
            cursor="hand2", pady=10, state=tk.DISABLED, command=self._do_enrol)
        self._btn_enrol.pack(fill=tk.X, pady=(0,6))

        self._btn_reenrol = tk.Button(
            left, text="🔄 RE-ENROL (replace)",
            font=("Courier", 9, "bold"), relief=tk.FLAT,
            bg=ORANGE_DIM, fg=ORANGE2, activebackground=ORANGE, activeforeground=BG,
            cursor="hand2", pady=8, state=tk.DISABLED, command=self._do_reenrol)
        self._btn_reenrol.pack(fill=tk.X, pady=(0,6))

        self._btn_delete = tk.Button(
            left, text="🗑 DELETE TEMPLATE",
            font=("Courier", 9, "bold"), relief=tk.FLAT,
            bg=RED_DIM, fg=RED2, activebackground=RED, activeforeground=WHITE,
            cursor="hand2", pady=8, state=tk.DISABLED, command=self._do_delete)
        self._btn_delete.pack(fill=tk.X)

        tk.Frame(left, bg=BORDER, height=1).pack(fill=tk.X, pady=12)

        tk.Label(left, text="PROGRESS",
                 font=("Courier", 7, "bold"), bg=CARD, fg=MUTED).pack(anchor="w")
        self._log = tk.Text(left, font=("Courier", 8), bg=CARD2, fg=TEXT2,
                            height=8, relief=tk.FLAT, padx=8, pady=6, state=tk.DISABLED)
        self._log.pack(fill=tk.X, pady=(4,0))
        for tag, col in [("ok",GREEN2),("err",RED2),("warn",ORANGE2),("info",ACCENT2)]:
            self._log.tag_config(tag, foreground=col)

        # RIGHT — enrolled list
        right = tk.Frame(body, bg=BG); right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1); right.columnconfigure(0, weight=1)

        list_hdr = tk.Frame(right, bg=BG); list_hdr.grid(row=0, column=0, sticky="ew", pady=(0,8))
        tk.Label(list_hdr, text="ENROLLED WORKERS",
                 font=("Courier", 9, "bold"), bg=BG, fg=MUTED).pack(side=tk.LEFT)
        tk.Button(list_hdr, text="↻ REFRESH", font=("Courier", 8, "bold"),
                  relief=tk.FLAT, bg=BORDER, fg=TEXT2, cursor="hand2",
                  padx=8, pady=4, command=self._refresh_list
                  ).pack(side=tk.RIGHT)

        style = ttk.Style()
        style.configure("FP.Treeview", background=CARD2, foreground=TEXT,
                        fieldbackground=CARD2, rowheight=30,
                        font=("Courier", 9), borderwidth=0)
        style.configure("FP.Treeview.Heading", background=CARD,
                        foreground=TEAL, font=("Courier", 8, "bold"), relief="flat")
        style.map("FP.Treeview",
                  background=[("selected", TEAL_DIM)],
                  foreground=[("selected", TEAL)])

        self._tree = ttk.Treeview(right, columns=("ID","Name","Enrolled","Updated"),
                                  show="headings", style="FP.Treeview", selectmode="browse")
        for col, w, anc in [("ID",70,"center"),("Name",220,"w"),
                             ("Enrolled",140,"center"),("Updated",140,"center")]:
            self._tree.heading(col, text=col.upper())
            self._tree.column(col, width=w, anchor=anc,
                              stretch=(col == "Name"))
        self._tree.grid(row=1, column=0, sticky="nsew")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        vsb = ttk.Scrollbar(right, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=1, column=1, sticky="ns")

    # ── events ────────────────────────────────────────────────────────────────

    def _on_id_change(self):
        uid = self._id_var.get().strip()
        if not uid:
            self._name_lbl.config(text="Enter an ID above", fg=MUTED)
            self._status_lbl.config(text="")
            self._sync_buttons(uid=None); return

        enrolled = is_enrolled(uid)
        self._status_lbl.config(
            text="● ENROLLED — template on file" if enrolled else "○ NOT YET ENROLLED",
            fg=GREEN2 if enrolled else ORANGE2)
        self._sync_buttons(uid=uid)

        if self._find_worker:
            threading.Thread(target=self._lookup, args=(uid,), daemon=True).start()

    def _lookup(self, uid):
        try:    w = self._find_worker(uid)
        except: w = None
        def _upd():
            if self._id_var.get().strip() != uid: return
            if w:
                self._name_lbl.config(text=w.get("Full_Name", uid), fg=WHITE)
            else:
                self._name_lbl.config(text=f"ID {uid} not found in Zoho", fg=RED2)
        try: self._win.after(0, _upd)
        except Exception: pass

    def _on_select(self, _=None):
        sel = self._tree.selection()
        if sel:
            self._id_var.set(self._tree.item(sel[0], "values")[0])

    def _sync_buttons(self, uid):
        if uid and not self._busy:
            enrolled = is_enrolled(uid)
            self._btn_enrol.config(
                state=tk.NORMAL if not enrolled else tk.DISABLED,
                bg=TEAL_DIM if not enrolled else BORDER,
                fg=TEAL     if not enrolled else MUTED)
            self._btn_reenrol.config(
                state=tk.NORMAL if enrolled else tk.DISABLED,
                bg=ORANGE_DIM if enrolled else BORDER,
                fg=ORANGE2    if enrolled else MUTED)
            self._btn_delete.config(
                state=tk.NORMAL if enrolled else tk.DISABLED,
                bg=RED_DIM if enrolled else BORDER,
                fg=RED2    if enrolled else MUTED)
        else:
            for b in (self._btn_enrol, self._btn_reenrol, self._btn_delete):
                b.config(state=tk.DISABLED, bg=BORDER, fg=MUTED)

    # ── actions ───────────────────────────────────────────────────────────────

    def _resolve(self):
        """Return (uid, zoho_id, name) from current entry."""
        uid = self._id_var.get().strip()
        if not uid:
            self._plog("Enter a Worker ID first.", "warn"); return None, None, None
        name = self._name_lbl.cget("text")
        zoho_id = uid
        if self._find_worker:
            try:
                w = self._find_worker(uid)
                if w:
                    name    = w.get("Full_Name", uid)
                    zoho_id = w.get("ID", uid)
            except Exception: pass
        return uid, zoho_id, name

    def _do_enrol(self):
        uid, zoho_id, name = self._resolve()
        if not uid: return
        if is_enrolled(uid):
            self._plog(f"{name} already enrolled — use Re-Enrol.", "warn"); return
        self._run(uid, zoho_id, name)

    def _do_reenrol(self):
        uid, zoho_id, name = self._resolve()
        if not uid: return
        delete_template(uid)
        self._plog(f"Old template removed for {name}.", "warn")
        self._run(uid, zoho_id, name)

    def _do_delete(self):
        uid, _, name = self._resolve()
        if not uid: return
        delete_template(uid)
        self._plog(f"Template deleted for {name} (ID {uid}).", "warn")
        self._status_lbl.config(text="○ NOT YET ENROLLED", fg=ORANGE2)
        self._sync_buttons(uid=uid)
        self._refresh_list()

    def _run(self, uid, zoho_id, name):
        self._busy = True
        self._sync_buttons(uid=None)
        self._plog(f"Starting enrolment for {name}…", "info")

        def _thread():
            ok, msg = enroll_worker(
                zk_user_id=uid, zoho_worker_id=zoho_id,
                worker_name=name, samples=self._samples.get(),
                progress_cb=lambda m, t="info": self._schedule(
                    lambda: self._plog(m, t)))
            def _done():
                self._plog(msg, "ok" if ok else "err")
                self._busy = False
                self._sync_buttons(uid=uid)
                self._refresh_list()
                self._status_lbl.config(
                    text="● ENROLLED — template on file" if ok else "✗ Enrolment failed",
                    fg=GREEN2 if ok else RED2)
            self._schedule(_done)

        threading.Thread(target=_thread, daemon=True).start()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _refresh_list(self):
        self._tree.delete(*self._tree.get_children())
        for w in list_enrolled():
            self._tree.insert("", tk.END, values=(
                w["zk_user_id"], w["worker_name"],
                w["enrolled_at"][:16], w["updated_at"][:16]))
        n = count_enrolled()
        self._count_lbl.config(text=f"{n} worker{'s' if n!=1 else ''} enrolled")

    def _plog(self, msg, tag="info"):
        self._log.config(state=tk.NORMAL)
        self._log.insert(tk.END,
                         f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n", tag)
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)

    def _schedule(self, fn):
        try: self._win.after(0, fn)
        except Exception: pass


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _get_template_and_name(zk_user_id: str):
    with _DB_LOCK:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT template_b64, worker_name FROM fp_templates WHERE zk_user_id=?",
                (str(zk_user_id),)).fetchone()
            return (row[0], row[1]) if row else (None, "")
        finally: conn.close()

def _extract_template(rec: dict) -> Optional[str]:
    # base-64 field
    b64 = rec.get("template_b64", "")
    if b64 and len(b64) > 20:
        try:
            if len(base64.b64decode(b64)) > 10: return b64
        except Exception: pass
    # hex field
    h = rec.get("template", "")
    if h and len(h) > 20:
        try:
            raw = bytes.fromhex(h)
            if len(raw) > 10: return base64.b64encode(raw).decode()
        except Exception: pass
    return None

def _save_to_db(zk_user_id, zoho_worker_id, worker_name, template_b64):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _DB_LOCK:
        conn = _open_db()
        try:
            conn.execute("""
                INSERT INTO fp_templates
                    (zk_user_id,zoho_worker_id,worker_name,template_b64,enrolled_at,updated_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(zk_user_id) DO UPDATE SET
                    zoho_worker_id=excluded.zoho_worker_id,
                    worker_name=excluded.worker_name,
                    template_b64=excluded.template_b64,
                    updated_at=excluded.updated_at
            """, (str(zk_user_id), str(zoho_worker_id),
                  str(worker_name), template_b64, now, now))
            conn.commit()
            _log.info("Stored template: %s (ZK %s)", worker_name, zk_user_id)
            return True
        except Exception as e:
            _log.error("_save_to_db: %s", e); return False
        finally: conn.close()

def _merge(captures):
    if not captures: return None
    if len(captures) == 1: return captures[0]
    try:
        t1, t2 = captures[0], captures[1]
        t3 = captures[2] if len(captures) >= 3 else captures[1]
        merged = _zk.DBMerge(t1, t2, t3)
        return merged if merged else captures[0]
    except Exception as e:
        _log.warning("DBMerge failed (%s) — using first capture", e)
        return captures[0]

def _push_to_zoho_bg(zoho_worker_id, template_b64, worker_name):
    def _run():
        if not (_zoho_request and _auth_headers and _API_DOMAIN): return
        hdrs = _auth_headers()
        if not hdrs: return
        url = (f"{_API_DOMAIN}/{_APP_OWNER}/{_APP_NAME}"
               f"/report/{_WORKERS_REPORT}/{zoho_worker_id}")
        r = _zoho_request("PATCH", url, headers=hdrs,
                          json={"data": {"Fingerprint_Template": template_b64}})
        ok = r and r.status_code == 200 and r.json().get("code") == 3000
        _log.info("Zoho push %s: %s", worker_name, "✔" if ok else "failed")
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
            CREATE INDEX IF NOT EXISTS idx_zoho ON fp_templates(zoho_worker_id);
        """)
        conn.commit(); conn.close()

def _open_db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)