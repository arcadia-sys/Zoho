# ============================================================
# EXACT CHANGES TO YOUR MAIN ATTENDANCE SCRIPT
# ============================================================
# Only 3 places need editing. Search for each comment below.
# ============================================================


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHANGE 1 — Add import + init (after your existing zk.Init())
# Find this block (~line 57):
#
#   zk = ZKFP2()
#   try:
#       zk.Init()
#   except Exception as e:
#       ...
#
# REPLACE WITH:
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import fp_store

zk = ZKFP2()
try:
    zk.Init()
    fp_store.init(
        zk_instance      = zk,
        zoho_request_fn  = zoho_request,
        auth_headers_fn  = auth_headers,
        api_domain       = API_DOMAIN,
        app_owner        = APP_OWNER,
        app_name         = APP_NAME,
        workers_report   = WORKERS_REPORT,
    )
except Exception as e:
    _log.error(f"Init Error: {e}")
    print(f"Init Error: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHANGE 2 — Replace the scanner block in _process()
#
# Find this section inside FingerprintGUI._process():
#
#   zk.OpenDevice(0); is_open = True
#   self.log("Waiting for fingerprint…", "info")
#   capture = None
#   for _ in range(150):
#       capture = zk.AcquireFingerprint()
#       if capture: break
#       time.sleep(0.2)
#
#   if not capture:
#       self.log("Scan timed out", "err")
#       self._gui(lambda: self._scan_err("TIMEOUT"))
#       self._gui(lambda: self._show_flash(...))
#       return
#
#   self._gui(self._scan_ok)
#   self.log("Fingerprint captured ✔", "ok")
#
#   _wcache_invalidate(uid)
#   worker = find_worker(uid, force_refresh=True)
#   if not worker:
#       ...return...
#
#   full_name = worker.get("Full_Name", uid)
#
# DELETE ALL OF THAT and REPLACE WITH these ~15 lines:
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

            # ── Fingerprint must match the typed ID ──────────────────────────
            self.log("Waiting for fingerprint scan…", "info")
            self._gui(self._scan_start)

            verified, fp_msg, full_name = fp_store.verify_id_matches_finger(uid)

            if not verified:
                self.log(fp_msg, "err")
                self._gui(lambda: self._scan_err("BLOCKED"))
                self._gui(lambda: self._show_flash(
                    "✗", "Access Denied", fp_msg, "", RED_DIM))
                return

            self._gui(self._scan_ok)
            self.log(f"Identity confirmed: {full_name} ✔", "ok")

            # still need the Zoho worker record for log_attendance
            _wcache_invalidate(uid)
            worker = find_worker(uid, force_refresh=True)
            if not worker:
                self.log(f"ID {uid} not found in Zoho — check log", "err")
                self._gui(lambda: self._scan_err("NOT FOUND"))
                self._gui(lambda: self._show_flash(
                    "✗", "Worker Not Found",
                    f"ID {uid} passed fingerprint but not in Zoho.\n"
                    "Check attendance.log for details.", "", RED_DIM))
                return

            # full_name already set from fingerprint match above
            # ─────────────────────────────────────────────────────────────────


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHANGE 3 — Add Fingerprints tab to AdminPanel
#
# Inside AdminPanel._build(), find where you create the notebook:
#
#   nb = ttk.Notebook(self, style="Admin.TNotebook")
#   nb.pack(...)
#   nb.add(self._tab_records, text="⚙  ALL RECORDS")
#   nb.add(self._tab_report,  text="📋  DAILY REPORT")
#
# ADD one line after the existing nb.add() calls:
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        fp_store.build_enroll_tab(nb, self, find_worker)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# OPTIONAL — Load existing templates from Zoho at startup
# Add inside FingerprintGUI.__init__() after _build_ui():
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        def _bg_sync():
            imported, skipped = fp_store.sync_from_zoho(
                progress_cb=lambda m: self.log(m, "info"))
            self._gui(lambda: self.log(
                f"Fingerprint sync: {imported} templates loaded from Zoho "
                f"({skipped} had no template)", "ok"))
        threading.Thread(target=_bg_sync, daemon=True).start()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WHAT CHANGES IN BEHAVIOUR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# BEFORE: worker types ID → scan captured → attendance logged
#         (anyone could type any ID)
#
# AFTER:  worker types ID → scan captured → compared to stored
#         template for THAT ID → only if they match does
#         attendance proceed. Wrong finger = BLOCKED.
#
# NOT ENROLLED:
#   Worker tries to check in but has no template → BLOCKED with
#   message "ask supervisor to enrol your fingerprint first".
#   Admin enrolls them in Admin Panel → Fingerprints tab.
#
# ENROLMENT FLOW (Admin Panel):
#   1. Admin opens Admin Panel → 👆 FINGERPRINTS tab
#   2. Types worker's ZK ID
#   3. Clicks "👆 ENROL"
#   4. Worker places finger 3 times (configurable)
#   5. Template saved to fp_templates.db + pushed to Zoho
#   6. Worker can now check in/out
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━