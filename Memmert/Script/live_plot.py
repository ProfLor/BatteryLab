import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import datetime

# Path to the latest log file
SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "log-files")

# Helper to find the latest log file
def get_latest_logfile():
    try:
        files = [f for f in os.listdir(LOG_DIR) if f.endswith('.csv')]
    except Exception as e:
        print(f"[ERROR] Could not list log directory: {e}")
        raise FileNotFoundError(f"Log directory not found: {LOG_DIR}")
    if not files:
        print(f"[ERROR] No log files found in {LOG_DIR}")
        raise FileNotFoundError("No log files found.")
    file_times = [(f, os.path.getmtime(os.path.join(LOG_DIR, f))) for f in files]
    file_times.sort(key=lambda x: x[1], reverse=True)
    latest_file = file_times[0][0]
    latest_path = os.path.join(LOG_DIR, latest_file)
    print(f"[DEBUG] Using latest log file: {latest_path}")
    return latest_path

# Parse log file for live data
def parse_logfile(logfile):
    times, temps, timestamps = [], [], []
    tau_mins, tinfs, t0s = [], [], []
    with open(logfile, 'r', encoding='utf-8') as f:
        for line in f:
            # Skip metadata, header, units, and empty lines
            if (line.startswith('#') or line.strip() == '' or
                line.startswith('Timestamp') or line.startswith('hh:mm:ss')):
                continue
            parts = line.strip().split(',')
            # Accept lines with at least 6 columns (old format) or 7+ (new format with T0)
            if len(parts) < 6:
                continue
            t_str, elapsed, temp, eta_min, tau_min, tinf = parts[:6]
            t0_val = parts[6] if len(parts) >= 7 else ''
            try:
                elapsed_f = float(elapsed)
                temp_f = float(temp)
                tau_f = float(tau_min) if tau_min != '' else np.nan
                tinf_f = float(tinf) if tinf != '' else np.nan
                t0_f = float(t0_val) if t0_val != '' else np.nan
                times.append(elapsed_f)
                temps.append(temp_f)
                timestamps.append(t_str)
                tau_mins.append(tau_f)
                tinfs.append(tinf_f)
                t0s.append(t0_f)
            except Exception:
                continue
    return np.array(times), np.array(temps), timestamps, np.array(tau_mins), np.array(tinfs), np.array(t0s)

def live_plot():
    fig, ax = plt.subplots(figsize=(10, 5))
    plt.style.use('ggplot')

    import matplotlib.dates as mdates

    def animate(frame):
        logfile = get_latest_logfile()
        log_title = os.path.basename(logfile)
        log_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(logfile))
        print(f"[INFO] Plotting from log file: {logfile} | mtime: {log_mtime}")
        ax.clear()
        times, temps, timestamps, tau_mins, tinfs, t0s = parse_logfile(logfile)
        if len(times) < 2:
            ax.set_title(f'No data in {log_title}')
            ax.legend(loc='upper right', frameon=True)
            return
        today = datetime.date.today().strftime('%Y-%m-%d')
        real_times_fmt = [mdates.datestr2num(f'{today} {ts}') for ts in timestamps]

        # Use Tau_min and Tinf from log file for extrapolation
        horizon = 3600
        dt = 10
        N_FADE = 8
        N_MAX = 20
        fade_curves = []
        for i in reversed(range(len(times))):
            tau_i = tau_mins[i] if not np.isnan(tau_mins[i]) else None
            Tinf_i = tinfs[i] if not np.isnan(tinfs[i]) else temps[i]
            T_current = temps[i]  # Start prediction from current temperature
            t_current = times[i]
            if tau_i and tau_i > 1e-3:
                # Predict forward from current temperature using fitted tau and Tinf
                t_ex = np.arange(t_current, t_current + horizon, dt)
                T_ex = Tinf_i + (T_current - Tinf_i) * np.exp(-(t_ex - t_current) / (tau_i * 60.0))
                if len(t_ex) > 0:
                    current_ts = datetime.datetime.strptime(f'{today} {timestamps[i]}', "%Y-%m-%d %H:%M:%S")
                    extrap_times = [current_ts + datetime.timedelta(seconds=float(tt - t_current)) for tt in t_ex]
                    extrap_times_fmt = [mdates.date2num(et) for et in extrap_times]
                    fade_curves.append((extrap_times_fmt, T_ex, tau_i, Tinf_i, T_current))
                    if len(fade_curves) >= N_MAX:
                        break

        # --- Plot layering: oldest to newest, so newest appears on top ---
        labels_used = set()
        n_fade = len(fade_curves)
        # fade_curves[0] is most recent, fade_curves[-1] is oldest
        # Plot from index n-1 (oldest) down to 0 (newest) so newest draws on top
        for idx in reversed(range(n_fade)):
            t, y, tau_j, Tinf_j, T_start = fade_curves[idx]
            # idx=0 is most recent (should be black = fade 0.0)
            # idx=1 is 1 step older (should be fade 0.05 = 5% gray)
            # Increase by 5% per step for more visible gradient
            fade = min(1.0, idx * 0.05)
            color = (fade, fade, fade)
            # Use zorder to ensure proper layering
            zorder_val = n_fade - idx
            if idx == 0:
                # Most recent curve: solid black with labels
                ax.plot(t, y, color='black', linewidth=2, zorder=zorder_val, label='Prediction')
                labels_used.add('Prediction')
                ax.axhline(Tinf_j, color='red', linestyle='--', linewidth=1.5, zorder=zorder_val+1, label='T∞')
                labels_used.add('T∞')
                # Add vertical line at estimated finish time using both convergence criteria
                if len(times) > 0:
                    tolerance = 0.5  # Match the tolerance from config
                    # Criterion 1: When temperature reaches within tolerance
                    # eta = -tau * ln(tolerance / |T_start - Tinf|)
                    err = abs(T_start - Tinf_j)
                    if err > tolerance:
                        # tau_j is in minutes, convert to seconds
                        eta_temp_seconds = -tau_j * 60.0 * np.log(tolerance / err)
                    else:
                        eta_temp_seconds = 0.0
                    
                    # Criterion 2: Minimum 5τ settling time (99.3%)
                    eta_time_seconds = 5 * tau_j * 60.0
                    
                    # Finish time is the MAXIMUM of both criteria
                    eta_seconds = max(eta_temp_seconds, eta_time_seconds)
                    
                    # Convert to matplotlib date offset
                    finish_time = t[0] + eta_seconds / 86400.0
                    ax.axvline(finish_time, color='#ff8800', linestyle='--', linewidth=1.5, zorder=zorder_val+1, label='Est. Finish')
                    labels_used.add('Est. Finish')
            else:
                # Older curves: faded with gray-tinted reference lines
                ax.plot(t, y, color=color, linewidth=1, zorder=zorder_val, label='_nolegend_')
                
                # Faded T∞ line (red to gray)
                red_fade = (fade + (1-fade)*1.0, fade + (1-fade)*0.0, fade + (1-fade)*0.0)
                ax.axhline(Tinf_j, color=red_fade, linestyle='--', linewidth=1.0, alpha=0.5, zorder=zorder_val+1, label='_nolegend_')
                
                # Faded Est. Finish line (orange to gray) using both convergence criteria
                tolerance = 0.5
                err = abs(T_start - Tinf_j)
                if err > tolerance:
                    eta_temp_seconds = -tau_j * 60.0 * np.log(tolerance / err)
                else:
                    eta_temp_seconds = 0.0
                eta_time_seconds = 5 * tau_j * 60.0
                eta_seconds = max(eta_temp_seconds, eta_time_seconds)
                finish_time = t[0] + eta_seconds / 86400.0
                orange_fade = (fade + (1-fade)*1.0, fade + (1-fade)*0.53, fade + (1-fade)*0.0)
                ax.axvline(finish_time, color=orange_fade, linestyle='--', linewidth=1.0, alpha=0.5, zorder=zorder_val+1, label='_nolegend_')

        # --- Plot layering: prediction lines first, then measured points on top ---

        # Target line (if available)
        target = None
        try:
            with open(logfile, 'r', encoding='utf-8') as f:
                for line in f:
                    if 'Target Temperature' in line:
                        target = float(line.split(':')[-1].strip())
                        break
        except Exception:
            pass
        if target is not None and 'Target' not in labels_used:
            ax.axhline(target, color='#22bb22', linestyle='--', linewidth=1.5, zorder=4, label='Target')
            labels_used.add('Target')

        # Always plot measured points last, above all lines
        ax.plot(real_times_fmt, temps, 'o-', color='#2222aa', label='Measured', markersize=4, zorder=10)

        # Labels and legend
        ax.set_xlabel('Time / hh:mm')
        ax.set_ylabel('Temperature / °C')
        ax.set_title(f'Live Temperature & Rolling Window Prediction\nFile: {log_title}\nmtime: {log_mtime}')
        ax.legend(loc='upper right', frameon=True)
        ax.grid(True, color='#cccccc', alpha=0.3)
        if len(real_times_fmt) > 0:
            ax.set_xlim(left=real_times_fmt[0])
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ani = FuncAnimation(fig, animate, interval=3000, cache_frame_data=False)
    plt.tight_layout()
    plt.show()

if __name__ == '__main__':
    live_plot()
