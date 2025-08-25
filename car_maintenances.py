import os
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import pandas as pd
import yaml

# File paths
DATA_FILE = Path("2018_Camry_data.csv")
RULES_FILE = Path("2018_Camry_schedule_rules.yaml")

def ensure_data():
    if not DATA_FILE.exists():
        pd.DataFrame(columns=["date","mileage","service"]).to_csv(DATA_FILE, index=False)

def parse_date_us(s):
    try:
        return datetime.strptime(str(s), "%m/%d/%Y").date()
    except Exception:
        return None

def load_rules():
    if not RULES_FILE.exists():
        messagebox.showerror("Rules Missing", f"Could not find {RULES_FILE}")
        return {"vehicle_name": "Unknown", "rules": []}
    data = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    return data

def normalize_services(df):
    df = df.copy()
    df["service_text"] = df["service"].astype(str)
    df["service_norm"] = df["service_text"].str.lower()
    return df

def last_event_for_rule(df, rule):
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
        miles_int = int(rule.get("miles_interval",0) or 0)
        months_int = int(rule.get("months_interval",0) or 0)
        trigger = str(rule.get("trigger","earliest")).lower()
        last = last_event_for_rule(df, rule)

        due_mileage, due_date = None, None
        if last:
            last_mi = float(last.get("mileage")) if pd.notnull(last.get("mileage")) else None
            last_date = parse_date_us(last.get("date"))
            if miles_int>0 and last_mi is not None:
                due_mileage = last_mi + miles_int
            if months_int>0 and last_date is not None and trigger!="mileage_only":
                due_date = last_date + relativedelta(months=+months_int)
        else:
            if miles_int>0: due_mileage = miles_int
            if months_int>0 and trigger!="mileage_only": due_date = today

        miles_until = None if due_mileage is None else int(due_mileage - current_mileage)
        days_until = None if due_date is None else (due_date - today).days

        overdue = (miles_until is not None and miles_until<=0) or (days_until is not None and days_until<=0)
        status = "OVERDUE" if overdue else "upcoming"

        results.append({
            "label": rule.get("label", rule.get("key")),
            "note": rule.get("note",""),
            "last_service": last["service_text"] if last else "(none)",
            "last_date": last.get("date") if last else None,
            "last_mileage": last.get("mileage") if last else None,
            "due_mileage": due_mileage,
            "due_date": due_date.strftime("%Y-%m-%d") if due_date else None,
            "miles_until": miles_until,
            "days_until": days_until,
            "status": status
        })
    return results

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.rules_data = load_rules()
        self.vehicle_name = self.rules_data.get("vehicle_name","Unknown Vehicle")
        self.rules = self.rules_data.get("rules",[])

        self.title(f"Car Maintenances — {self.vehicle_name}")
        self.geometry("900x600")

        # Mileage entry
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Current Mileage:").pack(side="left")
        self.mileage_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.mileage_var, width=10).pack(side="left", padx=4)
        ttk.Button(top, text="Compute Reminders", command=self.compute).pack(side="left", padx=6)

        # Add record
        mid = ttk.LabelFrame(self, text="Add Maintenance Record", padding=8)
        mid.pack(fill="x", padx=8, pady=8)

        self.date_var = tk.StringVar(value=date.today().strftime("%m/%d/%Y"))
        self.rec_miles_var = tk.StringVar()
        self.service_var = tk.StringVar()

        ttk.Label(mid, text="Date:").grid(row=0,column=0,padx=4)
        ttk.Entry(mid, textvariable=self.date_var, width=12).grid(row=0,column=1)
        ttk.Label(mid, text="Mileage:").grid(row=0,column=2,padx=4)
        ttk.Entry(mid, textvariable=self.rec_miles_var, width=10).grid(row=0,column=3)
        ttk.Label(mid, text="Service:").grid(row=0,column=4,padx=4)

        labels = [r.get("label",r.get("key")) for r in self.rules]
        self.service_combo = ttk.Combobox(mid, textvariable=self.service_var, values=labels, state="readonly", width=40)
        self.service_combo.grid(row=0,column=5)
        ttk.Button(mid, text="Add", command=self.add_record).grid(row=0,column=6,padx=4)

        # Output box
        out = ttk.LabelFrame(self, text="Reminders", padding=8)
        out.pack(fill="both", expand=True, padx=8, pady=8)
        self.text = tk.Text(out, wrap="word")
        self.text.pack(fill="both", expand=True)

        ensure_data()

    def add_record(self):
        d, m, s = self.date_var.get().strip(), self.rec_miles_var.get().strip(), self.service_var.get().strip()
        if not d or not m or not s:
            messagebox.showwarning("Missing","Fill all fields")
            return
        if parse_date_us(d) is None:
            messagebox.showwarning("Bad date","Use MM/DD/YYYY")
            return
        try: m_val = float(m)
        except: 
            messagebox.showwarning("Bad mileage","Enter a number")
            return
        df = pd.read_csv(DATA_FILE)
        df.loc[len(df)] = {"date":d,"mileage":m_val,"service":s}
        df.to_csv(DATA_FILE,index=False)
        messagebox.showinfo("Saved", f"Added: {d} | {m_val} mi | {s}")
        self.rec_miles_var.set(""); self.service_var.set("")

    def compute(self):
        try: cur_mi = float(self.mileage_var.get())
        except: 
            messagebox.showwarning("Mileage needed","Enter current mileage")
            return
        df = pd.read_csv(DATA_FILE)
        df = normalize_services(df)
        rows = compute_next_due(df, cur_mi, date.today(), self.rules)
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, f"{self.vehicle_name} — Maintenance Reminders\n")
        self.text.insert(tk.END, f"Today: {date.today().strftime('%m/%d/%Y')} | Odometer: {int(cur_mi)} mi\n")
        self.text.insert(tk.END, "-"*70+"\n")
        for r in rows:
            due = []
            if r["due_mileage"]: due.append(f"due @ {int(r['due_mileage'])} mi (in {r['miles_until']} mi)")
            if r["due_date"]: due.append(f"due by {r['due_date']} (in {r['days_until']} days)")
            if not due: due.append("no due info")
            self.text.insert(tk.END, f"[{r['status']}] {r['label']}: " + "; ".join(due) + "\n")
            self.text.insert(tk.END, f"  last: {r['last_service']} on {r['last_date']} @ {r['last_mileage']} mi\n")
            self.text.insert(tk.END, f"  note: {r['note']}\n\n")

if __name__=="__main__":
    App().mainloop()
