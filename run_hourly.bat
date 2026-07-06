@echo off
cd /d C:\Users\svats\trading_project
chcp 65001 > nul
python scripts\live\run_hourly_job.py >> logs\hourly_job.log 2>&1