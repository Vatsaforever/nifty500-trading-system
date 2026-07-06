@echo off
cd /d C:\Users\svats\trading_project
chcp 65001 > nul
python scripts\live\forward_test.py >> logs\forward_test.log 2>&1