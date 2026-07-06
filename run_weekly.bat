@echo off
cd /d C:\Users\svats\trading_project
chcp 65001 > nul
python scripts\live\run_weekly_job.py >> logs\weekly_job.log 2>&1