@echo off
cd /d C:\Users\svats\trading_project
powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Run kite_auth.py before market open!', 'Kite Auth Reminder', 'OK', 'Information')"