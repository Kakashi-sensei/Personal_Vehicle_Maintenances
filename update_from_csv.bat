@echo off
REM Update JSON/YAML from cardata.csv and (optionally) commit/push.
REM Run this .bat from your repo folder: C:\Users\drtia\OneDrive\Documents\GitHub\Personal_Vehicle_Maintenances

setlocal
cd /d %~dp0

REM Install dependencies if missing (safe to run repeatedly)
python -m pip install --upgrade pip >NUL 2>&1
python -m pip install pandas pyyaml >NUL 2>&1

REM Dry run preview (uncomment to preview first)
REM python parse_cardata.py --dry-run

REM Generate outputs
python parse_cardata.py

REM OPTIONAL: auto-commit and push (uncomment next two lines if you want it automatic)
REM python parse_cardata.py --commit -m "Update maintenance data from CSV"
REM python parse_cardata.py --commit --push -m "Update maintenance data from CSV (auto-push)"
endlocal
