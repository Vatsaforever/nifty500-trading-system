@echo off
cd /d C:\Users\svats\trading_project
chcp 65001 > nul

echo Starting market hours automation... >> logs\master.log
echo %date% %time% >> logs\master.log

:loop
:: Check if within market hours (approximate - runs all day, 
:: scripts internally check market hours)
python scripts\live\run_hourly_job.py >> logs\hourly_job.log 2>&1
python scripts\live\run_orb_scan.py >> logs\orb_scan.log 2>&1
python scripts\live\forward_test.py >> logs\forward_test.log 2>&1

echo %date% %time% - Scan complete >> logs\master.log

:: Wait 60 minutes (3600 seconds)
timeout /t 3600 /nobreak > nul
goto loop