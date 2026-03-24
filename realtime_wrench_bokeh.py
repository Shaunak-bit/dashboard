import socket
import threading
import numpy as np
from time import time
from datetime import datetime
import csv
import os
import base64
import pathlib
import sys

from bokeh.models import (
    ColumnDataSource, HoverTool, Button, Div, Span,
    NumeralTickFormatter, BasicTicker  # BasicTicker for controlling tick spacing
)
from bokeh.plotting import figure, curdoc
from bokeh.layouts import column, row
from bokeh.models import TextInput

# =====================================================
# GLOBAL STATE
# =====================================================
paused = False

bias_enabled = False
bias_vector  = np.zeros(6)

FORCE_THRESHOLD = 60
counter         = 0
time_in_minutes = False  # Flag to track if we've switched to minutes

last_update_time = time()
last_data_time   = 0.0

_socket_thread_started = False

# CSV STATE
csv_file         = None
csv_writer       = None
recording_active = False

# ALARM STATE
alarm_active = False

ROLLOVER_SMALL = 20
ROLLOVER_FORCE = 20
ROLLOVER_FORCE_MINUTES = 20  # User wants 20 points in minutes mode too
current_rollover = 20  # Track current rollover value

# CRITICAL: Calculate appropriate time windows based on data rate
UPDATE_RATE_HZ = 50.0  # Data update frequency
SECONDS_PER_ROLLOVER_POINT = 1.0 / UPDATE_RATE_HZ  # 0.02 seconds per point at 50Hz

# MONITORING CONSTANTS
MONITOR_INTERVAL = 1000      # Check memory/integrity every 1000 updates
MAX_ALLOWED_POINTS = 100     # Maximum points before forcing cleanup (rollover * 5)

# Live values
Fx = Fy = Fz = Tx = Ty = Tz = 0.0

# =====================================================
# HELPER FUNCTIONS
# =====================================================
def get_display_time(count):
    """Convert counter to display time (seconds or minutes)"""
    if time_in_minutes:
        return count / 60.0
    return float(count)  # CHANGED: Ensure it's a float

def get_time_label():
    """Get the appropriate time label"""
    return "Time [min]" if time_in_minutes else "Time [s]"

def validate_data_source(source, expected_keys):
    """Validate that a data source has proper structure and consistent lengths."""
    try:
        if not hasattr(source, 'data') or source.data is None:
            return False
        
        # Check all expected keys exist
        for key in expected_keys:
            if key not in source.data:
                return False
        
        # Check all arrays have the same length
        lengths = [len(source.data[key]) for key in expected_keys]
        if len(set(lengths)) > 1:
            print(f"⚠️ Data length mismatch: {dict(zip(expected_keys, lengths))}")
            return False
        
        return True
    except Exception as e:
        print(f"❌ Validation error: {e}")
        return False

def repair_data_source(source, default_data):
    """Repair a corrupted data source by resetting it."""
    try:
        source.data = default_data.copy()
        print(f"✅ Repaired data source")
        return True
    except Exception as e:
        print(f"❌ Repair failed: {e}")
        return False

# =====================================================
# DATA CONVERSION HELPERS - FIXED VERSION
# =====================================================

def convert_sources_to_minutes():
    """Convert existing x/t values from seconds to minutes - FIXED to prevent graph disappearing."""
    global current_rollover
    
    print(f"🔄 Starting conversion to minutes at counter={counter}")
    
    # Calculate appropriate follow interval based on rollover
    # At 50Hz, 20 points = 0.4 seconds = 0.00667 minutes
    data_duration_seconds = ROLLOVER_FORCE_MINUTES * SECONDS_PER_ROLLOVER_POINT
    data_duration_minutes = data_duration_seconds / 60.0
    # Add 50% padding for better visibility
    follow_interval_minutes = data_duration_minutes * 1.5
    
    print(f"   Rollover: {ROLLOVER_FORCE_MINUTES} points")
    print(f"   Data duration: {data_duration_seconds:.2f} seconds = {data_duration_minutes:.4f} minutes")
    print(f"   Follow interval: {follow_interval_minutes:.4f} minutes")
    
    # Convert scatter plot sources - simple conversion without range manipulation
    for i, src in enumerate(sources):
        try:
            if len(src.data.get("x", [])) > 0:
                # Convert data to minutes
                src.data = {
                    "x": [x / 60.0 for x in src.data["x"]],
                    "y": list(src.data["y"]),
                    "size": list(src.data["size"]),
                    "color": list(src.data["color"])
                }
                
                # Set follow interval based on actual data duration
                figs[i].x_range.follow_interval = follow_interval_minutes
                
                print(f"✅ Converted scatter source {i} - {len(src.data['x'])} points")
                
        except Exception as e:
            print(f"❌ Error converting source {i} to minutes: {e}")
            src.data = dict(x=[], y=[], size=[], color=[])
    
    # Convert force magnitude source - CRITICAL FIX
    try:
        if len(force_mag_source.data.get("t", [])) > 0:
            old_t = list(force_mag_source.data["t"])
            old_fmag = list(force_mag_source.data["fmag"])
            
            print(f"   Force data before conversion: {len(old_t)} points")
            print(f"   Time range before: {min(old_t):.2f} to {max(old_t):.2f} seconds")
            
            # Convert to minutes
            new_t = [t / 60.0 for t in old_t]
            
            # Update the data source
            force_mag_source.data = {
                "t": new_t,
                "fmag": old_fmag
            }
            
            # Update rollover to minutes mode value
            current_rollover = ROLLOVER_FORCE_MINUTES
            
            # CRITICAL FIX: Set follow interval based on actual data duration
            # This ensures the visible window matches the amount of data
            force_fig.x_range.follow_interval = follow_interval_minutes
            
            print(f"✅ Converted force magnitude to minutes")
            print(f"   Force data after conversion: {len(new_t)} points")
            print(f"   Time range after: {min(new_t):.3f} to {max(new_t):.3f} minutes")
            print(f"   Rollover: {current_rollover} points")
            print(f"   Follow interval: {follow_interval_minutes:.4f} minutes")
            print(f"   Follow mode active - Bokeh will auto-adjust x_range")
            
    except Exception as e:
        print(f"❌ Error converting force magnitude to minutes: {e}")
        force_mag_source.data = dict(t=[], fmag=[])

# =====================================================
# SHARED VARIABLE + LOCK
# =====================================================
latest_data = None
data_lock   = threading.Lock()

# =====================================================
# LOGO CONFIGURATION
# =====================================================
if getattr(sys, 'frozen', False):
    script_dir = pathlib.Path(sys._MEIPASS)
else:
    script_dir = pathlib.Path(__file__).parent
logo_file  = None
for ext in ("png", "jpg", "jpeg", "gif", "svg"):
    matches = list(script_dir.rglob(f"*Bhabha_Atomic_Research_Centre_Logo*.{ext}"))
    if matches:
        logo_file = matches[0]
        break
if logo_file is None:
   imgs = list(script_dir.rglob("static/*Bhabha*"))
   logo_file = imgs[0] if imgs else None

if logo_file and logo_file.exists():
    raw  = logo_file.read_bytes()
    b64  = base64.b64encode(raw).decode("ascii")
    mime = "image/png"
    if logo_file.suffix.lower() in (".jpg", ".jpeg"): mime = "image/jpeg"
    elif logo_file.suffix.lower() == ".gif":          mime = "image/gif"
    elif logo_file.suffix.lower() == ".svg":          mime = "image/svg+xml"
    logo_html = (f'<img src="data:{mime};base64,{b64}" width="60" height="60" '
                 f'style="object-fit:contain;display:block;">')
else:
    logo_html = '<div style="width:60px;height:60px"></div>'

# =====================================================
# FOOTER LOGO CONFIGURATION
# =====================================================
footer_logo_file = None
for ext in ("png", "jpg", "jpeg", "gif", "svg"):
    matches = list(script_dir.rglob(f"*DRHR Logo_withoutbg*.{ext}"))
    if matches:
        footer_logo_file = matches[0]
        break

if footer_logo_file and footer_logo_file.exists():
    raw  = footer_logo_file.read_bytes()
    b64  = base64.b64encode(raw).decode("ascii")
    mime = "image/png"
    if footer_logo_file.suffix.lower() in (".jpg", ".jpeg"): mime = "image/jpeg"
    elif footer_logo_file.suffix.lower() == ".gif":          mime = "image/gif"
    elif footer_logo_file.suffix.lower() == ".svg":          mime = "image/svg+xml"
    footer_logo_html = (f'<img src="data:{mime};base64,{b64}" '
                        f'style="height:50px;width:auto;object-fit:contain;margin-left:15px;">')
else:
    footer_logo_html = ""

# =====================================================
# REUSABLE STYLE HELPERS
# =====================================================
def _make_style(color, bg):
    return {
        "font-size": "16px", "color": color, "font-weight": "600",
        "padding": "8px 15px", "margin-bottom": "4px",
        "border-left": f"4px solid {color}", "border-radius": "4px",
        "background-color": bg, "box-shadow": "0 1px 2px rgba(0,0,0,0.05)"
    }

RED_STYLE   = _make_style("#DC2626", "#FEF2F2")
GREEN_STYLE = _make_style("#16A34A", "#F0FDF4")
GREY_STYLE  = {
    "font-size": "15px", "color": "#4B5563", "font-weight": "500",
    "padding": "8px 15px", "margin-bottom": "4px",
    "border-left": "4px solid #9CA3AF", "border-radius": "4px",
    "background-color": "#F9FAFB", "box-shadow": "0 1px 2px rgba(0,0,0,0.05)"
}

# =====================================================
# HMI STATUS WIDGETS  (LEFT column)
# =====================================================
conn_status  = Div(text=" TCP: Disconnected", styles=RED_STYLE,   height=40)
force_status = Div(text=" Force: Normal",     styles=GREEN_STYLE, height=40)
rate_status  = Div(text="⏱ Update: -- ms",    styles=GREY_STYLE,  height=40)

# =====================================================
# ALARM WIDGETS  (RIGHT column — beside TCP/Force)
# ─────────────────────────────────────────────────────
# alarm_div + ack_button live in a separate right column
# that sits horizontally next to conn_status/force_status.
# Both are hidden until an alarm fires.
# =====================================================
alarm_div = Div(
    text="", visible=False,
    styles={
        "background-color": "#991B1B",
        "color": "white",
        "padding": "14px 18px",
        "font-size": "15px",
        "font-weight": "700",
        "border-radius": "6px",
        "text-align": "center",
        "box-shadow": "0 3px 8px rgba(0,0,0,0.25)",
        "line-height": "1.5",
        "min-width": "240px"
    }
)

ack_button = Button(
    label="✔ ACKNOWLEDGE ALARM",
    button_type="danger",
    width=240,
    visible=False
)

# =====================================================
# PAUSE BUTTON
# =====================================================
pause_button = Button(label="⏸ Pause", button_type="warning", width=120)

def acknowledge_alarm():
    global alarm_active, paused
    alarm_active = False;  paused = False
    alarm_div.visible  = False
    ack_button.visible = False
    pause_button.label       = "⏸ Pause"
    pause_button.button_type = "warning"

ack_button.on_click(acknowledge_alarm)

def toggle_pause():
    global paused
    if alarm_active:
        acknowledge_alarm(); return
    paused = not paused
    pause_button.label       = "▶ Resume" if paused else "⏸ Pause"
    pause_button.button_type = "success"  if paused else "warning"

pause_button.on_click(toggle_pause)

# =====================================================
# BIAS BUTTON
# =====================================================
bias_button = Button(label=" Set Sensor Bias", button_type="primary", width=150)

def trigger_bias():
    global bias_enabled, bias_vector, Fx, Fy, Fz, Tx, Ty, Tz
    if active_conn:
        try: active_conn.sendall(b"BIAS\n")
        except: pass
    if not bias_enabled:
        bias_vector  = np.array([Fx, Fy, Fz, Tx, Ty, Tz])
        bias_enabled = True
        bias_button.label       = "Bias OFF"
        bias_button.button_type = "danger"
        print(f"✅ Bias SET: {bias_vector}")
    else:
        bias_vector  = np.zeros(6);  bias_enabled = False
        bias_button.label       = "Set Bias"
        bias_button.button_type = "primary"
        print("✅ Bias CLEARED — raw sensor values restored")
    bias_source.stream(dict(t=[get_display_time(counter)]))

bias_button.on_click(trigger_bias)

# =====================================================
# ROLLOVER CONTROL
# =====================================================
rollover_label      = Div(text="<b>Rollover Points</b>",
                           styles={"font-size":"13px","color":"#4B5563"})
rollover_input      = TextInput(value=str(ROLLOVER_FORCE), width=110)
set_rollover_button = Button(label="Set", button_type="primary",
                             width=55, height=31)

def set_rollover_value():
    global ROLLOVER_FORCE, ROLLOVER_SMALL, ROLLOVER_FORCE_MINUTES
    try:
        value = int(rollover_input.value)
        if value >= 1:
            ROLLOVER_FORCE = value
            ROLLOVER_SMALL = value
            ROLLOVER_FORCE_MINUTES = value  # Same rollover for both modes
            print(f"✅ Rollover set to {ROLLOVER_FORCE} points for both modes")
        else:
            rollover_input.value = str(ROLLOVER_FORCE)
    except ValueError:
        rollover_input.value = str(ROLLOVER_FORCE)

set_rollover_button.on_click(set_rollover_value)

# =====================================================
# THRESHOLD CONTROL
# =====================================================
threshold_label_title = Div(text="<b>Force Threshold (N)</b>",
                             styles={"font-size":"13px","color":"#DC2626"})
threshold_input      = TextInput(value=str(FORCE_THRESHOLD), width=110)
set_threshold_button = Button(label="Set", button_type="danger",
                              width=55, height=31)

threshold_current_label = Div(
    text=f"🔴 Current Threshold: <b>{FORCE_THRESHOLD} N</b>",
    styles={
        "font-size": "13px", "color": "#DC2626", "font-weight": "500",
        "padding": "5px 10px 5px 5px", "border-left": "4px solid #DC2626",
        "border-radius": "4px", "background-color": "#FEF2F2"
    }
)

# threshold_span assigned after force_fig is created
threshold_span = None

def set_threshold_value():
    global FORCE_THRESHOLD
    try:
        value = float(threshold_input.value)
        if value > 0:
            FORCE_THRESHOLD = value
            threshold_span.location      = FORCE_THRESHOLD
            force_fig.y_range.end        = FORCE_THRESHOLD * 1.5
            threshold_current_label.text = (
                f"🔴 Current Threshold: <b>{FORCE_THRESHOLD:.1f} N</b>")
            print(f"✅ Force threshold set to {FORCE_THRESHOLD} N")
        else:
            threshold_input.value = str(FORCE_THRESHOLD)
    except ValueError:
        threshold_input.value = str(FORCE_THRESHOLD)

set_threshold_button.on_click(set_threshold_value)

# =====================================================
# TCP SERVER
# =====================================================
active_conn = None

def socket_server():
    global active_conn, latest_data
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    s.bind(("0.0.0.0", 5001));  s.listen(1)
    print("Waiting for C++ connection...")
    while True:
        conn, addr = s.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        active_conn = conn
        print("Connected from:", addr)
        buffer = ""
        try:
            while True:
                chunk = conn.recv(8192).decode()
                if not chunk: break
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    try:
                        values = list(map(float, line.split(",")))
                        if len(values) == 13:
                            with data_lock:
                                latest_data = values
                    except: pass
        except Exception as e:
            print(f"Connection error: {e}")
        finally:
            conn.close();  active_conn = None
            print("C++ client disconnected")

if not _socket_thread_started:
    threading.Thread(target=socket_server, daemon=True).start()
    _socket_thread_started = True

# =====================================================
# DATA SOURCES
# =====================================================
sources          = [ColumnDataSource(data=dict(x=[], y=[], size=[], color=[]))
                    for _ in range(6)]
force_mag_source = ColumnDataSource(data=dict(t=[], fmag=[]))
bias_source      = ColumnDataSource(data=dict(t=[]))

# =====================================================
# AXIS STYLE HELPER - UPDATED WITH BETTER TIME FORMATTING
# =====================================================
def style_axes(fig):
    two_dp = NumeralTickFormatter(format="0.00")
    # CHANGED: Use integer format for time in seconds, one decimal for minutes
    time_formatter = NumeralTickFormatter(format="0")  # Start with integers for seconds
    fig.yaxis.formatter = two_dp
    fig.xaxis.formatter = time_formatter
    fig.x_range.range_padding = 0.08  # Add padding on x-axis to avoid edge-clinging points
    for axis in (fig.yaxis, fig.xaxis):
        axis.axis_label_text_font_style  = "bold"
        axis.axis_label_text_font_size   = "13px"
        axis.major_label_text_font_style = "bold"
        axis.major_label_text_font_size  = "11px"
    
    # Add spacing between tick labels and axis line for better readability
    fig.xaxis.major_label_standoff = 8
    fig.yaxis.major_label_standoff = 8

# ADDED: Function to update time axis formatting when switching units
def update_time_axis_format(fig, in_minutes=False):
    """Update the time axis formatter when switching between seconds and minutes"""
    if in_minutes:
        # Calculate follow interval based on rollover
        data_duration_seconds = ROLLOVER_FORCE_MINUTES * SECONDS_PER_ROLLOVER_POINT
        data_duration_minutes = data_duration_seconds / 60.0
        follow_interval_minutes = data_duration_minutes * 1.5  # Add 50% padding
        
        # Use one decimal place for minutes (e.g., 22.1, 22.2, 22.3)
        fig.xaxis.formatter = NumeralTickFormatter(format="0.0")
        
        # Set follow interval based on actual data duration
        fig.x_range.follow_interval = follow_interval_minutes
        fig.x_range.range_padding = 0.1
        
        # Control tick density - fewer ticks for small windows
        if follow_interval_minutes < 0.1:  # Less than 6 seconds
            fig.xaxis.ticker = BasicTicker(desired_num_ticks=3, num_minor_ticks=2)
        else:
            fig.xaxis.ticker = BasicTicker(desired_num_ticks=5, num_minor_ticks=2)
        
    else:
        # Use integer format for seconds (e.g., 100, 200, 300)
        fig.xaxis.formatter = NumeralTickFormatter(format="0")
        # Show last 200 seconds
        fig.x_range.follow_interval = 200
        fig.x_range.range_padding = 0.08
        
        # Reset to default ticker for seconds mode
        fig.xaxis.ticker = BasicTicker(desired_num_ticks=8)

# =====================================================
# 2D SCATTER PLOTS
# =====================================================
titles = [
    "Tx Torque vs Time", "Ty Torque vs Time", "Tz Torque vs Time",
    "Fx Force vs Time",  "Fy Force vs Time",  "Fz Force vs Time",
]
axes = [
    ("Time [s]", "Tx [Nm]"), ("Time [s]", "Ty [Nm]"), ("Time [s]", "Tz [Nm]"),
    ("Time [s]", "Fx [N]"),  ("Time [s]", "Fy [N]"),  ("Time [s]", "Fz [N]"),
]
LEFT_MARGIN = 55

figs = [
    figure(
        title=titles[i], x_axis_label=axes[i][0], y_axis_label=axes[i][1],
        sizing_mode="stretch_both", toolbar_location="right", margin=(0,0,0,0)
    )
    for i in range(6)
]
for i, f in enumerate(figs):
    f.scatter('x', 'y', size='size', color='color', alpha=0.7, source=sources[i])
    f.add_tools(HoverTool(tooltips=[("Time","@x{0.00}"),("Value","@y{0.00}")]))
    f.min_border = 0;  f.min_border_left = LEFT_MARGIN
    f.min_border_right = 0;  f.min_border_top = 0;  f.min_border_bottom = 0
    f.toolbar.autohide = True
    f.x_range.follow = "end";  f.x_range.follow_interval = 200
    style_axes(f)

# =====================================================
# FORCE MAGNITUDE PLOT
# =====================================================
force_fig = figure(
    title="Resultant Force |F|",
    x_axis_label="Time [s]",
    y_axis_label="Force Magnitude [N]",
    sizing_mode="stretch_both",
    toolbar_location="right",
    margin=(0, 0, 0, 0)
)
force_fig.y_range.start = 0
force_fig.y_range.end   = FORCE_THRESHOLD * 1.5
force_fig.min_border = 0;  force_fig.min_border_left = LEFT_MARGIN
force_fig.min_border_right = 0;  force_fig.min_border_top = 0
force_fig.min_border_bottom = 0
force_fig.toolbar.autohide = True
force_fig.x_range.follow = "end";  force_fig.x_range.follow_interval = 200
style_axes(force_fig)

# Main force line
force_fig.line('t', 'fmag', source=force_mag_source,
               line_width=3, color='#2563EB')

# ── Bias Event: BLUE dashed vertical segments ─────────
force_fig.segment(
    x0='t', x1='t', y0=0, y1=FORCE_THRESHOLD * 1.5,
    source=bias_source,
    line_color="#2563EB",       # solid blue colour
    line_width=2,
    line_dash="dashed",
    legend_label="Bias Event"
)

# ── Threshold: RED dashed Span + legend entry ──────────
threshold_span = Span(
    location=FORCE_THRESHOLD, dimension='width',
    line_color="#DC2626", line_dash="dashed", line_width=2
)
force_fig.add_layout(threshold_span)

# Dummy invisible segment just so "Threshold" appears
# in the legend with a red dashed style
_thresh_leg_src = ColumnDataSource(data=dict(t=[0]))
force_fig.segment(
    x0='t', x1='t', y0=FORCE_THRESHOLD, y1=FORCE_THRESHOLD,
    source=_thresh_leg_src,
    line_color="#DC2626", line_width=2, line_dash="dashed",
    legend_label="Threshold"
)

# Style legend
force_fig.legend.label_text_font_size  = "11px"
force_fig.legend.label_text_font_style = "bold"
force_fig.legend.background_fill_alpha = 0.85
force_fig.legend.location             = "top_right"
force_fig.legend.click_policy         = "hide"

# =====================================================
# UPDATE LOOP
# =====================================================
def update():
    global counter, last_update_time, last_data_time
    global csv_file, csv_writer, recording_active
    global alarm_active, paused
    global Fx, Fy, Fz, Tx, Ty, Tz
    global latest_data, time_in_minutes, current_rollover

    now = time()

    tcp_connected      = (now - last_data_time) < 0.5
    conn_status.text   = " TCP: Connected"   if tcp_connected else " TCP: Disconnected"
    conn_status.styles = GREEN_STYLE          if tcp_connected else RED_STYLE

    if paused:
        return

    with data_lock:
        if latest_data is None:
            return
        packet      = latest_data
        latest_data = None

    X, Y, Z, A, B, C, Fx, Fy, Fz, Tx, Ty, Tz, z_travel = packet
    last_data_time = now

    wrench = np.array([Fx, Fy, Fz, Tx, Ty, Tz])
    if bias_enabled:
        wrench = wrench - bias_vector
    Fx, Fy, Fz, Tx, Ty, Tz = wrench

    force  = np.array([Fx, Fy, Fz])
    torque = np.array([Tx, Ty, Tz])
    fmag   = np.linalg.norm(force)

    # CHANGED: Better time axis switching with formatting update
    if counter >= 1000 and not time_in_minutes:
        time_in_minutes = True
        print(f"🔄 Starting conversion to minutes at counter={counter}")
        print(f"   Force data before conversion: {len(force_mag_source.data.get('t', []))} points")
        
        # Convert all previously plotted points to minute scale before next point.
        convert_sources_to_minutes()
        
        print(f"   Force data after conversion: {len(force_mag_source.data.get('t', []))} points")
        print(f"   Current rollover: {current_rollover}")
        
        # Update all axis labels AND formatters
        for fig in figs:
            fig.xaxis.axis_label = get_time_label()
            update_time_axis_format(fig, in_minutes=True)  # ADDED
        force_fig.xaxis.axis_label = get_time_label()
        update_time_axis_format(force_fig, in_minutes=True)  # ADDED
        print(f"✅ Time axis switched to minutes at counter={counter}")

    # Alarm — alarm_div is in the RIGHT status column
    if fmag > FORCE_THRESHOLD and not alarm_active:
        alarm_active       = True
        paused             = True
        alarm_div.text     = (
            f"⚠ FORCE LIMIT EXCEEDED!<br>"
            f"|F| = {fmag:.2f} N  |  Threshold = {FORCE_THRESHOLD:.1f} N"
        )
        alarm_div.visible  = True
        ack_button.visible = True
        pause_button.label       = "▶ Resume"
        pause_button.button_type = "success"

    if not recording_active:
        os.makedirs("recordings", exist_ok=True)
        filename   = datetime.now().strftime("recordings/session_%Y%m%d_%H%M%S.csv")
        csv_file   = open(filename, "w", newline="", buffering=8192)
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["timestamp","Fx","Fy","Fz",
                              "Tx","Ty","Tz","fmag","threshold"])
        recording_active = True

    csv_writer.writerow([datetime.now().isoformat(),
                         Fx, Fy, Fz, Tx, Ty, Tz, fmag, FORCE_THRESHOLD])
    if counter % 100 == 0:
        csv_file.flush()

    rate_status.text   = f"⏱ Update: {(now - last_update_time)*1000:.0f} ms"
    rate_status.styles = GREY_STYLE
    last_update_time   = now
    
    # Add health monitoring info periodically
    if counter % MONITOR_INTERVAL == 0:
        health_info = (
            f"⏱ Update: {(now - last_update_time)*1000:.0f} ms | "
            f"📊 Points: {len(force_mag_source.data.get('t', []))} | "
            f"✅ Health: OK"
        )
        rate_status.text = health_info

    if alarm_active:
        force_status.text   = f" Force: HIGH ({fmag:.2f} N)"
        force_status.styles = RED_STYLE
    else:
        force_status.text   = f" Force: Normal ({fmag:.2f} N)"
        force_status.styles = GREEN_STYLE

    color_torque = ['green' if v >= 0 else 'red' for v in torque]
    color_force  = ['green' if v >= 0 else 'red' for v in force]
    values       = [Tx, Ty, Tz, Fx, Fy, Fz]

    # Get the display time (either in seconds or minutes)
    display_time = get_display_time(counter)

    # ═══════════════════════════════════════════════════════════════
    # MEMORY MONITORING - Safety net to catch rollover failures
    # Check for memory bloat and force cleanup if needed
    # ═══════════════════════════════════════════════════════════════
    if counter % MONITOR_INTERVAL == 0:
        # Check force magnitude source
        max_allowed = current_rollover * 5  # Dynamic based on current mode
        actual_points = len(force_mag_source.data.get('t', []))
        if actual_points > max_allowed:
            print(f"⚠️ Memory leak detected in force_mag: {actual_points} points (max {max_allowed})")
            # Force cleanup - keep only last current_rollover points
            force_mag_source.data = dict(
                t=list(force_mag_source.data['t'][-current_rollover:]),
                fmag=list(force_mag_source.data['fmag'][-current_rollover:])
            )
            print(f"✅ Forced cleanup - reduced to {current_rollover} points")
        
        # Check scatter sources
        for i, src in enumerate(sources):
            actual_points = len(src.data.get('x', []))
            if actual_points > MAX_ALLOWED_POINTS:
                print(f"⚠️ Memory leak in source {i}: {actual_points} points")
                src.data = dict(
                    x=list(src.data['x'][-ROLLOVER_SMALL:]),
                    y=list(src.data['y'][-ROLLOVER_SMALL:]),
                    size=list(src.data['size'][-ROLLOVER_SMALL:]),
                    color=list(src.data['color'][-ROLLOVER_SMALL:])
                )

    # ═══════════════════════════════════════════════════════════════
    # DATA VALIDATION - Detect and repair corruption
    # Validate data sources before streaming
    # ═══════════════════════════════════════════════════════════════
    # Validate force magnitude source
    if not validate_data_source(force_mag_source, ['t', 'fmag']):
        print("⚠️ Force magnitude source corrupted - repairing...")
        repair_data_source(force_mag_source, {'t': [], 'fmag': []})
    
    # Validate scatter sources
    for i, src in enumerate(sources):
        if not validate_data_source(src, ['x', 'y', 'size', 'color']):
            print(f"⚠️ Source {i} corrupted - repairing...")
            repair_data_source(src, {'x': [], 'y': [], 'size': [], 'color': []})

    # ═══════════════════════════════════════════════════════════════
    # ERROR RECOVERY - Wrap all streaming operations in try-catch
    # ═══════════════════════════════════════════════════════════════
    
    # MARKER SIZE VARIATION: Most recent 20 points larger (size=10), older points smaller (size=6)
    for i in range(6):
        col = color_torque[i] if i < 3 else color_force[i - 3]
        
        try:
            # Stream new point with large size
            sources[i].stream(
                dict(x=[display_time], y=[values[i]], size=[10], color=[col]),
                rollover=ROLLOVER_SMALL
            )
            
            # Update sizes: keep last 20 at size 10, rest at size 6
            data_len = len(sources[i].data['size'])
            if data_len > 20:
                new_sizes = [6] * (data_len - 20) + [10] * 20
                sources[i].data = dict(sources[i].data, size=new_sizes)
                
        except Exception as e:
            print(f"❌ Streaming error on source {i}: {e}")
            # Recovery: rebuild source with just this point
            try:
                sources[i].data = dict(
                    x=[display_time], 
                    y=[values[i]], 
                    size=[10], 
                    color=[col]
                )
                print(f"✅ Recovered source {i}")
            except Exception as e2:
                print(f"❌ Recovery failed for source {i}: {e2}")
    
    # CRITICAL FIX: Use dynamic rollover based on time mode
    effective_rollover = current_rollover if time_in_minutes else ROLLOVER_FORCE
    
    # Stream force magnitude with error recovery
    try:
        force_mag_source.stream(
            dict(t=[display_time], fmag=[fmag]),
            rollover=effective_rollover  # FIXED: Use appropriate rollover
        )
    except Exception as e:
        print(f"❌ Force magnitude streaming error: {e}")
        # Recovery: rebuild with just this point
        try:
            force_mag_source.data = dict(t=[display_time], fmag=[fmag])
            print("✅ Recovered force magnitude source")
        except Exception as e2:
            print(f"❌ Force magnitude recovery failed: {e2}")
    
    counter += 1


curdoc().add_periodic_callback(update, 20)

# =====================================================
# LAYOUT
# =====================================================
row1       = row(figs[0], figs[1], figs[2],
                 sizing_mode="stretch_both", spacing=0, align='start')
row2       = row(figs[3], figs[4], figs[5],
                 sizing_mode="stretch_both", spacing=0, align='start')
plots_grid = column(row1, row2, sizing_mode="stretch_both", spacing=0)

# ── All controls in single row ──────────────────────────
rollover_label_inline = Div(text="<b>Rollover Points:</b>",
                            styles={"font-size":"13px","color":"#4B5563","padding":"8px 5px 0 0"})

# Main controls row (Pause, Bias, Rollover)
controls_row = row(pause_button, bias_button,
                   rollover_label_inline, rollover_input, set_rollover_button,
                   spacing=10, align='end', margin=(0,0,0,0))

# Threshold row (Current Threshold label + input controls)
threshold_row = row(threshold_current_label, threshold_input, set_threshold_button,
                    spacing=10, align='center', margin=(0,0,0,0))

# ── LEFT column: TCP / Force / Rate / threshold row / controls ──────
left_status_col = column(
    conn_status,
    force_status,
    rate_status,
    threshold_row,
    controls_row,
    spacing=3,
    sizing_mode="stretch_width",
    margin=(0,0,0,0)
)

# ── RIGHT column: alarm banner + ack button ───────────
# This sits BESIDE the left column at the same height
# as TCP/Force status.
right_alarm_col = column(
    alarm_div,
    ack_button,
    spacing=8,
    width=270
)

# ── Combined status band: left indicators | right alarm ───────────────
status_band = row(
    left_status_col,
    right_alarm_col,
    sizing_mode="stretch_width",
    spacing=10,
    align="start",
    margin=(0,0,0,0)
)

left_column  = column(status_band, force_fig,
                       sizing_mode="stretch_both", spacing=5, margin=(0,0,0,0))
main_content = row(left_column, plots_grid,
                   sizing_mode='stretch_both', spacing=10, align='start', margin=(0,0,0,0))

header_div = Div(
    text=f"""
    <div style="
        width:100vw; position:relative; left:50%; transform:translateX(-50%);
        box-sizing:border-box; display:flex; align-items:center;
        justify-content:center; padding:12px 20px;
        background-color:#F3F4F6; border-bottom:2px solid #E5E7EB;
        font-size:18px; font-weight:700; color:#1F2937;
    ">
        <div style="position:absolute;left:20px;top:50%;transform:translateY(-50%);">{logo_html}</div>
        <div>Visual Wrench Guided Robot Navigation</div>
    </div>
    """,
    sizing_mode="stretch_width"
)

footer_div = Div(
    text=f"""
    <div style="
        width:100vw; position:relative; left:50%; transform:translateX(-50%);
        box-sizing:border-box; display:flex; align-items:center;
        justify-content:center; padding:16px 0;
        font-size:18px; font-weight:600; color:#1F2937;
        border-top:2px solid #E5E7EB; background-color:#F3F4F6;
        overflow:visible; height:56px;
    ">
        <div style="display:flex; align-items:center;">
            <span>Developed by Division of Remote Handling &amp; Robotics</span>
            {footer_logo_html}
        </div>
    </div>
    """,
    sizing_mode="stretch_width"
)

main_layout = column(
    header_div, main_content,
    row(footer_div, sizing_mode="stretch_width", spacing=0),
    sizing_mode="stretch_both", spacing=0
)

curdoc().add_root(main_layout)

# =====================================================
# CLEANUP
# =====================================================
def cleanup():
    global csv_file, recording_active
    if recording_active and csv_file:
        csv_file.close()
        recording_active = False

curdoc().on_session_destroyed(lambda _: cleanup())