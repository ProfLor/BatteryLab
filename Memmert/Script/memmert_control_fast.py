import requests, yaml, time, sys, math
try: import numpy as np
except: np = None

# Fast-mode controller for local simulator (100x accelerated dynamics)
BASE_URL="http://127.0.0.1:8000/atmoweb"; CFG="IPP30_TEMP_CNTRL.yaml"
TIMEOUT_S=5; RETRIES=3; RETRY_DELAY_S=1; FAST=100.0

def cfg():
    """Load config: returns (target, wait_min, tolerance, config_dict)"""
    try:
        c=yaml.safe_load(open(CFG,"r",encoding="utf-8")) or {}
        wait_m=int(c.get("wait_time",0)); tol=float(c.get("tolerance",0.5))
        # Ensure tau_info keys exist for persistence
        for k in ['tau_heating_info','tau_cooling_info']:
            if k not in c: c[k]=''
        if "target_temperatures" in c:
            temps=c["target_temperatures"]
            if not temps or not isinstance(temps,list): print("[ERROR] target_temperatures must be non-empty list"); sys.exit(1)
            idx=int(c.get("current_set_index",0))
            if not(0<=idx<len(temps)): print(f"[ERROR] current_set_index {idx} out of range"); sys.exit(1)
            return float(temps[idx]),wait_m,tol,{"temps":temps,"idx":idx,"c":c}
        return float(c["target_temperature"]),wait_m,tol,{"temps":[c["target_temperature"]],"idx":0,"c":c}
    except Exception as e: print(f"[ERROR] Config: {e}"); sys.exit(1)

def http_get(url):
    """HTTP GET with retry logic"""
    for i in range(1,RETRIES+1):
        try: return requests.get(url,timeout=TIMEOUT_S)
        except (requests.exceptions.Timeout,requests.exceptions.ConnectionError) as e:
            if i<RETRIES: print(f"[WARN] Retry {i}/{RETRIES}"); time.sleep(RETRY_DELAY_S)
        except Exception as e: print(f"[ERROR] HTTP: {e}"); sys.exit(1)
    print("[ERROR] Unreachable"); sys.exit(1)

def get_state():
    """Returns (current_temp, range_dict)"""
    r=http_get(f"{BASE_URL}?Temp1Read=&TempSet_Range=")
    if r.status_code!=200: print(f"[ERROR] HTTP {r.status_code}"); sys.exit(1)
    try:
        d=r.json()
        cur=float(d["Temp1Read"])
        rng={"min":float(d["TempSet_Range"]["min"]),"max":float(d["TempSet_Range"]["max"])}
        return cur,rng
    except:
        t=r.text.strip()
        cur=float(t.split("Temp1Read=")[1].split("&")[0]) if "Temp1Read=" in t else None
        if cur is None: print("[ERROR] No Temp1Read"); sys.exit(1)
        print("[ERROR] No TempSet_Range"); sys.exit(3)

def set_target(temp):
    """Set target temperature"""
    r=http_get(f"{BASE_URL}?TempSet={temp}")
    if r.status_code!=200: print(f"[ERROR] HTTP {r.status_code}"); sys.exit(1)

def progress_bar(cur,tgt,start,w=20):
    """Progress bar from start to target"""
    if abs(tgt-start)<0.1: return "["+"#"*w+"]"
    p=max(0,min(1,(cur-start)/(tgt-start))); f=int(p*w)
    return f"[{'#'*f}{'_'*(w-f)}]"

def estimate_eta_ekf(readings,target,tau_h,tau_c,dt):
    """Extended Kalman Filter for tau estimation and ETA prediction"""
    if np is None or len(readings)<2: return None,{}
    w=readings[-10:]; temps=[x for _,x in w]; T0,cur=temps[0],temps[-1]
    heating=target>cur; tau0=tau_h if heating else tau_c; Tinf=float(target)
    # 2-state EKF: [T_current, tau]
    x=np.array([T0,tau0],dtype=float)
    P=np.diag([10.0,2.0]); Q=np.diag([0.05**2,0.002**2]); R=0.1**2
    H=np.array([1.0,0.0])
    for i in range(1,len(temps)):
        Tm,Tp=temps[i],temps[i-1]; tau_k=max(x[1],1e-3); a=np.exp(-dt/tau_k)
        # Jacobian: ∂T/∂τ = (dt/τ²)(Tp-Tinf)e^(-dt/τ)
        A=np.array([[a,(dt/tau_k**2)*(Tp-Tinf)*a],[0.0,1.0]])
        # Predict
        x_pred=np.array([a*Tp+(1-a)*Tinf,x[1]]); P_pred=A@P@A.T+Q
        # Update with gain limiting
        K=(P_pred@H)/(H@P_pred@H+R)
        K_lim=np.array([K[0],np.clip(K[1],-0.05,0.05)])  # Limit tau gain
        x=x_pred+K_lim*(Tm-H@x_pred); P=P_pred-np.outer(K_lim,K_lim)*(H@P_pred@H+R)
    tau=max(float(x[1]),1e-3); err=abs(cur-Tinf)
    if err<0.01: return 0.0,{"tau":tau}
    return max(0.0,-tau*np.log(0.01/err)),{"tau":tau}

def estimate_eta_exp(readings,target,tau_h,tau_c,tol):
    """Exponential model with fixed tau from config"""
    if not readings: return None,{}
    w=readings[-10:]; T0,cur=w[0][1],w[-1][1]
    heating=target>cur; Tinf=float(target)
    tau=float(tau_h if heating else tau_c)
    # Optional: fit tau from data (least-squares on log-transformed)
    min_delta=max(tol*2,0.01)
    if len(w)>=3:
        t0=w[0][0]; pts=[]
        for t,T in w:
            if abs(T0-Tinf)>min_delta and abs(T-Tinf)>min_delta:
                pts.append(((t-t0)/60.0,math.log(abs((T-Tinf)/(T0-Tinf)))))
        if len(pts)>=3:
            n=len(pts); st,sy=sum(t for t,_ in pts),sum(y for _,y in pts)
            st2,sty=sum(t*t for t,_ in pts),sum(t*y for t,y in pts)
            denom=n*st2-st*st
            if abs(denom)>1e-9:
                slope=(n*sty-st*sy)/denom
                if slope<-1e-6: tau=-1.0/slope
    err=abs(cur-Tinf)
    if err<0.01: return 0.0,{"tau":tau}
    return max(0.0,-tau*math.log(0.01/err)),{"tau":tau}

def write_config(temps,idx,c):
    """Write config YAML with all sections"""
    lines=["# IPP30_TEMP_CNTRL.yaml\n# Configuration for Memmert IPP30 temperature control\n",
           "# Target temperature sequence\ntarget_temperatures:"]
    for i,t in enumerate(temps): lines.append(f"  - {float(t)}" + ("  # <-- current SetTemp" if i==idx else ""))
    lines.extend(["",f"# Active setpoint index (0-based)\ncurrent_set_index: {idx}","",
                  f"# Wait time after reaching target (minutes)\nwait_time: {int(c.get('wait_time',0))}","",
                  f"# Temperature tolerance for target reached (°C)\ntolerance: {float(c.get('tolerance',0.5))}","",
                  "# ETA prediction model: 1=Exponential (least-squares τ fit), 2=EKF (Extended Kalman Filter)",
                  f"eta_model: {int(c.get('eta_model',1))}","",
                  "# Update tau with EKF estimates: 0=no (keep user values), 1=yes (override with learned values)",
                  f"tau_override: {int(c.get('tau_override',0))}",""])
    for mode,key,info_key in [("heating","tau_heating","tau_heating_info"),("cooling","tau_cooling","tau_cooling_info")]:
        tau,info=float(c.get(key,10.0)),c.get(info_key,'')
        lines.append(f"# {mode.capitalize()} time constant (minutes)\n{key}: {tau}")
        if info: lines.append(f'{info_key}: "{info}"')
        lines.append("")
    lines.append(f"# Sampling interval for temperature readings (minutes)\ndt_minutes: {float(c.get('dt_minutes',1.0))}")
    try: open(CFG,"w",encoding="utf-8").write("\n".join(lines)+"\n")
    except Exception as e: print(f"[WARN] Config write failed: {e}")

def main():
    tgt,wait_m,tol,cfg_obj=cfg(); cur,rng=get_state(); mn,mx=rng['min'],rng['max']
    c=cfg_obj['c']
    print(f"[INFO] [FASTx{int(FAST)}] Target {tgt}°C | Range {mn}–{mx}°C | Current {cur:.2f}°C | Tol ±{tol}°C")
    if not(mn<=tgt<=mx): print(f"[ERROR] Target {tgt}°C outside [{mn},{mx}]"); sys.exit(1)
    set_target(tgt)
    # Scale parameters for FAST mode
    dt_min=max(0.05,float(c.get('dt_minutes',1.0))/FAST)
    tau_h,tau_c=max(0.001,float(c.get('tau_heating',10.0))/FAST),max(0.001,float(c.get('tau_cooling',10.0))/FAST)
    wait_scaled=max(0,int(round(wait_m/FAST)))
    sleep_s=max(0.5,dt_min*60.0); start_temp=cur
    em=int(c.get('eta_model',1))
    if em==2: print("[INFO] ETA Model: Extended Kalman Filter (EKF) | T(t)=T∞+(T₀-T∞)e^(-t/τ)")
    else: print(f"[INFO] ETA Model: Exponential | T(t)=T∞+(T₀-T∞)e^(-t/τ), τ={(tau_h if tgt>start_temp else tau_c):.2f}m")
    print(f"[INFO] Monitoring with {dt_min:.2f}m updates (FAST x{int(FAST)}) …")
    
    readings=[]; start=time.time(); tau_h_est,tau_c_est=tau_h,tau_c
    while True:
        cur,_=get_state(); now=time.time(); readings.append((now,cur))
        if em==2:
            eta,ex=estimate_eta_ekf(readings,tgt,tau_h_est,tau_c_est,dt_min); tag='[EKF]'
            tau_show=ex.get('tau',tau_h if tgt>start_temp else tau_c)
            if tau_show>0.01:
                if tgt>start_temp: tau_h_est=tau_show
                else: tau_c_est=tau_show
            eta_str=f"ETA~{eta:.1f}m" if eta else "ETA~--"; param_str=f" τ={tau_show:.2f}m"
        else:
            eta,ex=estimate_eta_exp(readings,tgt,tau_h,tau_c,tol); tag='[EXP]'
            eta_str=f"ETA~{eta:.1f}m" if eta else "ETA~--"; param_str=""
        ts=time.strftime("%H:%M:%S")
        print(f"[{ts}] {progress_bar(cur,tgt,start_temp)} {tag} {eta_str} | T={cur:.2f}°C{param_str}")
        if abs(cur-tgt)<=tol: print(f"[INFO] Target reached in {(now-start)/60:.1f}m. Waiting {wait_scaled}m …"); break
        time.sleep(sleep_s)
    time.sleep(wait_scaled*60); print("[INFO] Complete.")
    
    # Log run history
    heating=tgt>start_temp; final_tau=(tau_h_est if heating else tau_c_est)*FAST
    ts=time.strftime("%Y-%m-%d %H:%M:%S"); model="EKF" if em==2 else "EXP"; mode="heating" if heating else "cooling"
    try:
        with open("run_history.csv","a") as f:
            if f.tell()==0:
                f.write("Timestamp,Initial_Temp,Target_Temp,Tau_calc,Model,Mode\nYYYY-MM-DD HH:MM:SS,°C,°C,min,-,-\n")
            f.write(f"{ts},{start_temp:.2f},{tgt:.2f},{final_tau:.2f},{model},{mode}\n")
    except Exception as e: print(f"[WARN] History log failed: {e}")
    
    # Update tau if enabled (only from ambient, idx==0)
    if int(c.get('tau_override',0))==1 and cfg_obj['idx']==0:
        final_tau_unscaled=(tau_h_est if heating else tau_c_est)*FAST
        ts=time.strftime("%Y-%m-%d %H:%M:%S")
        key,info_key=("tau_heating","tau_heating_info") if heating else ("tau_cooling","tau_cooling_info")
        print(f"[INFO] Updating {key} to {final_tau_unscaled:.2f}m (learned from EKF)")
        c[key],c[info_key]=final_tau_unscaled,f"Updated {ts} | Start T={start_temp:.1f}°C"
    
    # Advance setpoint or write tau updates
    temps,idx=cfg_obj['temps'],cfg_obj['idx']
    if len(temps)>1 or int(c.get('tau_override',0))==1:
        ni=(idx+1)%len(temps) if len(temps)>1 else idx
        if len(temps)>1: print(f"[INFO] Advancing set index {idx}->{ni}")
        write_config(temps,ni,c)

if __name__ == "__main__":
    main()
