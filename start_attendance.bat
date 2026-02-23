@echo off
:: 1. Navigate to the correct project folder
cd /d "C:\Users\Admin\finlanza-tasks\Zoho"

:: 2. Wait 30 seconds for Wi-Fi and Drivers
timeout /t 30 /nobreak

:retry
:: 3. Run the GUI app using the virtual environment
"venv\Scripts\python.exe" fingerprint_gui_full.py

:: 4. If it closes, wait 5 seconds and restart
timeout /t 5
goto retry