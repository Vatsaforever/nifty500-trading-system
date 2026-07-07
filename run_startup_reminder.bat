@echo off
timeout /t 30 /nobreak > nul
powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Run kite_auth.py before 9:15 AM then start run_market_hours.bat', 'Trading System Startup', 'OK', 'Information')"