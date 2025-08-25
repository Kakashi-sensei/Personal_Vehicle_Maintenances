import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import font as tkfont
from pathlib import Path
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import pandas as pd
import yaml

APP_TITLE = "Car Maintenances"

# Single-vehicle files (adjust names if you change them)
DATA_FILE = Path("2018_Camry_data.csv")
RULES_FILE = Path("2018_Camry_schedule_rules.yaml")

# ---------------- Core helpers ----------------

def ensure_data():
    """Ensure the CSV exists with expected columns."""
    if not DATA_FILE.exists():
        pd.DataFrame(columns=["date", "mileage", "service", "note"]).to_csv(DATA_FILE, index=False)
    else:
        # Add note column if missing
        df = pd.read_csv(DATA_FILE)
        changed = False
        if "note" not in df.columns:
            df["note"] = ""
            changed = True
        # Normalize columns if someone re-ordered/renamed
        needed = ["date", "mileage", "service", "note"]
        for c in needed:
            if c not in df.columns:
                df[c] = "" if c != "mileage" else 0
                changed = True
        if changed:
            df[["date","mileage","service","note"]].to_csv(DATA_FILE, index=False)

def parse_date_us(s):
    """Parse MM/DD/YYYY -> date."""
    try:
        return datetime.strptime(str(s), "%m/%d/%Y").date()
    except Exception:
        return None

def load_rules():
    """Load YAML rules; expect {vehicle_name: str, rules: list}."""
    if not RULES_FILE.exists():
        messagebox.showerror("Rules Missing", f"Could not find {RULES_FILE}")
        return {"vehicle_name": "Unknown Vehicle", "rules": []}
    data = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        messagebox.showerror("Rules Error", "Rules file must be a YAML mapping with vehicle_name and rules.")
        return {"vehicle_name": "Unknown Vehicle", "rules": []}
    data.setdefault("vehicle_name", "Unknown Vehicle")
    data.setdefault("rules", [])
    return data

def normalize_services(df):
    """Lowercase copy for keyword matching; keep original text and note."""
    df = df.copy()
    if "service" not in df.columns:
        df["service"] = ""
    if "note" not in df.columns:
        df["note"] = ""
    df["service_text"] = df["service"].astype(str)
    df["service_norm"] = df["service_text"].str.lower()
    return df

def last_event_for_rule(df, rule):
    """Find most recent row matching any keyword; return dict with note."""
    mask = pd.Series(False, index=df.index)
    for kw in rule.get("match", []):
        mask |= df["service_norm"].str.contains(kw, na=False)
    hits = df[mask].copy()
    if hits.empty:
        return None
    hits["parsed_date"] = hits["date"].apply(parse_date_us)
    hits = hits.sort_values(["parsed_date", "mileage"], ascending=[True, True])
    return hits.iloc[-1].to_dict()

def compute_next_due(df, current_mileage, today, rules):
    """Compute due status per rule; return list of rows for rendering."""
    results = []
    for rule in rules:
        miles_int = int(rule.get("miles_interval", 0) or 0)
        months_int = int(rule.get("months_interval", 0) or 0)
        trigger = str(rule.get("trigger", "earliest")).lower()
        label = rule.get("label", rule.get("key", "Unnamed"))
        rule_note = rule.get("note", "")

        last = last_event_for_rule(df, rule)

        due_mileage, due_date = None, None
        if last:
            last_mi = float(last.get("mileage")) if pd.notnull(last.get("mileage")) else None
            last_date = parse_date_us(last.get("date"))
            if miles_int > 0 and last_mi is not None:
                due_mileage = last_mi + miles_int
            if months_int > 0 and last_date is not None and trigger != "mileage_only":
                due_date = last_date + relativedelta(months=+months_int)
        else:
            if miles_int > 0:
                due_mileage = miles_int
            if months_int > 0 and trigger != "mileage_only":
                due_date = today

        miles_until = None if due_mileage is None else int(due_mileage - current_mileage)
        days_until = None if due_date is None else (due_date - today).days

        overdue = (miles_until is not None and miles_until <= 0) or (days_until is not None and days_until <= 0)
        status = "OVERDUE" if overdue else "upcoming"

        results.append({
            "label": label,
            "rule_note": rule_note,
            "last_service": last["service_text"] if last else "(none)",
            "last_note": last.get("note") if last else "",
            "last_date": last.get("date") if last else None,
            "last_mileage": last.get("mileage") if last else None,
            "due_mileage": due_mileage,
            "due_date": due_date.strftime("%Y-%m-%d") if due_date else None,
            "miles_until": miles_until,
            "days_until": days_until,
            "status": status
        })
    return results

# ---------------- GUI ----------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        ensure_data()

        # Load rules and set title with vehicle name
        self.rules_data = load_rules()
        self.vehicle_name = self.rules_data.get("vehicle_name", "Unknown Vehicle")
        self.rules = self.rules_data.get("rules", [])

        self.title(f"{APP_TITLE} — {self.vehicle_name}")
        self.geometry("1000x720")
        self.minsize(860, 560)

        # Top bar
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Current Mileage:").pack(side="left")
        self.mileage_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.mileage_var, width=12).pack(side="left", padx=6)
        ttk.Button(top, text="Compute Reminders", command=self.compute).pack(side="left", padx=6)

        # Add record section
        mid = ttk.LabelFrame(self, text="Add Maintenance Record", padding=8)
        mid.pack(fill="x", padx=8, pady=8)

        self.date_var = tk.StringVar(value=date.today().strftime("%m/%d/%Y"))
        self.rec_miles_var = tk.StringVar()
        self.service_var = tk.StringVar()
        self.note_var = tk.StringVar()

        ttk.Label(mid, text="Date (MM/DD/YYYY):").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(mid, textvariable=self.date_var, width=16).grid(row=0, column=1, padx=4, pady=2)

        ttk.Label(mid, text="Mileage:").grid(row=0, column=2, sticky="w", padx=4, pady=2)
        ttk.Entry(mid, textvariable=self.rec_miles_var, width=12).grid(row=0, column=3, padx=4, pady=2)

        ttk.Label(mid, text="Service:").grid(row=0, column=4, sticky="w", padx=4, pady=2)
        labels = [r.get("label", r.get("key", "")) for r in self.rules]
        labels.append("Other")  # allow catch-all
        self.service_combo = ttk.Combobox(mid, textvariable=self.service_var, values=labels, state="readonly", width=42)
        self.service_combo.grid(row=0, column=5, padx=4, pady=2)

        ttk.Button(mid, text="Add Record", command=self.add_record).grid(row=0, column=6, padx=8, pady=2)

        ttk.Label(mid, text="Note:").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(mid, textvariable=self.note_var, width=70).grid(row=1, column=1, columnspan=5, sticky="we", padx=4, pady=2)

        # Output (report)
        out = ttk.LabelFrame(self, text="Reminders", padding=8)
        out.pack(fill="both", expand=True, padx=8, pady=8)

        # Larger font for readability
        self.report_font = tkfont.Font(family="Segoe UI", size=12)
        self.text = tk.Text(out, wrap="word", font=self.report_font)
        self.text.pack(fill="both", expand=True)

        # Color tags for status
        self.text.tag_config("OVERDUE", background="#c62828", foreground="white")   # red
        self.text.tag_config("upcoming", background="#fff59d", foreground="black") # yellow

    # ----- Actions -----

    def add_record(self):
        d = self.date_var.get().strip()
        m = self.rec_miles_var.get().strip()
        s = self.service_var.get().strip()
        n = self.note_var.get().strip()

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

        try:
            df = pd.read_csv(DATA_FILE) if DATA_FILE.exists() else pd.DataFrame(columns=["date", "mileage", "service", "note"])
            if "note" not in df.columns:
                df["note"] = ""
            df.loc[len(df)] = {"date": d, "mileage": m_val, "service": s, "note": n}
            df[["date","mileage","service","note"]].to_csv(DATA_FILE, index=False)
            messagebox.showinfo("Added", f"Saved: {d} | {m_val} mi | {s}" + (f" | Note: {n}" if n else ""))
            # reset inputs
            self.rec_miles_var.set("")
            self.service_var.set("")
            self.note_var.set("")
        except Exception as e:
            messagebox.showerror("Write error", f"Could not write to data file:\n{e}")

    def compute(self):
        cur = self.mileage_var.get().strip()
        if not cur:
            messagebox.showwarning("Mileage needed", "Enter your current mileage first.")
            return
        try:
            current_mileage = float(cur)
        except Exception:
            messagebox.showwarning("Bad mileage", "Current mileage must be a number.")
            return

        try:
            df = pd.read_csv(DATA_FILE) if DATA_FILE.exists() else pd.DataFrame(columns=["date", "mileage", "service", "note"])
        except Exception as e:
            messagebox.showerror("Read error", f"Could not read data file:\n{e}")
            return

        df = normalize_services(df)
        today = date.today()
        rows = compute_next_due(df, current_mileage, today, self.rules)

        # Render with colored status lines
        self.text.delete("1.0", tk.END)
        header = (
            f"{self.vehicle_name} — Maintenance Reminders\n"
            f"Today: {today.strftime('%m/%d/%Y')} | Odometer: {int(current_mileage)} mi\n"
            + "-" * 72 + "\n"
        )
        self.text.insert(tk.END, header)

        for r in rows:
            # Build main line and apply tag
            due_bits = []
            if r["due_mileage"] is not None:
                due_bits.append(f"due @ {int(r['due_mileage'])} mi (in {r['miles_until']} mi)")
            if r["due_date"] is not None:
                due_bits.append(f"due by {r['due_date']} (in {r['days_until']} days)")
            if not due_bits:
                due_bits.append("no computed due date (check intervals/history)")

            status_line = f"[{r['status']}] {r['label']}: " + "; ".join(due_bits) + "\n"
            start_idx = self.text.index(tk.INSERT)
            self.text.insert(tk.END, status_line)
            end_idx = self.text.index(tk.INSERT)
            tag_name = "OVERDUE" if r["status"] == "OVERDUE" else "upcoming"
            self.text.tag_add(tag_name, start_idx, end_idx)

            # Details (no background)
            self.text.insert(tk.END, f"  last: {r['last_service']} on {r['last_date']} @ {r['last_mileage']} mi\n")
            # Show last note (from your log) and rule note (from schedule)
            if r.get("last_note"):
                self.text.insert(tk.END, f"  last note: {r['last_note']}\n")
            if r.get("rule_note"):
                self.text.insert(tk.END, f"  schedule note: {r['rule_note']}\n")
            self.text.insert(tk.END, "\n")

# ---------------- Main ----------------

if __name__ == "__main__":
    App().mainloop()