import requests, yaml, time, sys, math
try: import numpy as np
except: np = None

# Production controller for Memmert IPP30 temperature chamber
BASE_URL="http://192.168.96.21/atmoweb"; CFG="IPP30_TEMP_CNTRL.yaml"
TIMEOUT_S=10; RETRIES=3; RETRY_DELAY_S=2
TARGET_THRESHOLD=0.1  # °C threshold for "target reached"

class ConfigError(Exception): pass
class DeviceError(Exception): pass

def cfg():
    """Load config: returns (target, wait_min, tolerance, config_dict)"""
    try:
        with open(CFG,"r",encoding="utf-8") as f:
            c=yaml.safe_load(f) or {}
    except Exception as e:
        raise ConfigError(f"Failed to load {CFG}: {e}")
    
    wait_m=int(c.get("wait_time",0)); tol=float(c.get("tolerance",0.5))
    # Ensure tau_info keys exist for persistence
    for k in ['tau_heating_info','tau_cooling_info']:
        if k not in c: c[k]=''
    
    if "target_temperatures" in c:
        temps=c["target_temperatures"]
        if not temps or not isinstance(temps,list):
            raise ConfigError("target_temperatures must be non-empty list")
        idx=int(c.get("current_set_index",0))
        if not(0<=idx<len(temps)):
            raise ConfigError(f"current_set_index {idx} out of range [0,{len(temps)-1}]")
        return float(temps[idx]),wait_m,tol,{"temps":temps,"idx":idx,"c":c}
    
    if "target_temperature" not in c:
        raise ConfigError("Missing both target_temperatures and target_temperature")
    return float(c["target_temperature"]),wait_m,tol,{"temps":[c["target_temperature"]],"idx":0,"c":c}

def http_get(url):
    """HTTP GET with retry logic"""
    for i in range(1,RETRIES+1):
        try: return requests.get(url,timeout=TIMEOUT_S)
        except (requests.exceptions.Timeout,requests.exceptions.ConnectionError) as e:
            if i<RETRIES: print(f"[WARN] Retry {i}/{RETRIES}"); time.sleep(RETRY_DELAY_S)
            else: raise DeviceError(f"Device unreachable after {RETRIES} retries")
        except requests.exceptions.RequestException as e:
            raise DeviceError(f"HTTP request failed: {e}")

def get_state():
    """Returns (current_temp, range_dict)"""
    r=http_get(f"{BASE_URL}?Temp1Read=&TempSet_Range=")
    if r.status_code!=200:
        raise DeviceError(f"HTTP {r.status_code}")
    try:
        d=r.json()
        cur=float(d["Temp1Read"])
        rng={"min":float(d["TempSet_Range"]["min"]),"max":float(d["TempSet_Range"]["max"])}
        return cur,rng
    except (KeyError,ValueError,TypeError) as e:
        raise DeviceError(f"Invalid device response: {e}")

def set_target(temp):
    """Set target temperature"""
    r=http_get(f"{BASE_URL}?TempSet={temp}")
    if r.status_code!=200:
        raise DeviceError(f"Failed to set target: HTTP {r.status_code}")

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
        K_lim=np.array([K[0],np.clip(K[1],-0.5,0.5)])  # Limit tau gain
        x=x_pred+K_lim*(Tm-H@x_pred); P=P_pred-np.outer(K_lim,K_lim)*(H@P_pred@H+R)
        P=0.5*(P+P.T)  # Enforce symmetry
        P[P<1e-6]=1e-6  # Prevent negative eigenvalues
    tau=max(float(x[1]),1e-3); err=abs(cur-Tinf)
    if err<0.1: return 0.0,{"tau":tau}
    return max(0.0,-tau*np.log(0.1/err)),{"tau":tau}

def estimate_eta_exp(readings,target,tau_h,tau_c,tol):
    """Exponential model with fixed tau from config (no fitting)"""
    if not readings: return None,{}
    w=readings[-10:]; T0,cur=w[0][1],w[-1][1]
    heating=target>cur; Tinf=float(target)
    tau=float(tau_h if heating else tau_c)
    err=abs(cur-Tinf)
    if err<0.1: return 0.0,{"tau":tau}
    return max(0.0,-tau*math.log(0.1/err)),{"tau":tau}

def write_config(temps,idx,c):
    """Write config YAML with all sections"""
    lines=["# IPP30_TEMP_CNTRL.yaml\n# Configuration for Memmert IPP30 temperature control\n",
           "target_temperatures:  # Temperature sequence"]
    for i,t in enumerate(temps): lines.append(f"  - {float(t)}" + ("  # <-- current SetTemp" if i==idx else ""))
    lines.extend([f"current_set_index: {idx}  # Active setpoint (0-based)",
                  f"wait_time: {int(c.get('wait_time',0))}  # Minutes to wait after reaching target",
                  f"tolerance: {float(c.get('tolerance',0.5))}  # Temperature tolerance (°C)",
                  f"eta_model: {int(c.get('eta_model',1))}  # 1=Exponential, 2=EKF",
                  f"tau_override: {int(c.get('tau_override',0))}  # 1=update tau with EKF, 0=keep user values"])
    for mode,key,info_key in [("heating","tau_heating","tau_heating_info"),("cooling","tau_cooling","tau_cooling_info")]:
        tau,info=float(c.get(key,10.0)),c.get(info_key,'')
        lines.append(f"{key}: {tau}  # {mode.capitalize()} time constant (minutes)")
        if info: lines.append(f'{info_key}: "{info}"')
    lines.append(f"dt_minutes: {float(c.get('dt_minutes',1.0))}  # Sampling interval (minutes)")
    try:
        with open(CFG,"w",encoding="utf-8") as f:
            f.write("\n".join(lines)+"\n")
    except Exception as e:
        print(f"[WARN] Config write failed: {e}")

def log_run(start_temp,tgt,final_tau,em,heating):
    """Log completed run to CSV history"""
    ts=time.strftime("%Y-%m-%d %H:%M:%S")
    model="EKF" if em==2 else "EXP"
    mode="heating" if heating else "cooling"
    try:
        with open("run_history.csv","a") as f:
            if f.tell()==0:
                f.write("Timestamp,Initial_Temp,Target_Temp,Tau_calc,Model,Mode\nYYYY-MM-DD HH:MM:SS,°C,°C,min,-,-\n")
            f.write(f"{ts},{start_temp:.2f},{tgt:.2f},{final_tau:.2f},{model},{mode}\n")
    except Exception as e:
        print(f"[WARN] History log failed: {e}")

def maybe_update_tau(c,cfg_obj,heating,tau_h_est,tau_c_est,start_temp):
    """Update tau in config if tau_override enabled and starting from ambient"""
    if int(c.get('tau_override',0))==1 and cfg_obj['idx']==0:
        final_tau=tau_h_est if heating else tau_c_est
        ts=time.strftime("%Y-%m-%d %H:%M:%S")
        key,info_key=("tau_heating","tau_heating_info") if heating else ("tau_cooling","tau_cooling_info")
        print(f"[INFO] Updating {key} to {final_tau:.2f}m (learned from EKF)")
        c[key],c[info_key]=final_tau,f"Updated {ts} | Start T={start_temp:.1f}°C"

def run_single_setpoint(tgt,wait_m,tol,cfg_obj):
    """Execute control loop for one setpoint"""
    c=cfg_obj['c']
    cur,rng=get_state(); mn,mx=rng['min'],rng['max']
    print(f"[INFO] Target {tgt}°C | Range {mn}–{mx}°C | Current {cur:.2f}°C | Tol ±{tol}°C")
    if not(mn<=tgt<=mx):
        raise ConfigError(f"Target {tgt}°C outside valid range [{mn},{mx}]")
    
    set_target(tgt)
    dt_min=float(c.get('dt_minutes',1.0))
    tau_h,tau_c=float(c.get('tau_heating',10.0)),float(c.get('tau_cooling',10.0))
    sleep_s=max(5,dt_min*60.0); start_temp=cur
    em=int(c.get('eta_model',1))
    
    if em==2: print("[INFO] ETA Model: Extended Kalman Filter (EKF) | T(t)=T∞+(T₀-T∞)e^(-t/τ)")
    else: print(f"[INFO] ETA Model: Exponential | T(t)=T∞+(T₀-T∞)e^(-t/τ), τ={(tau_h if tgt>start_temp else tau_c):.2f}m")
    print(f"[INFO] Monitoring with {dt_min:.2f}m updates …" if dt_min>=1.0 else f"[INFO] Monitoring with {int(sleep_s)}s updates …")
    
    readings=[]; start=time.time(); tau_h_est,tau_c_est=tau_h,tau_c
    while True:
        cur,_=get_state(); now=time.time(); readings.append((now,cur))
        if em==2:
            eta,ex=estimate_eta_ekf(readings,tgt,tau_h_est,tau_c_est,dt_min); tag='[EKF]'
            tau_show=ex.get('tau',tau_h if tgt>start_temp else tau_c)
            if tau_show>0.1:
                if tgt>start_temp: tau_h_est=tau_show
                else: tau_c_est=tau_show
            eta_str=f"ETA~{eta:.1f}m" if eta else "ETA~--"; param_str=f" τ={tau_show:.2f}m"
        else:
            eta,ex=estimate_eta_exp(readings,tgt,tau_h,tau_c,tol); tag='[EXP]'
            eta_str=f"ETA~{eta:.1f}m" if eta else "ETA~--"; param_str=""
        print(f"[INFO] {progress_bar(cur,tgt,start_temp)} {tag} {eta_str} | T={cur:.2f}°C{param_str}")
        if abs(cur-tgt)<=tol:
            print(f"[INFO] Target reached in {(now-start)/60:.1f}m. Waiting {wait_m}m …")
            break
        time.sleep(sleep_s)
    
    time.sleep(wait_m*60); print("[INFO] Complete.")
    
    # Log and update
    heating=tgt>start_temp; final_tau=tau_h_est if heating else tau_c_est
    log_run(start_temp,tgt,final_tau,em,heating)
    maybe_update_tau(c,cfg_obj,heating,tau_h_est,tau_c_est,start_temp)
    
    # Advance setpoint if needed
    temps,idx=cfg_obj['temps'],cfg_obj['idx']
    if len(temps)>1 or int(c.get('tau_override',0))==1:
        ni=(idx+1)%len(temps) if len(temps)>1 else idx
        if len(temps)>1: print(f"[INFO] Advancing set index {idx}->{ni}")
        write_config(temps,ni,c)

def main():
    try:
        tgt,wait_m,tol,cfg_obj=cfg()
        run_single_setpoint(tgt,wait_m,tol,cfg_obj)
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user. Shutting down cleanly.")
        sys.exit(130)
    except (ConfigError,DeviceError) as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
