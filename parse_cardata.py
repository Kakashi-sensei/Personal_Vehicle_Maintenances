#!/usr/bin/env python3
"""
parse_cardata.py
Regenerate maintenance_data.json and maintenance_config.yaml from cardata.csv (in the same folder).

Your date rule:
- Last 4 digits = YEAR
- If 8 digits total: MM DD YYYY
- If 7 digits total: M DD YYYY

Usage (from repo root):
  python parse_cardata.py
  python parse_cardata.py --dry-run
  python parse_cardata.py --datecol "Date" --milescol "Miles" --taskcol "Service" --notescol "Notes"
  python parse_cardata.py --commit -m "Update maintenance data from CSV"
  python parse_cardata.py --commit --push -m "Update from CSV (auto-push)"

Requires: pandas, pyyaml
"""
import argparse, re, json, subprocess, shutil
from pathlib import Path
from datetime import date
import pandas as pd

try:
    import yaml
except ImportError:
    raise SystemExit("Please install pyyaml: pip install pyyaml")

REPO = Path(__file__).resolve().parent
CSV_PATH = REPO / "cardata.csv"
DATA_JSON = REPO / "maintenance_data.json"
CFG_YAML  = REPO / "maintenance_config.yaml"

def parse_m_d_y_token(val: object) -> str | None:
    """Parse date strings per rule into YYYY-MM-DD or return None."""
    if val is None:
        return None
    s = str(val).strip()
    s = re.sub(r'\D', '', s)  # keep digits only
    if len(s) == 8:
        m = int(s[:2]); d = int(s[2:4]); y = int(s[4:8])
    elif len(s) == 7:
        m = int(s[:1]); d = int(s[1:3]); y = int(s[3:7])
    else:
        return None
    if not (1 <= m <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100):
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"

def guess_cols(df, excl=None):
    cols = {c: c.lower().strip() for c in df.columns}
    if excl and excl in cols:
        cols.pop(excl, None)
    def pick(patterns):
        for c, lc in cols.items():
            for p in patterns:
                if re.search(p, lc):
                    return c
        return None
    miles_col = pick([r'\b(odo|odometer|mileage|miles|mi)\b'])
    task_col  = pick([r'\b(service|task|work|description|item|maintenance|operation)\b'])
    notes_col = pick([r'\b(note|comment|remark|details|vendor|shop)\b'])
    return miles_col, task_col, notes_col

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datecol", type=str, help="CSV column name for date (7/8-digit tokens).")
    ap.add_argument("--milescol", type=str, help="CSV column name for odometer miles.")
    ap.add_argument("--taskcol", type=str, help="CSV column name for service description.")
    ap.add_argument("--notescol", type=str, help="CSV column name for notes/comments/vendor.")
    ap.add_argument("--dry-run", action="store_true", help="Parse and print summary without writing files.")
    ap.add_argument("--commit", action="store_true", help="Git add/commit updated files.")
    ap.add_argument("--push", action="store_true", help="With --commit, also git push.")
    ap.add_argument("-m", "--message", type=str, default="Update maintenance data from CSV", help="Commit message.")
    args = ap.parse_args()

    if not CSV_PATH.exists():
        raise SystemExit(f"CSV not found: {CSV_PATH}")

    df = pd.read_csv(CSV_PATH, engine="python")
    # detect date column if not specified
    date_col = args.datecol
    if not date_col:
        best, score = None, -1
        for c in df.columns:
            sample = df[c].head(100)
            hits = sum(parse_m_d_y_token(v) is not None for v in sample)
            if hits > score:
                best, score = c, hits
        date_col = best

    parsed_dates = df[date_col].apply(parse_m_d_y_token) if date_col in df.columns else pd.Series([None]*len(df))

    miles_col, task_col, notes_col = args.milescol, args.taskcol, args.notescol
    if not (miles_col and task_col and notes_col):
        g_m, g_t, g_n = guess_cols(df, excl=date_col)
        miles_col = miles_col or g_m
        task_col  = task_col  or g_t
        notes_col = notes_col or g_n

    # Build normalized rows
    miles_series = (pd.to_numeric(df[miles_col].astype(str).str.replace(r'[^0-9.]', '', regex=True), errors="coerce")
                    if miles_col else pd.Series([pd.NA]*len(df)))
    tasks = df[task_col].astype(str) if task_col else pd.Series([""]*len(df))
    notes = df[notes_col].astype(str) if notes_col else pd.Series([""]*len(df))

    services = []
    for i in range(len(df)):
        d = parsed_dates.iloc[i] if len(parsed_dates) == len(df) else None
        m = miles_series.iloc[i]
        t = " ".join(str(tasks.iloc[i]).split())
        n = str(notes.iloc[i]).strip()
        if t or pd.notna(m) or d:
            services.append({"task": t, "miles": (int(m) if pd.notna(m) else None), "date": d, "notes": n})

    df_srv = pd.DataFrame(services).drop_duplicates().sort_values(["task","date","miles"], na_position="last")
    df_odo = df_srv.dropna(subset=["date","miles"])[["date","miles"]].drop_duplicates().sort_values(["date","miles"])

    # Build config
    default_map = {"engine oil": (5000,6),"engine oil & filter": (5000,6),"oil change": (5000,6),"tire rotation": (5000,6),
                   "cabin air filter": (15000,12),"engine air filter": (30000,24),"brake inspection": (5000,6),
                   "brake fluid": (30000,36),"coolant": (100000,120),"transmission fluid": (60000,72),"spark plug": (120000,120)}
    def task_interval_guess(t):
        tl=t.lower()
        for k,v in default_map.items():
            if k in tl: return v
        return (None,12)

    tasks_cfg=[]
    for t in sorted([t for t in df_srv["task"].dropna().unique() if t]):
        last = df_srv[df_srv["task"]==t].dropna(subset=["date"]).sort_values(["date","miles"]).tail(1)
        last_date = (str(last["date"].iloc[0]) if not last.empty else date.today().strftime("%Y-%m-%d"))
        last_miles = (int(last["miles"].iloc[0]) if (not last.empty and pd.notna(last["miles"].iloc[0])) else 0)
        imiles, imonths = task_interval_guess(t)
        tasks_cfg.append({"name":t,"interval_miles":(int(imiles) if imiles is not None else None),
                          "interval_months":(int(imonths) if imonths is not None else None),
                          "initial_miles":last_miles,"initial_date":last_date})

    # Summary
    print("Detected columns:")
    print(f"  date:  {date_col}")
    print(f"  miles: {miles_col}")
    print(f"  task:  {task_col}")
    print(f"  notes: {notes_col}")
    print(f"Parsed rows: {len(df_srv)}  | Odometer points: {len(df_odo)}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    # Back up existing outputs if present
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if DATA_JSON.exists():
        shutil.copy(DATA_JSON, DATA_JSON.with_name(f"{DATA_JSON.stem}.bak_{ts}.json"))
    if CFG_YAML.exists():
        shutil.copy(CFG_YAML, CFG_YAML.with_name(f"{CFG_YAML.stem}.bak_{ts}.yaml"))

    # Write outputs
    DATA_JSON.write_text(json.dumps({"odometer": df_odo.to_dict(orient="records"),
                                     "services": df_srv.to_dict(orient="records")}, indent=2), encoding="utf-8")
    CFG_YAML.write_text(yaml.safe_dump({"vehicle":{"year":2018,"make":"Toyota","model":"Camry","vin":""},
                                         "thresholds":{"miles":500,"days":30},
                                         "tasks":tasks_cfg}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"Wrote: {DATA_JSON.name}, {CFG_YAML.name}")

    if args.commit:
        try:
            subprocess.run(["git","add",str(DATA_JSON.name), str(CFG_YAML.name)],
                           cwd=REPO, check=True)
            subprocess.run(["git","commit","-m",args.message], cwd=REPO, check=True)
            print("Git commit created.")
            if args.push:
                subprocess.run(["git","push"], cwd=REPO, check=True)
                print("Git push complete.")
        except Exception as e:
            print(f"Git step skipped/failed: {e}")

if __name__ == "__main__":
    main()
