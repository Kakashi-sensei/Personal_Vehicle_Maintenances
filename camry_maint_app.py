
import os
import sys
import csv
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import pandas as pd
import yaml

APP_TITLE = "Camry Maintenance Helper"
CSV_FILE = Path("cardata.csv")   # expects columns: date (MM/DD/YYYY), mileage (float), service (text)
RULES_FILE = Path("schedule_rules.yaml")

def ensure_csv():
    if not CSV_FILE.exists():
        pd.DataFrame(columns=["date","mileage","service"]).to_csv(CSV_FILE, index=False)

def parse_date_us(s):
    try:
        return datetime.strptime(str(s), "%m/%d/%Y").date()
    except Exception:
        return None

def normalize_services(df):
    df = df.copy()
    df["service_text"] = df["service"].astype(str)
    df["service_norm"] = df["service_text"].str.lower()
    return df

def load_rules():
    if not RULES_FILE.exists():
        raise FileNotFoundError(f"Rules file not found: {RULES_FILE.resolve()}")
    data = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    return data.get("rules", [])

def last_event_for_rule(df, rule):
    # find last row where any keyword appears in service_norm
    mask = pd.Series(False, index=df.index)
    for kw in rule.get("match", []):
        mask |= df["service_norm"].str.contains(kw, na=False)
    hits = df[mask].copy()
    if hits.empty:
        return None
    hits["parsed_date"] = hits["date"].apply(parse_date_us)
    hits = hits.sort_values(["parsed_date","mileage"], ascending=[True, True])
    return hits.iloc[-1].to_dict()

def compute_next_due(df, current_mileage, today, rules):
    results = []
    for rule in rules:
        key = rule.get("key")
        miles_int = int(rule.get("miles_interval", 0) or 0)
        months_int = int(rule.get("months_interval", 0) or 0)
        trigger = str(rule.get("trigger","earliest")).strip().lower()  # 'mileage_only' or 'earliest'
        last = last_event_for_rule(df, rule)

        due_mileage = None
        due_date = None
        basis = None

        if last is not None:
            last_mileage = float(last.get("mileage")) if pd.notnull(last.get("mileage")) else None
            last_date = parse_date_us(last.get("date"))
            # mileage
            if miles_int > 0 and last_mileage is not None:
                due_mileage = last_mileage + miles_int
            # time
            if months_int > 0 and last_date is not None:
                due_date = last_date + relativedelta(months=+months_int)

            if trigger == "mileage_only":
                basis = "mileage"
                # ignore due_date in calculations
                due_date = None
            else:  # earliest
                basis = "earliest"
        else:
            # never done: recommend baseline due
            if miles_int > 0:
                due_mileage = miles_int
            if months_int > 0 and trigger != "mileage_only":
                due_date = today  # time-based attention now
            basis = "first-time"

        miles_until = None if due_mileage is None else int(due_mileage - current_mileage)
        days_until = None if due_date is None else (due_date - today).days

        # Determine status: overdue if either threshold crossed (when applicable)
        overdue = False
        if miles_until is not None and miles_until <= 0:
            overdue = True
        if days_until is not None and days_until <= 0:
            overdue = True
        status = "OVERDUE" if overdue else "upcoming"

        # urgency metric for sorting (min of positive margins)
        urgency_metric = 999999
        if miles_until is not None:
            urgency_metric = min(urgency_metric, miles_until)
        if days_until is not None:
            urgency_metric = min(urgency_metric, days_until)

        results.append({
            "key": key,
            "note": rule.get("note",""),
            "trigger": trigger,
            "last_service": last["service_text"] if last else "(none recorded)",
            "last_date": last.get("date") if last else None,
            "last_mileage": last.get("mileage") if last else None,
            "miles_interval": miles_int,
            "months_interval": months_int,
            "due_mileage": None if due_mileage is None else int(due_mileage),
            "due_date": None if due_date is None else due_date.strftime("%Y-%m-%d"),
            "miles_until": miles_until,
            "days_until": days_until,
            "status": status,
            "urgency_metric": urgency_metric,
        })

    def urgency_key(x):
        overdue = 0 if x["status"]=="OVERDUE" else 1
        return (overdue, x["urgency_metric"] if x["urgency_metric"] is not None else 999999)
    results.sort(key=urgency_key)
    return results

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("880x600")
        self.resizable(True, True)

        # Top frame - current mileage and buttons
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Current Mileage:").pack(side="left")
        self.mileage_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.mileage_var, width=12).pack(side="left", padx=5)

        ttk.Button(top, text="Compute Reminders", command=self.compute_reminders).pack(side="left", padx=5)
        ttk.Button(top, text="Open CSV", command=self.open_csv).pack(side="left", padx=5)
        ttk.Button(top, text="Open Rules", command=self.open_rules).pack(side="left", padx=5)

        # Middle frame - add record
        mid = ttk.LabelFrame(self, text="Add Maintenance Record", padding=8)
        mid.pack(fill="x", padx=8, pady=8)

        self.date_var = tk.StringVar(value=date.today().strftime("%m/%d/%Y"))
        self.rec_miles_var = tk.StringVar()
        self.service_var = tk.StringVar()

        ttk.Label(mid, text="Date (MM/DD/YYYY):").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(mid, textvariable=self.date_var, width=14).grid(row=0, column=1, padx=4, pady=2)
        ttk.Label(mid, text="Mileage:").grid(row=0, column=2, sticky="w", padx=4, pady=2)
        ttk.Entry(mid, textvariable=self.rec_miles_var, width=10).grid(row=0, column=3, padx=4, pady=2)
        ttk.Label(mid, text="Service:").grid(row=0, column=4, sticky="w", padx=4, pady=2)
        ttk.Entry(mid, textvariable=self.service_var, width=40).grid(row=0, column=5, padx=4, pady=2)

        ttk.Button(mid, text="Add Record", command=self.add_record).grid(row=0, column=6, padx=6, pady=2)

        # Bottom frame - output
        out = ttk.LabelFrame(self, text="Reminders", padding=8)
        out.pack(fill="both", expand=True, padx=8, pady=8)

        self.text = tk.Text(out, wrap="word")
        self.text.pack(fill="both", expand=True)

        # Ensure CSV exists
        try:
            ensure_csv()
        except Exception as e:
            messagebox.showerror("Error", f"Could not prepare CSV: {e}")

    def open_csv(self):
        path = CSV_FILE.resolve()
        if not path.exists():
            ensure_csv()
        try:
            os.startfile(str(path))  # Windows
        except Exception:
            filedialog.askopenfilename(initialdir=str(path.parent), title="cardata.csv")

    def open_rules(self):
        path = RULES_FILE.resolve()
        if not path.exists():
            messagebox.showwarning("Missing rules", f"Rules file not found: {path}")
            return
        try:
            os.startfile(str(path))  # Windows
        except Exception:
            filedialog.askopenfilename(initialdir=str(path.parent), title="schedule_rules.yaml")

    def add_record(self):
        d = self.date_var.get().strip()
        m = self.rec_miles_var.get().strip()
        s = self.service_var.get().strip()

        if not d or not m or not s:
            messagebox.showwarning("Missing info", "Please fill Date, Mileage, and Service.")
            return

        if parse_date_us(d) is None:
            messagebox.showwarning("Bad date", "Date must be MM/DD/YYYY.")
            return

        try:
            m_val = float(m)
        except Exception:
            messagebox.showwarning("Bad mileage", "Mileage must be a number.")
            return

        ensure_csv()
        try:
            df = pd.read_csv(CSV_FILE)
            if not {"date","mileage","service"}.issubset(df.columns):
                messagebox.showerror("CSV format", "cardata.csv must have columns: date, mileage, service")
                return
            df.loc[len(df)] = {"date": d, "mileage": m_val, "service": s}
            df.to_csv(CSV_FILE, index=False)
            messagebox.showinfo("Added", f"Saved: {d} | {m_val} mi | {s}")
            # reset service/mileage fields
            self.rec_miles_var.set("")
            self.service_var.set("")
        except Exception as e:
            messagebox.showerror("Write error", f"Could not write to CSV: {e}")

    def compute_reminders(self):
        cur = self.mileage_var.get().strip()
        if not cur:
            messagebox.showwarning("Mileage needed", "Enter your current mileage first.")
            return
        try:
            current_mileage = float(cur)
        except Exception:
            messagebox.showwarning("Bad mileage", "Current mileage must be a number.")
            return

        ensure_csv()
        try:
            df = pd.read_csv(CSV_FILE)
        except Exception as e:
            messagebox.showerror("Read error", f"Could not read CSV: {e}")
            return

        if df.empty:
            df = pd.DataFrame(columns=["date","mileage","service"])

        try:
            rules = load_rules()
        except Exception as e:
            messagebox.showerror("Rules error", str(e))
            return

        df = normalize_services(df)
        today = date.today()

        rows = compute_next_due(df, current_mileage, today, rules)

        # Render results
        self.text.delete("1.0", tk.END)
        header = f"Reminders as of {today.strftime('%m/%d/%Y')} | Odometer: {int(current_mileage)} mi\n" \
                 + "-"*70 + "\n"
        self.text.insert(tk.END, header)

        if not rows:
            self.text.insert(tk.END, "No rules found.\n")
            return

        for r in rows:
            due_bits = []
            if r["due_mileage"] is not None:
                due_bits.append(f"due @ {r['due_mileage']} mi (in {r['miles_until']} mi)")
            if r["due_date"] is not None:
                due_bits.append(f"due by {r['due_date']} (in {r['days_until']} days)")
            if not due_bits:
                due_bits.append("no computed due date (check rule intervals/history)")
            block = (
                f"[{r['status']}] {r['key']} ({r['trigger']}) — " + "; ".join(due_bits) + "\n"
                f"  last: {r['last_service']} on {r['last_date']} @ {r['last_mileage']} mi\n"
                f"  interval: {r['miles_interval']} mi / {r['months_interval']} mo\n"
                f"  note: {r['note']}\n\n"
            )
            self.text.insert(tk.END, block)

def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
