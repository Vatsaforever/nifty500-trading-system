@echo off
cd /d C:\Users\svats\trading_project
python scripts\live\run_hourly_job.py >> logs\hourly_job.log 2>&1