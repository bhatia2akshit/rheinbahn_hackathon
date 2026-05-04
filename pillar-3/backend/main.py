
import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from io import BytesIO
import uvicorn

app = FastAPI(title="Unified Operations Intelligence API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
STORE = {"contribution": None, "workforce": None}

def money(v):
    try: return round(float(v), 2)
    except Exception: return 0.0

def clean_columns(df):
    df = df.copy()
    df.columns = [str(c).strip().replace("\ufeff", "").replace(" ", "_").replace("-", "_").lower() for c in df.columns]
    return df

def read_csv_upload(file_bytes):
    for enc in ["utf-8", "latin1", "cp1252"]:
        try: return pd.read_csv(BytesIO(file_bytes), encoding=enc)
        except Exception: pass
    raise HTTPException(status_code=400, detail="Could not read CSV file.")

def generate_contribution_dummy():
    np.random.seed(42); departments=["Operations Tram","Operations Bus","Maintenance","Infrastructure","Customer Service","Administration"]; rows=[]
    for quarter in ["Q1 2025","Q2 2025","Q3 2025","Q4 2025"]:
        for dept in departments:
            revenue=np.random.randint(850000,1800000); labour=np.random.randint(280000,780000); materials=np.random.randint(70000,280000); external=np.random.randint(40000,210000); absence=np.random.randint(20000,110000); delay_loss=np.random.randint(15000,180000)
            total_cost=labour+materials+external+absence+delay_loss; margin=revenue-total_cost
            rows.append({"quarter":quarter,"department":dept,"revenue":revenue,"labour_cost":labour,"material_cost":materials,"external_cost":external,"absence_cost":absence,"delay_loss":delay_loss,"total_cost":total_cost,"contribution_margin":margin,"margin_pct":round((margin/revenue)*100,1)})
    return pd.DataFrame(rows)

def generate_workforce_dummy():
    np.random.seed(7); routes=["U35","302","306","308","310","318","SB37","CE31"]; reasons=["Construction Detour","Traffic Jam","Police Action","Accident","Late Shift Handover","Break Not Taken","Vehicle Issue","Signal Problem"]; rows=[]; start=datetime(2025,5,1)
    for i in range(260):
        route=np.random.choice(routes); reason=np.random.choice(reasons,p=[.22,.23,.09,.13,.10,.09,.08,.06]); date=start+timedelta(days=int(np.random.randint(0,90))); delay=int(np.random.gamma(3,9)); no_break=1 if reason=="Break Not Taken" or np.random.random()<.18 else 0; sick=1 if np.random.random()<.09 else 0
        overtime=max(0,round((delay/60)*np.random.uniform(.7,1.8)+(.7 if no_break else 0)+(.4 if reason=="Late Shift Handover" else 0),1))
        rows.append({"date":date.strftime("%Y-%m-%d"),"quarter":f"Q{((date.month-1)//3)+1} {date.year}","route_id":route,"department":"Operations Tram" if route not in ["SB37","CE31"] else "Operations Bus","driver_id":f"D{100+np.random.randint(1,95)}","planned_hours":8,"actual_hours":round(8+overtime,1),"overtime_hours":overtime,"delay_minutes":delay,"incident_reason":reason,"break_taken":"no" if no_break else "yes","sick_leave":sick,"detour_flag":1 if reason=="Construction Detour" else 0,"traffic_level":np.random.choice(["low","medium","high"],p=[.22,.48,.3]),"police_action":1 if reason=="Police Action" else 0,"accident_flag":1 if reason=="Accident" else 0,"construction_flag":1 if reason=="Construction Detour" else 0,"overtime_cost":round(overtime*np.random.uniform(35,52),2)})
    return pd.DataFrame(rows)

def contribution_from_df(df):
    source="uploaded" if STORE["contribution"] is not None else "dummy"; df=clean_columns(df)
    dept_col=next((c for c in df.columns if c in ["department","dept","bereich","cost_center","kst","route","unit"]), df.columns[0])
    period_col=next((c for c in df.columns if c in ["quarter","period","month","date","year_quarter"]), None)
    for c in df.columns: df[c]=pd.to_numeric(df[c], errors="ignore")
    numeric_cols=list(df.select_dtypes(include="number").columns)
    revenue_col=next((c for c in df.columns if c in ["revenue","sales","income","umsatz"]), None) or (numeric_cols[0] if numeric_cols else None)
    total_cost_col=next((c for c in df.columns if c in ["total_cost","cost","costs","gesamtkosten"]), None)
    margin_col=next((c for c in df.columns if c in ["contribution_margin","margin","db","db2","profit","non_profit_kpa"]), None)
    if total_cost_col is None:
        cost_candidates=[c for c in numeric_cols if any(x in c for x in ["cost","kosten","labour","labor","material","absence","delay"])]
        if cost_candidates: df["__total_cost"]=df[cost_candidates].sum(axis=1); total_cost_col="__total_cost"
    if margin_col is None and revenue_col and total_cost_col: df["__contribution_margin"]=df[revenue_col]-df[total_cost_col]; margin_col="__contribution_margin"
    if margin_col is None and numeric_cols: margin_col=numeric_cols[-1]
    if margin_col is None: raise HTTPException(status_code=400, detail="No numeric contribution columns found.")
    group_cols=[dept_col]+([period_col] if period_col and period_col!=dept_col else [])
    nums=list(df.select_dtypes(include="number").columns)
    grouped=df.groupby(group_cols, dropna=False).agg({c:"sum" for c in nums}).reset_index()
    if period_col and period_col in grouped.columns:
        latest_period=sorted(grouped[period_col].astype(str).unique())[-1]; latest=grouped[grouped[period_col].astype(str)==latest_period].copy()
    else: latest_period="Uploaded file" if source=="uploaded" else "Dummy data"; latest=grouped.copy()
    departments=[]
    for _, row in latest.iterrows():
        revenue=money(row[revenue_col]) if revenue_col in row else 0; total_cost=money(row[total_cost_col]) if total_cost_col in row else 0; margin=money(row[margin_col]) if margin_col in row else 0; margin_pct=round((margin/revenue)*100,1) if revenue else 0
        departments.append({"department":str(row[dept_col]),"period":latest_period,"revenue":revenue,"totalCost":total_cost,"contributionMargin":margin,"marginPct":margin_pct,"raw":{c:money(row[c]) for c in nums if c in row}})
    trend=[]
    if period_col and period_col in grouped.columns:
        for _, row in grouped.iterrows(): trend.append({"period":str(row[period_col]),"department":str(row[dept_col]),"value":money(row[margin_col])})
    return {"source":source,"period":latest_period,"departments":sorted(departments,key=lambda x:x["contributionMargin"]),"trend":trend,"kpis":{"revenue":money(sum(d["revenue"] for d in departments)),"totalCost":money(sum(d["totalCost"] for d in departments)),"contributionMargin":money(sum(d["contributionMargin"] for d in departments)),"averageMarginPct":round(float(np.mean([d["marginPct"] for d in departments])),1) if departments else 0}}

def workforce_from_df(df):
    source="uploaded" if STORE["workforce"] is not None else "dummy"; df=clean_columns(df)
    if "route_id" not in df.columns and "route" in df.columns: df["route_id"]=df["route"]
    if "department" not in df.columns: df["department"]="Operations"
    if "incident_reason" not in df.columns and "reason" in df.columns: df["incident_reason"]=df["reason"]
    if "incident_reason" not in df.columns: df["incident_reason"]="Unknown"
    if "break_taken" not in df.columns: df["break_taken"]="yes"
    if "sick_leave" not in df.columns: df["sick_leave"]=0
    if "date" not in df.columns: df["date"]="2025-05-01"
    if "overtime_hours" not in df.columns: df["overtime_hours"]=0
    if "delay_minutes" not in df.columns: df["delay_minutes"]=0
    if "overtime_cost" not in df.columns: df["overtime_cost"]=pd.to_numeric(df["overtime_hours"], errors="coerce").fillna(0)*42
    for c in ["overtime_hours","delay_minutes","sick_leave","overtime_cost"]: df[c]=pd.to_numeric(df[c], errors="coerce").fillna(0)
    total_overtime=df["overtime_hours"].sum(); total_cost=df["overtime_cost"].sum(); no_break_rate=round(df["break_taken"].astype(str).str.lower().eq("no").mean()*100,1); sick_rate=round(df["sick_leave"].mean()*100,1)
    routes=df.groupby("route_id").agg(overtimeHours=("overtime_hours","sum"),overtimeCost=("overtime_cost","sum"),delayMinutes=("delay_minutes","mean"),incidents=("route_id","count")).reset_index().sort_values("overtimeHours",ascending=False).round(2).to_dict(orient="records")
    reasons=df.groupby("incident_reason").agg(overtimeHours=("overtime_hours","sum"),overtimeCost=("overtime_cost","sum"),delayMinutes=("delay_minutes","mean"),incidents=("incident_reason","count")).reset_index().sort_values("overtimeHours",ascending=False).round(2).to_dict(orient="records")
    daily=df.groupby("date").agg(overtimeHours=("overtime_hours","sum"),sickLeaves=("sick_leave","sum")).reset_index().sort_values("date").round(2).to_dict(orient="records")
    return {"source":source,"kpis":{"overtimeHours":round(float(total_overtime),1),"overtimeCost":money(total_cost),"noBreakRate":no_break_rate,"sickLeaveRate":sick_rate,"incidents":int(len(df))},"routes":routes,"reasons":reasons,"daily":daily,"records":df.head(80).to_dict(orient="records")}

@app.get("/api/dashboard")
def dashboard():
    contribution=contribution_from_df(STORE["contribution"] if STORE["contribution"] is not None else generate_contribution_dummy())
    workforce=workforce_from_df(STORE["workforce"] if STORE["workforce"] is not None else generate_workforce_dummy())
    worst_dept=contribution["departments"][0] if contribution["departments"] else {}; worst_route=workforce["routes"][0] if workforce["routes"] else {}; top_reason=workforce["reasons"][0] if workforce["reasons"] else {}
    return {"contribution":contribution,"workforce":workforce,"overview":{"alerts":[{"level":"critical","title":f"Weakest contribution margin: {worst_dept.get('department','-')}","body":f"Margin is {worst_dept.get('marginPct',0)}%. Review cost drivers and operational losses."},{"level":"warning","title":f"Highest overtime route: {worst_route.get('route_id','-')}","body":f"{worst_route.get('overtimeHours',0)} hours caused by delays and incidents."},{"level":"info","title":f"Top overtime reason: {top_reason.get('incident_reason','-')}","body":f"{top_reason.get('overtimeHours',0)} overtime hours linked to this reason."}]}}

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.post("/api/upload/contribution")
async def upload_contribution(file: UploadFile = File(...)):
    df=read_csv_upload(await file.read()); STORE["contribution"]=df; return {"status":"ok","view":"contribution","rows":len(df),"columns":list(df.columns)}
@app.post("/api/upload/workforce")
async def upload_workforce(file: UploadFile = File(...)):
    df=read_csv_upload(await file.read()); STORE["workforce"]=df; return {"status":"ok","view":"workforce","rows":len(df),"columns":list(df.columns)}
@app.post("/api/reset")
def reset_data(): STORE["contribution"]=None; STORE["workforce"]=None; return {"status":"ok"}

if __name__ == "__main__":
    port = int(os.getenv("UNIFIED_OPS_PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port)
