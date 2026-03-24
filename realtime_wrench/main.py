import socket
import threading
from queue import Queue
import numpy as np
from time import time
from datetime import datetime
import csv
import os

from bokeh.models import (
    ColumnDataSource, HoverTool, Button, Div,
    Span, LinearColorMapper, ColorBar
)
from bokeh.plotting import figure, curdoc
from bokeh.layouts import gridplot, column, row
from bokeh.transform import linear_cmap

# ✅ Screenshot export imports
from bokeh.io.export import export_png
from selenium import webdriver
from selenium.webdriver.firefox.options import Options

# =====================================================
# GLOBAL STATE
# =====================================================
data_queue = Queue()
paused = False

FORCE_THRESHOLD = 60.0
counter = 0

last_update_time = time()
last_data_time = 0.0

_socket_thread_started = False

# CSV STATE
csv_file = None
csv_writer = None
recording_active = False

# 🚨 ALARM STATE
alarm_active = False

# =====================================================
# LOGO CONFIGURATION
# =====================================================
# Path to BARC logo - update this path as needed
LOGO_PATH = "Bhabha_Atomic_Research_Centre_Logo.png"

# Check if logo exists, otherwise use placeholder
# =====================================================
# CORNER LOGOS (STATIC FOLDER VERSION - WORKING)
# =====================================================

logo_html = """
<img src="/static/Bhabha_Atomic_Research_Centre_Logo.png"
     width="60"
     height="60"
     style="object-fit: contain; display:block;">
"""

logo_top_left = Div(text=logo_html, width=70, height=70, styles={"padding": "5px"})
logo_top_right = Div(text=logo_html, width=70, height=70, styles={"padding": "5px"})
logo_bottom_left = Div(text=logo_html, width=70, height=70, styles={"padding": "5px"})
logo_bottom_right = Div(text=logo_html, width=70, height=70, styles={"padding": "5px"})


# =====================================================
# HMI STATUS HEADER (COMPACT DESIGN)
# =====================================================
conn_status = Div(
    text="🔴 TCP: Disconnected",
    styles={
        "font-size": "16px", 
        "color": "#DC2626", 
        "font-weight": "600",
        "padding": "10px 15px",
        "margin-bottom": "8px",
        "border-left": "4px solid #DC2626",
        "border-radius": "4px",
        "background-color": "#FEF2F2",
        "box-shadow": "0 1px 2px rgba(0,0,0,0.05)"
    },
    height=45
)

force_status = Div(
    text="🟢 Force: Normal",
    styles={
        "font-size": "16px", 
        "color": "#16A34A", 
        "font-weight": "600",
        "padding": "10px 15px",
        "margin-bottom": "8px",
        "border-left": "4px solid #16A34A",
        "border-radius": "4px",
        "background-color": "#F0FDF4",
        "box-shadow": "0 1px 2px rgba(0,0,0,0.05)"
    },
    height=45
)

rate_status = Div(
    text="⏱ Update: -- ms",
    styles={
        "font-size": "15px", 
        "color": "#4B5563",
        "font-weight": "500",
        "padding": "10px 15px",
        "margin-bottom": "8px",
        "border-left": "4px solid #9CA3AF",
        "border-radius": "4px",
        "background-color": "#F9FAFB",
        "box-shadow": "0 1px 2px rgba(0,0,0,0.05)"
    },
    height=45
)

# =====================================================
# 🚨 FORCE ALARM POPUP (COMPACT DESIGN)
# =====================================================
alarm_div = Div(
    text="",
    visible=False,
    styles={
        "background-color": "#991B1B",
        "color": "white",
        "padding": "12px 16px",
        "font-size": "15px",
        "font-weight": "600",
        "border-radius": "4px",
        "text-align": "center",
        "box-shadow": "0 2px 4px rgba(0,0,0,0.15)"
    }
)

ack_button = Button(
    label="ACKNOWLEDGE ALARM",
    button_type="danger",
    width=220,
    visible=False
)

def acknowledge_alarm():
    global alarm_active, paused
    alarm_active = False
    paused = False
    alarm_div.visible = False
    ack_button.visible = False
    pause_button.label = "⏸ Pause"
    pause_button.button_type = "warning"

ack_button.on_click(acknowledge_alarm)

# =====================================================
# PAUSE / RESUME BUTTON (PROFESSIONAL DESIGN)
# =====================================================
pause_button = Button(
    label="⏸ Pause",
    button_type="warning",
    width=120
)

def toggle_pause():
    global paused
    if alarm_active:
        return
    paused = not paused
    pause_button.label = "▶ Resume" if paused else "⏸ Pause"
    pause_button.button_type = "success" if paused else "warning"

pause_button.on_click(toggle_pause)

# =====================================================
# 💾 SAVE SCREENSHOT BUTTON (PROFESSIONAL DESIGN)
# =====================================================
save_button = Button(
    label="💾 Save Screenshot",
    button_type="primary",
    width=170
)

# =====================================================
# SCREENSHOT FUNCTIONALITY (Using Firefox)
# =====================================================
def save_dashboard_screenshot():
    os.makedirs("screenshots", exist_ok=True)
    filename = datetime.now().strftime("screenshots/dashboard_%Y%m%d_%H%M%S.png")

    opts = Options()
    opts.add_argument("--headless")  # Run in headless mode

    # Explicit geckodriver path (as per your setup)
    driver = webdriver.Firefox(options=opts, executable_path="/usr/local/bin/geckodriver")

    try:
        export_png(main_layout, filename=filename, webdriver=driver)
        print(f"✅ Screenshot saved: {filename}")
    finally:
        driver.quit()

def on_save_click():
    save_dashboard_screenshot()

save_button.on_click(on_save_click)

# =====================================================
# TCP SERVER (BACKGROUND THREAD)
# =====================================================
def socket_server():
    HOST = "0.0.0.0"
    PORT = 5001

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(1)

    print("Waiting for C++ connection...")

    while True:
        conn, addr = s.accept()
        print("Connected from:", addr)

        buffer = ""
        try:
            while True:
                data = conn.recv(1024).decode()
                if not data:
                    break

                buffer += data
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    try:
                        values = list(map(float, line.split(",")))
                        if len(values) == 13:
                            data_queue.put(values)
                    except:
                        pass
        finally:
            conn.close()
            print("C++ client disconnected")

# =====================================================
# START TCP SERVER ONCE
# =====================================================
if not _socket_thread_started:
    threading.Thread(target=socket_server, daemon=True).start()
    _socket_thread_started = True

# =====================================================
# DATA SOURCES
# =====================================================
sources = [ColumnDataSource(data=dict(x=[], y=[], size=[], color=[])) for _ in range(6)]
force_mag_source = ColumnDataSource(data=dict(t=[], fmag=[]))
tcp3d_source = ColumnDataSource(data=dict(x=[], y=[], z=[]))

# =====================================================
# 2D PLOTS (ZERO MARGINS FOR NO GAPS)
# =====================================================
titles = [
    "XY Position", "YZ Position", "ZX Position",
    "XY Force", "YZ Force", "ZX Force"
]

axes = [
    ("X time", "Y Position"),
    ("Y time", "Z Position"),
    ("Z time", "X Position"),

    (" X time", "Force Y"),
    (" Y time", "Force Z"),
    (" Z time", "Force X")
]

figs = [
    figure(
        title=titles[i],
        x_axis_label=axes[i][0],
        y_axis_label=axes[i][1],
        width=350,
        height=280,
        toolbar_location="right",  # Move toolbar to side to reduce vertical space
        margin=(0, 0, 0, 0)  # ✅ ZERO margins - no gaps!
    )
    for i in range(6)
]

for i, f in enumerate(figs):
    f.scatter('x', 'y', size='size', color='color', alpha=0.7, source=sources[i])
    f.add_tools(HoverTool(tooltips=[("X","@x{0.00}"),("Y","@y{0.00}")]))
    # remove inner plot borders/padding so subplots sit flush
    f.min_border = 0
    f.min_border_right = 0
    f.min_border_top = 0
    f.min_border_bottom = 0

# fixed left margin (pixels) used to align plotting areas exactly
LEFT_MARGIN = 60

# apply left margin to each small subplot so their plotting areas line up
for f in figs:
    f.min_border_left = LEFT_MARGIN


# =====================================================
# TCP 3D VIEW (COMPACT SIZE)
# =====================================================
color_mapper = LinearColorMapper(palette="Turbo256", low=100, high=150)

tcp3d_fig = figure(
    title="TCP 3D View (XY with Z depth)",
    x_axis_label="X Position",
    y_axis_label="Y Position",
    width=600,
    height=420,
    toolbar_location="right"
)

tcp3d_fig.scatter(
    'x', 'y',
    source=tcp3d_source,
    size=10,
    color=linear_cmap('z', "Turbo256", low=100, high=150),
    alpha=0.9
)

tcp3d_fig.line('x', 'y', source=tcp3d_source, line_width=2, alpha=0.6)
tcp3d_fig.add_layout(ColorBar(color_mapper=color_mapper, title="Z Position"), 'right')

# =====================================================
# FORCE MAGNITUDE (ZERO MARGINS)
# =====================================================
force_fig = figure(
    title="Resultant Force |F|",
    x_axis_label="Time",
    y_axis_label="Force Magnitude",
    width=1050,
    height=250,
    toolbar_location="right",
    margin=(0, 0, 0, 0)  # ✅ ZERO margins
)
# match min_border settings of small subplots so plotting areas align
force_fig.min_border = 0
force_fig.min_border_left = LEFT_MARGIN
force_fig.min_border_right = 0
force_fig.min_border_top = 0
force_fig.min_border_bottom = 0

force_fig.line('t', 'fmag', source=force_mag_source, line_width=3)
force_fig.add_layout(
    Span(location=FORCE_THRESHOLD, dimension='width',
         line_color='red', line_dash='dashed', line_width=2)
)

# =====================================================
# UPDATE LOOP
# =====================================================
def update():
    global counter, last_update_time, last_data_time
    global csv_file, csv_writer, recording_active
    global alarm_active, paused

    now = time()

    # ---------------- TCP HEARTBEAT ----------------
    tcp_connected = (now - last_data_time) < 0.5

    if tcp_connected:
        conn_status.text = "🟢 TCP: Connected"
        conn_status.styles = {
            "font-size": "16px",
            "color": "#16A34A",
            "font-weight": "600",
            "padding": "10px 15px",
            "margin-bottom": "8px",
            "border-left": "4px solid #16A34A",
            "border-radius": "4px",
            "background-color": "#F0FDF4",
            "box-shadow": "0 1px 2px rgba(0,0,0,0.05)"
        }
    else:
        conn_status.text = "🔴 TCP: Disconnected"
        conn_status.styles = {
            "font-size": "16px",
            "color": "#DC2626",
            "font-weight": "600",
            "padding": "10px 15px",
            "margin-bottom": "8px",
            "border-left": "4px solid #DC2626",
            "border-radius": "4px",
            "background-color": "#FEF2F2",
            "box-shadow": "0 1px 2px rgba(0,0,0,0.05)"
        }

        if recording_active:
            csv_file.close()
            recording_active = False

    if paused or data_queue.empty():
        return

    X,Y,Z,A,B,C,Fx,Fy,Fz,Tx,Ty,Tz,z_travel = data_queue.get()
    last_data_time = now

    # ---------------- FORCE CHECK (ALARM) ----------------
    force = np.array([Fx, Fy, Fz])
    fmag = np.linalg.norm(force)

    if fmag > FORCE_THRESHOLD and not alarm_active:
        alarm_active = True
        paused = True
        alarm_div.text = f"🚨 FORCE LIMIT EXCEEDED!<br>|F| = {fmag:.2f}"
        alarm_div.visible = True
        ack_button.visible = True
        pause_button.label = "▶ Resume"
        pause_button.button_type = "success"

    # ---------------- CSV RECORDING ----------------
    if not recording_active:
        os.makedirs("recordings", exist_ok=True)
        filename = datetime.now().strftime("recordings/session_%Y%m%d_%H%M%S.csv")
        csv_file = open(filename, "w", newline="")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow([
            "timestamp","X","Y","Z","A","B","C",
            "Fx","Fy","Fz","Tx","Ty","Tz","z_travel"
        ])
        recording_active = True

    csv_writer.writerow([
        datetime.now().isoformat(),
        X,Y,Z,A,B,C,
        Fx,Fy,Fz,Tx,Ty,Tz,
        z_travel
    ])

    # ---------------- UI UPDATE ----------------
    rate_status.text = f"⏱ Update: {(now - last_update_time)*1000:.0f} ms"
    last_update_time = now

    if alarm_active:
        force_status.text = f"🔴 Force: HIGH ({fmag:.2f})"
        force_status.styles = {
            "font-size": "16px",
            "color": "#DC2626",
            "font-weight": "600",
            "padding": "10px 15px",
            "margin-bottom": "8px",
            "border-left": "4px solid #DC2626",
            "border-radius": "4px",
            "background-color": "#FEF2F2",
            "box-shadow": "0 1px 2px rgba(0,0,0,0.05)"
        }
    else:
        force_status.text = f"🟢 Force: Normal ({fmag:.2f})"
        force_status.styles = {
            "font-size": "16px",
            "color": "#16A34A",
            "font-weight": "600",
            "padding": "10px 15px",
            "margin-bottom": "8px",
            "border-left": "4px solid #16A34A",
            "border-radius": "4px",
            "background-color": "#F0FDF4",
            "box-shadow": "0 1px 2px rgba(0,0,0,0.05)"
        }

    size = np.clip(np.abs(force)*10, 5, 25)
    color = ['green' if f >= 0 else 'red' for f in force]
    values = [(X,Y),(Y,Z),(Z,X),(Fx,Fy),(Fy,Fz),(Fz,Fx)]

    for i in range(6):
        sources[i].stream(
            dict(
                x=[values[i][0]],
                y=[values[i][1]],
                size=[size[i % 3]],
                color=[color[i % 3]]
            ),
            rollover=50
        )

    tcp3d_source.stream(dict(x=[X], y=[Y], z=[Z]), rollover=200)
    force_mag_source.stream(dict(t=[counter], fmag=[fmag]), rollover=200)
    counter += 1

curdoc().add_periodic_callback(update, 150)

# =====================================================
# LAYOUT WITH CORNER LOGOS
# =====================================================

# Build a tightly-packed grid using rows/columns with zero spacing
row1 = row(figs[0], figs[1], figs[2], sizing_mode=None, spacing=0, align='start')
row2 = row(figs[3], figs[4], figs[5], sizing_mode=None, spacing=0, align='start')
row3 = row(force_fig, sizing_mode=None, spacing=0, align='start')

plots_grid = column(row1, row2, row3, sizing_mode=None, spacing=0)

# Create a spacer to fill remaining vertical space
spacer_div = Div(text="", styles={"min-height": "1px"}, sizing_mode="stretch_height")

# Status block with buttons and spacer
status_block = column(
    conn_status,
    force_status,
    rate_status,
    row(pause_button, save_button, spacing=10),
    spacer_div,  # This will expand to fill remaining space
    spacing=8,
    height=480,  # Fixed height for upper half
    sizing_mode="fixed"
)

alarm_block = column(
    alarm_div,
    ack_button,
    spacing=8
)

# Left column with 50/50 split between status and 3D plot
left_column = column(
    status_block,
    tcp3d_fig,
    alarm_block,
    spacing=15
)

# Main content layout
main_content = row(left_column, plots_grid, sizing_mode='stretch_width', spacing=20, align='start')

# =====================================================
# CREATE LAYOUT WITH LOGOS IN CORNERS
# =====================================================
# Top row with logos in corners
top_spacer = Div(text="", sizing_mode="stretch_width", height=10)
top_row = row(
    logo_top_left,
    top_spacer,
    logo_top_right,
    sizing_mode="stretch_width",
    height=70
)

# Bottom row with logos in corners
bottom_spacer = Div(text="", sizing_mode="stretch_width", height=10)
bottom_row = row(
    logo_bottom_left,
    bottom_spacer,
    logo_bottom_right,
    sizing_mode="stretch_width",
    height=70
)

# Complete layout with logos at corners
main_layout = column(
    top_row,
    main_content,
    bottom_row,
    sizing_mode="stretch_both",
    spacing=5
)

curdoc().add_root(main_layout)