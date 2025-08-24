@echo off
setlocal
cd /d %~dp0
set SMTP_HOST=smtp.gmail.com
set SMTP_PORT=587
set SMTP_USER=youraddress@gmail.com
set SMTP_PASS=your_app_password
set SMTP_FROM=youraddress@gmail.com
python maintenance_bot.py email --to youraddress@gmail.com
endlocal
