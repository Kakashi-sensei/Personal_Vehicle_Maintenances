#!/usr/bin/env python3
import argparse, datetime as dt, json, os
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception: pass
import yaml
DATA_FILE = Path("maintenance_data.json")
CONFIG_FILE = Path("maintenance_config.yaml")
DATE_FMT = "%Y-%m-%d"
def parse_date(s): return None if not s else dt.datetime.strptime(s, DATE_FMT).date()
def today(): return dt.date.today()
def load_config():
    with open(CONFIG_FILE,"r",encoding="utf-8") as f: cfg=yaml.safe_load(f) or {}
    cfg.setdefault("thresholds",{"miles":500,"days":30}); return cfg
def load_data():
    if not DATA_FILE.exists(): return {"odometer":[], "services":[]}
    return json.loads(open(DATA_FILE,"r",encoding="utf-8").read())
def latest_odo(d): return None if not d["odometer"] else max(d["odometer"], key=lambda x:(x["date"],x["miles"]))
def last_service_for_task(d,name):
    sv=[s for s in d["services"] if s.get("task","").lower()==name.lower()]
    return None if not sv else max(sv, key=lambda x:(x["date"], x.get("miles",0)))
def add_months(d0,m):
    y=d0.year+(d0.month-1+m)//12; mo=(d0.month-1+m)%12+1; dim=[31,29 if y%4==0 and (y%100!=0 or y%400==0) else 28,31,30,31,30,31,31,30,31,30,31][mo-1]
    return dt.date(y,mo,min(d0.day,dim))
def compute(t,data,ref_mi,ref_dt,th):
    name=t["name"]; im=t.get("interval_miles"); it=t.get("interval_months"); last=last_service_for_task(data,name)
    if last: a_mi=last.get("miles") or 0; a_dt=parse_date(last.get("date")) or ref_dt
    else: a_mi=t.get("initial_miles",0); a_dt=parse_date(t.get("initial_date")) or ref_dt
    next_mi=a_mi+(im or 0) if im else None; next_dt=add_months(a_dt,it) if it else None
    miles_left=None if next_mi is None or ref_mi is None else next_mi-ref_mi
    days_left=None if next_dt is None else (next_dt-ref_dt).days
    overdue=(miles_left is not None and miles_left<0) or (days_left is not None and days_left<0)
    due_soon=False if overdue else ((miles_left is not None and miles_left<=th.get("miles",500)) or (days_left is not None and days_left<=th.get("days",30)))
    return {"task":name,"next_due_miles":next_mi,"next_due_date":(next_dt.strftime(DATE_FMT) if next_dt else None),"miles_left":miles_left,"days_left":days_left,"overdue":overdue,"due_soon":due_soon}
def render(rows):
    def f(x): return "—" if x is None else str(x)
    out=["TASK | Next Due (Miles) | Next Due (Date) | Miles Left | Days Left | Status","-----|------------------:|-----------------|-----------:|----------:|--------"]
    for r in rows:
        st="OVERDUE" if r["overdue"] else ("Due soon" if r["due_soon"] else "OK")
        out.append(f"{r['task']} | {f(r['next_due_miles'])} | {f(r['next_due_date'])} | {f(r['miles_left'])} | {f(r['days_left'])} | {st}")
    return "\n".join(out)
def build_rows(ref_miles,ref_date):
    cfg=load_config(); data=load_data(); odo=latest_odo(data); ref_mi=ref_miles or (odo['miles'] if odo else None); ref_dt=parse_date(ref_date) if ref_date else dt.date.today()
    return [compute(t,data,ref_mi,ref_dt,cfg.get("thresholds",{})) for t in cfg["tasks"]]
def email(body,to):
    host=os.getenv("SMTP_HOST"); port=int(os.getenv("SMTP_PORT","587")); user=os.getenv("SMTP_USER"); pw=os.getenv("SMTP_PASS"); mail_from=os.getenv("SMTP_FROM", user or "maintenance-bot@example.com")
    if not host or not user or not pw: print("⚠️ Missing SMTP configuration. Preview:\n"+body); return
    import smtplib; from email.message import EmailMessage
    msg=EmailMessage(); msg["Subject"]="Vehicle Maintenance Reminder"; msg["From"]=mail_from; msg["To"]=to; msg.set_content(body)
    with smtplib.SMTP(host,port) as s: s.starttls(); s.login(user,pw); s.send_message(msg)
    print(f"📧 Email sent to {to}")
def main():
    import argparse
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd", required=True)
    ps=sub.add_parser("status"); ps.add_argument("--miles",type=int); ps.add_argument("--date",type=str); ps.set_defaults(func=lambda a: print(render(build_rows(a.miles,a.date))))
    pd=sub.add_parser("due"); pd.add_argument("--miles",type=int); pd.add_argument("--date",type=str); pd.set_defaults(func=lambda a: (lambda rows: print("🎉 Nothing due soon. You're all set." if not [r for r in rows if r['overdue'] or r['due_soon']] else "Items due or due soon:\n"+render([r for r in rows if r['overdue'] or r['due_soon']]))) (build_rows(a.miles,a.date)))
    pe=sub.add_parser("email"); pe.add_argument("--to",type=str,required=True); pe.add_argument("--miles",type=int); pe.add_argument("--date",type=str); pe.set_defaults(func=lambda a: email(render(build_rows(a.miles,a.date)), a.to))
    po=sub.add_parser("add-odo"); po.add_argument("--miles",type=int,required=True); po.add_argument("--date",type=str); po.set_defaults(func=lambda a: (lambda d: (d["odometer"].append({"miles":a.miles,"date":(a.date or dt.date.today().strftime(DATE_FMT))}), open(DATA_FILE,"w",encoding="utf-8").write(json.dumps(d,indent=2)), print(f"✅ Odometer added: {a.miles} on {a.date or dt.date.today().strftime(DATE_FMT)}"))) (load_data()))
    pl=sub.add_parser("log-service"); pl.add_argument("--task",type=str,required=True); pl.add_argument("--miles",type=int,required=True); pl.add_argument("--date",type=str); pl.add_argument("--notes",type=str); pl.set_defaults(func=lambda a: (lambda d: (d["services"].append({"task":a.task,"miles":a.miles,"date":(a.date or dt.date.today().strftime(DATE_FMT)),"notes":(a.notes or "")}), open(DATA_FILE,"w",encoding="utf-8").write(json.dumps(d,indent=2)), print(f"🛠️ Logged service: {a.task} at {a.miles} on {a.date or dt.date.today().strftime(DATE_FMT)}"))) (load_data()))
    a=p.parse_args(); a.func(a)
if __name__=="__main__": main()
