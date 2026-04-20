"""
streamlit_app.py
CO2 Transcritical Heat Pump - Cloud SCADA Dashboard
Subscribes to HiveMQ Cloud MQTT broker over TLS.
Deploy on Streamlit Cloud for public access.
"""

import json
import time
import collections
from datetime import datetime
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import paho.mqtt.client as mqtt

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CO₂ Heat Pump SCADA",
    page_icon="🌡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Custom CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #0e1117; }
    .header-title {
        font-size: 1.8rem; font-weight: 700;
        background: linear-gradient(90deg, #00d4aa, #0099ff);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }
    div[data-testid="stMetric"] {
        background: #1e2130;
        border: 1px solid #3d4263;
        border-radius: 10px;
        padding: 12px;
    }
</style>
""", unsafe_allow_html=True)

# ── HiveMQ Cloud Configuration ─────────────────────────────────────────────
BROKER_HOST   = "4c17435853b94c7cae7c35a9d90b7f19.s1.eu.hivemq.cloud"
BROKER_PORT   = 8883
MQTT_USERNAME = "hp_co2"
MQTT_PASSWORD = "HeatPump2026"
TOPIC_DATA    = "heatpump/co2/data"
TOPIC_ALARM   = "heatpump/co2/alarm"
TOPIC_STATUS  = "heatpump/co2/status"
HISTORY_LEN   = 120

# ── Mode colors ────────────────────────────────────────────────────────────
MODE_COLOR = {
    "eHEATING": "#ff6b35",
    "eCOOLING": "#0099ff",
    "eDHW":     "#ffaa00",
    "eSTANDBY": "#888888",
    "eOFF":     "#444444",
    "eDEFROST": "#00ccff",
    "eALARM":   "#ff4444",
    "eFAULT":   "#ff0000",
}

# ── MQTT client cached across reruns ──────────────────────────────────────
@st.cache_resource
def get_mqtt_client():
    store = {
        "latest":      {},
        "history":     collections.deque(maxlen=HISTORY_LEN),
        "alarms":      [],
        "connected":   False,
        "last_update": None,
        "broker_status": "OFFLINE"
    }

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            store["connected"] = True
            store["broker_status"] = "ONLINE"
            client.subscribe(TOPIC_DATA,   qos=1)
            client.subscribe(TOPIC_ALARM,  qos=2)
            client.subscribe(TOPIC_STATUS, qos=1)

    def on_disconnect(client, userdata, flags, rc, properties=None):
        store["connected"]      = False
        store["broker_status"]  = "OFFLINE"

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            if msg.topic == TOPIC_DATA:
                store["latest"]      = payload
                store["last_update"] = datetime.now()
                store["history"].append(payload)
            elif msg.topic == TOPIC_ALARM:
                store["alarms"].append(payload)
                if len(store["alarms"]) > 20:
                    store["alarms"].pop(0)
            elif msg.topic == TOPIC_STATUS:
                store["broker_status"] = msg.payload.decode()
        except Exception:
            pass

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="HP_Dashboard_Cloud"
    )
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.tls_set()
    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_disconnect = on_disconnect

    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        client.loop_start()
    except Exception as e:
        store["error"] = str(e)

    return client, store

# ── Gauge chart ────────────────────────────────────────────────────────────
def make_gauge(value, title, min_val, max_val, unit, warn, crit):
    color = "#00d4aa" if value < warn else "#ffaa00" if value < crit else "#ff4444"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        title={"text": f"{title}<br><span style='font-size:0.8em;color:#8892b0'>{unit}</span>",
               "font": {"color": "#ccd6f6", "size": 13}},
        number={"font": {"color": color, "size": 26}, "suffix": f" {unit}"},
        gauge={
            "axis":    {"range": [min_val, max_val], "tickcolor": "#8892b0",
                        "tickfont": {"color": "#8892b0", "size": 9}},
            "bar":     {"color": color, "thickness": 0.25},
            "bgcolor": "#1e2130", "bordercolor": "#3d4263",
            "steps": [
                {"range": [min_val, warn], "color": "#1a3a2a"},
                {"range": [warn,   crit], "color": "#3a3a1a"},
                {"range": [crit, max_val],"color": "#3a1a1a"},
            ],
            "threshold": {"line": {"color": "#ff4444", "width": 2},
                          "thickness": 0.75, "value": crit},
        }
    ))
    fig.update_layout(
        height=210, margin=dict(l=20, r=20, t=50, b=10),
        paper_bgcolor="#0e1117", font_color="#ccd6f6"
    )
    return fig

# ── Time series chart ──────────────────────────────────────────────────────
def make_timeseries(history, keys, title, unit, colors=None):
    if not history:
        return go.Figure()
    df = pd.DataFrame(list(history))
    if "timestamp" not in df.columns:
        return go.Figure()
    default_colors = ["#00d4aa", "#0099ff", "#ff6b6b", "#ffaa00", "#cc88ff"]
    fig = go.Figure()
    for i, key in enumerate(keys):
        if key not in df.columns:
            continue
        color = colors[i] if colors and i < len(colors) else default_colors[i % len(default_colors)]
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df[key],
            name=key.replace("_", " "),
            line=dict(color=color, width=2),
            mode="lines"
        ))
    fig.update_layout(
        title=dict(text=title, font=dict(color="#ccd6f6", size=13)),
        xaxis=dict(showgrid=True, gridcolor="#2a2d3e",
                   tickfont=dict(color="#8892b0")),
        yaxis=dict(showgrid=True, gridcolor="#2a2d3e",
                   tickfont=dict(color="#8892b0"),
                   title=dict(text=unit, font=dict(color="#8892b0"))),
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        legend=dict(bgcolor="#1e2130", bordercolor="#3d4263",
                    font=dict(color="#ccd6f6")),
        height=270, margin=dict(l=50, r=20, t=40, b=40)
    )
    return fig

# ══════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## ⚙️ System Info")
    st.markdown(f"""
    **PLC:** Schneider M172 28-42 I/Os  
    **Software:** EcoStruxure HVAC  
    **Refrigerant:** CO₂ (R-744)  
    **Cycle:** Transcritical  
    **Protocol:** Modbus TCP → MQTT  
    **Broker:** HiveMQ Cloud  
    """)
    st.divider()
    st.markdown("## 📡 MQTT Broker")
    st.code(f"{BROKER_HOST}\nPort: {BROKER_PORT} (TLS)", language="text")
    st.divider()
    st.markdown("## 📋 Topics")
    st.code(f"heatpump/co2/data\nheatpump/co2/alarm\nheatpump/co2/status", language="text")
    st.divider()
    st.markdown("## 🔌 Hardware Mode")
    st.info("Currently running in **Simulator** mode.\n\nSwitch to real hardware:\n```\npython mqtt_publisher.py --real\n```")

# ══════════════════════════════════════════════════════════════════════════
#  MAIN DASHBOARD
# ══════════════════════════════════════════════════════════════════════════
def render():
    client, store = get_mqtt_client()
    d       = store["latest"]
    history = store["history"]

    # ── Header ─────────────────────────────────────────────────────────
    c1, c2 = st.columns([4, 1])
    with c1:
        st.markdown('<p class="header-title">🌡️ CO₂ Transcritical Heat Pump — Cloud SCADA</p>',
                    unsafe_allow_html=True)
        st.caption("Schneider M172 PLC | EcoStruxure HVAC | MQTT IoT | Final Year Project")
    with c2:
        if store["connected"]:
            st.success("🟢 HiveMQ Cloud")
        else:
            st.error("🔴 Disconnected")
        if store["last_update"]:
            st.caption(f"Updated: {store['last_update'].strftime('%H:%M:%S')}")

    st.divider()

    if not d:
        st.info("⏳ Waiting for data from publisher...")
        st.markdown("**Make sure `mqtt_publisher.py` is running on your PC:**")
        st.code("python mqtt_publisher.py", language="bash")
        time.sleep(2)
        st.rerun()
        return

    # ── Mode banner ─────────────────────────────────────────────────────
    mode_name  = d.get("Mode_Name", "UNKNOWN")
    mode_color = MODE_COLOR.get(mode_name, "#888888")
    fault_code = d.get("FaultCode", 0)
    safety_ok  = d.get("SafetyOK", True)
    source     = d.get("source", "simulator")

    st.markdown(
        f"""<div style='background:{mode_color}22;border:2px solid {mode_color};
        border-radius:10px;padding:10px 20px;display:flex;
        justify-content:space-between;align-items:center;margin-bottom:12px'>
        <span style='color:{mode_color};font-size:1.2rem;font-weight:700'>
            ⚡ {mode_name}</span>
        <span style='color:{"#00ff88" if safety_ok else "#ff4444"};font-weight:600'>
            {"✅ Safety OK" if safety_ok else "🚨 FAULT"}</span>
        <span style='color:#8892b0'>Fault: 0x{fault_code:04X}</span>
        <span style='color:#8892b0'>Source: {"🔧 Real Hardware" if source=="real_hardware" else "🔵 Simulator"}</span>
        <span style='color:#8892b0'>Watchdog: {"🟢" if d.get("Watchdog") else "🔴"}</span>
        </div>""",
        unsafe_allow_html=True
    )

    # ── KPI metrics ─────────────────────────────────────────────────────
    st.markdown("### 📊 Key Performance Indicators")
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1: st.metric("⚡ COP",            f"{d.get('COP_Realtime',0):.2f}",      f"{d.get('COP_Realtime',0)-6:.2f} vs baseline")
    with m2: st.metric("🔥 Heat Output",    f"{d.get('HeatOutput_kW',0):.1f} kW")
    with m3: st.metric("🔵 Optimal P",      f"{d.get('P_Optimal',0):.1f} bar")
    with m4: st.metric("💨 Compressor",     f"{d.get('AO_CompressorSpeed',0):.1f} %")
    with m5: st.metric("🔧 GCPV",           f"{d.get('AO_GCPV_Opening',0):.1f} %")

    st.divider()

    # ── Gauges ──────────────────────────────────────────────────────────
    st.markdown("### 🎯 Live Gauges")
    g1, g2, g3, g4 = st.columns(4)
    with g1: st.plotly_chart(make_gauge(d.get("COP_Realtime",0),    "COP",                  0,   12,  "",    6,   10),  use_container_width=True)
    with g2: st.plotly_chart(make_gauge(d.get("P_HighSide",0),      "High Side Pressure",   0,  120, "bar", 80,  100),  use_container_width=True)
    with g3: st.plotly_chart(make_gauge(d.get("T_Discharge",0),     "Discharge Temp",       0,  150, "°C", 100,  130),  use_container_width=True)
    with g4: st.plotly_chart(make_gauge(d.get("T_GasCoolerOut",0),  "Gas Cooler Outlet",   20,   90, "°C",  60,   75),  use_container_width=True)

    # ── Variables ────────────────────────────────────────────────────────
    st.markdown("### 🌡️ Live Variables")
    v1, v2, v3 = st.columns(3)

    with v1:
        st.markdown("**Temperatures**")
        for name, key in [
            ("Gas Cooler Out", "T_GasCoolerOut"),
            ("Gas Cooler In",  "T_GasCoolerIn"),
            ("Discharge",      "T_Discharge"),
            ("Ambient",        "T_Ambient"),
            ("Process Water",  "T_ProcessWater"),
            ("Evaporator",     "T_Evaporator"),
            ("Suction",        "T_Suction"),
        ]:
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;"
                f"padding:3px 0;border-bottom:1px solid #2a2d3e'>"
                f"<span style='color:#8892b0;font-size:0.85rem'>{name}</span>"
                f"<span style='color:#00d4aa;font-weight:600'>{d.get(key,0):.1f} °C</span></div>",
                unsafe_allow_html=True
            )

    with v2:
        st.markdown("**Pressures & Flow**")
        for name, key, unit, color in [
            ("High Side",      "P_HighSide",  "bar", "#ff6b35"),
            ("Low Side",       "P_LowSide",   "bar", "#0099ff"),
            ("Optimal (Liao)", "P_Optimal",   "bar", "#ffaa00"),
            ("Water Flow",     "F_WaterFlow", "L/min","#00d4aa"),
            ("SP Water Out",   "SP_WaterOutlet","°C","#cc88ff"),
        ]:
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;"
                f"padding:3px 0;border-bottom:1px solid #2a2d3e'>"
                f"<span style='color:#8892b0;font-size:0.85rem'>{name}</span>"
                f"<span style='color:{color};font-weight:600'>{d.get(key,0):.2f} {unit}</span></div>",
                unsafe_allow_html=True
            )

    with v3:
        st.markdown("**Digital Outputs**")
        outputs = {
            "Compressor":    safety_ok and mode_name == "eHEATING",
            "Water Pump":    safety_ok and mode_name != "eOFF",
            "Fan":           safety_ok and mode_name == "eHEATING",
            "Alarm":         fault_code != 0,
            "Master Enable": d.get("MasterEnable", False),
        }
        for name, state in outputs.items():
            color = "#00ff88" if state else "#ff4444"
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;"
                f"padding:5px 0;border-bottom:1px solid #2a2d3e'>"
                f"<span style='color:#8892b0;font-size:0.85rem'>{name}</span>"
                f"<span style='color:{color};font-weight:600'>{'🟢 ON' if state else '🔴 OFF'}</span></div>",
                unsafe_allow_html=True
            )

    st.divider()

    # ── Trend charts ─────────────────────────────────────────────────────
    st.markdown("### 📈 Real-Time Trends")
    r1, r2 = st.columns(2)
    with r1:
        st.plotly_chart(make_timeseries(history,
            ["COP_Realtime"], "COP Trend", "",
            ["#00d4aa"]), use_container_width=True)
    with r2:
        st.plotly_chart(make_timeseries(history,
            ["P_HighSide", "P_LowSide", "P_Optimal"],
            "Pressure Trends", "bar",
            ["#ff6b35", "#0099ff", "#ffaa00"]), use_container_width=True)

    r3, r4 = st.columns(2)
    with r3:
        st.plotly_chart(make_timeseries(history,
            ["T_GasCoolerOut", "T_GasCoolerIn", "T_Discharge", "T_Ambient"],
            "Temperature Trends", "°C",
            ["#ff6b35", "#ffaa00", "#ff4444", "#0099ff"]), use_container_width=True)
    with r4:
        st.plotly_chart(make_timeseries(history,
            ["AO_CompressorSpeed", "AO_GCPV_Opening"],
            "PID Actuator Outputs", "%",
            ["#00d4aa", "#cc88ff"]), use_container_width=True)

    # ── Alarm log ─────────────────────────────────────────────────────────
    if store["alarms"]:
        st.divider()
        st.markdown("### 🚨 Alarm Log")
        for alarm in reversed(store["alarms"][-5:]):
            color = "#ff4444" if "FAULT" in alarm.get("message","") else "#00ff88"
            st.markdown(
                f"<div style='background:#1e2130;border-left:3px solid {color};"
                f"padding:8px 12px;margin:4px 0;border-radius:4px'>"
                f"<span style='color:{color};font-weight:600'>{alarm.get('message','')}</span> "
                f"<span style='color:#8892b0;font-size:0.85rem'>— {alarm.get('timestamp','')}</span>"
                f"</div>",
                unsafe_allow_html=True
            )

    # Auto-refresh
    time.sleep(1)
    st.rerun()

render()
