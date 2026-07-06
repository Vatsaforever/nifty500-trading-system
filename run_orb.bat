@echo off
cd /d C:\Users\svats\trading_project
chcp 65001 > nul
python scripts\live\run_orb_scan.py >> logs\orb_scan.log 2>&1