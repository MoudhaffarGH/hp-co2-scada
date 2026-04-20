"""
mqtt_publisher.py
CO2 Transcritical Heat Pump - Cloud MQTT Publisher
Publishes to HiveMQ Cloud broker over TLS (port 8883)

Usage:
    python mqtt_publisher.py           # simulator mode
    python mqtt_publisher.py --real    # real M172 hardware via Modbus TCP
"""

import json
import time
import argparse
import paho.mqtt.client as mqtt
from plc_simulator import CO2HeatPumpSimulator, ModbusReader

# ── HiveMQ Cloud Configuration ─────────────────────────────────────────────
BROKER_HOST      = "4c17435853b94c7cae7c35a9d90b7f19.s1.eu.hivemq.cloud"
BROKER_PORT      = 8883   # TLS port for cloud
MQTT_USERNAME    = "hp_co2"
MQTT_PASSWORD    = "HeatPump2026"
PUBLISH_INTERVAL = 1.0    # seconds

# ── Topics ─────────────────────────────────────────────────────────────────
TOPIC_BASE   = "heatpump/co2"
TOPIC_DATA   = f"{TOPIC_BASE}/data"
TOPIC_STATUS = f"{TOPIC_BASE}/status"
TOPIC_ALARM  = f"{TOPIC_BASE}/alarm"

# ── MQTT Callbacks ─────────────────────────────────────────────────────────
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[MQTT] ✅ Connected to HiveMQ Cloud: {BROKER_HOST}")
        client.publish(TOPIC_STATUS, "ONLINE", retain=True)
    else:
        print(f"[MQTT] ❌ Connection failed with code {rc}")

def on_disconnect(client, userdata, flags, rc, properties=None):
    print(f"[MQTT] Disconnected (rc={rc})")

def on_publish(client, userdata, mid, reason_code=None, properties=None):
    pass  # silent publish confirmation

# ── Main ───────────────────────────────────────────────────────────────────
def main(use_real_hardware=False):
    # Select data source
    if use_real_hardware:
        print("[PLC] Connecting to real M172 via Modbus TCP 127.0.0.1:502 ...")
        source = ModbusReader(host="127.0.0.1", port=502)
        if not source.connected:
            print("[PLC] ⚠️  Hardware not found. Falling back to simulator.")
            source = CO2HeatPumpSimulator()
        else:
            print("[PLC] ✅ Connected to real M172 hardware.")
    else:
        print("[PLC] 🔵 Using CO2 heat pump simulator")
        source = CO2HeatPumpSimulator()

    # Setup MQTT client with TLS for HiveMQ Cloud
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="HP_CO2_Publisher"
    )
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.tls_set()  # enables TLS for HiveMQ cloud

    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_publish    = on_publish
    client.will_set(TOPIC_STATUS, "OFFLINE", retain=True)

    print(f"[MQTT] Connecting to HiveMQ Cloud...")
    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    except Exception as e:
        print(f"[MQTT] ❌ Connection error: {e}")
        return

    client.loop_start()
    time.sleep(1)  # wait for connection

    prev_fault = 0
    print(f"[SYSTEM] Publishing every {PUBLISH_INTERVAL}s to HiveMQ Cloud. Ctrl+C to stop.\n")

    try:
        while True:
            data = source.get_data()
            data["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            data["source"]    = "real_hardware" if use_real_hardware else "simulator"

            # Publish full data
            client.publish(TOPIC_DATA, json.dumps(data), qos=1)

            # Publish alarm on fault change
            if data["FaultCode"] != prev_fault:
                alarm = {
                    "fault_code": data["FaultCode"],
                    "mode":       data["Mode_Name"],
                    "timestamp":  data["timestamp"],
                    "message":    "FAULT CLEARED" if data["FaultCode"] == 0
                                  else f"FAULT: 0x{data['FaultCode']:04X}"
                }
                client.publish(TOPIC_ALARM, json.dumps(alarm), qos=2, retain=True)
                prev_fault = data["FaultCode"]

            print(
                f"[{data['timestamp']}] "
                f"Mode={data['Mode_Name']:10s} | "
                f"COP={data['COP_Realtime']:5.2f} | "
                f"P_opt={data['P_Optimal']:6.2f} bar | "
                f"T_out={data['T_GasCoolerOut']:5.1f}°C | "
                f"Q={data['HeatOutput_kW']:5.2f} kW"
            )

            time.sleep(PUBLISH_INTERVAL)

    except KeyboardInterrupt:
        print("\n[SYSTEM] Shutting down...")
    finally:
        client.publish(TOPIC_STATUS, "OFFLINE", retain=True)
        client.loop_stop()
        client.disconnect()
        if hasattr(source, 'close'):
            source.close()
        print("[SYSTEM] Publisher stopped.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CO2 Heat Pump MQTT Publisher")
    parser.add_argument("--real", action="store_true",
                        help="Use real M172 hardware via Modbus TCP")
    args = parser.parse_args()
    main(use_real_hardware=args.real)
