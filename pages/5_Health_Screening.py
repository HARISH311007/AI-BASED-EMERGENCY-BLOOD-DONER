"""
Page 5: Pre-Donation Health Screening Module & Override Workflow.
"""

import streamlit as st
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from pathlib import Path

# Load Custom CSS
CSS_PATH = Path(__file__).parent.parent / "assets" / "style.css"
if CSS_PATH.exists():
    with open(CSS_PATH, "r") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

from database.db import (
    fetch_health_screenings, fetch_donors, 
    insert_health_screening, update_screening_status
)
from utils.screening_rules import evaluate_health_screening
from utils.validation import validate_screening_vitals
from backend.temperature_check import check_temperature_eligibility, run_health_screening_backend
from backend.esp_service import fetch_esp_vitals

# Initialize Session State for ESP Hardware Live Telemetry
if "esp_temp" not in st.session_state:
    st.session_state["esp_temp"] = 36.8
if "esp_hr" not in st.session_state:
    st.session_state["esp_hr"] = 74
if "esp_spo2" not in st.session_state:
    st.session_state["esp_spo2"] = 98
if "esp_sys" not in st.session_state:
    st.session_state["esp_sys"] = 120
if "esp_dia" not in st.session_state:
    st.session_state["esp_dia"] = 80
if "esp_ip" not in st.session_state:
    st.session_state["esp_ip"] = "192.168.4.1"

st.markdown("""
<div class="section-header">
    <div>
        <h2>🩺 Pre-Donation Health Screening Module</h2>
        <p>Evaluate preliminary donor vitals, rule-based screening indicators, safety warnings, and physician review overrides.</p>
    </div>
    <span class="badge badge-purple">PRE-DONATION SAFETY</span>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="medical-disclaimer">
    🔴 <b>IMPORTANT SAFETY MANDATE:</b> Sensor readings and automated rule evaluations are preliminary indicators only, NOT medical clearance. Final donor eligibility must be determined by qualified blood-bank personnel using clinical guidelines.
</div>
""", unsafe_allow_html=True)

screenings_df = fetch_health_screenings()
donors_df = fetch_donors()

# Navigation Tabs: New Screening Form | Health Screening System | ESP Hardware Telemetry | Screening Log & Manual Override
tab_eval, tab_backend, tab_esp, tab_log = st.tabs([
    "📝 Evaluate New Screening Readings", 
    "☕ HEALTH SCREENING SYSTEM", 
    "📡 ESP Hardware Setup & Firmware",
    "📜 Screening History & Physician Override"
])

with tab_eval:
    st.markdown("##### 📡 ESP Microcontroller Hardware Live Sync Bridge")
    st.caption("Connect to your ESP32 / ESP8266 board via Wi-Fi IP to automatically stream donor vitals directly into the form.")

    col_esp_input, col_esp_btn, col_esp_sim = st.columns([2.5, 1.2, 1.2])
    with col_esp_input:
        entered_esp_ip = st.text_input(
            "ESP Hardware IP Address / URL:", 
            value=st.session_state["esp_ip"], 
            placeholder="e.g. 192.168.4.1 or 192.168.1.105",
            help="Default SoftAP IP is 192.168.4.1. If connected to router, enter your ESP local IP from Arduino Serial Monitor."
        )
    with col_esp_btn:
        st.write("")
        st.write("")
        btn_connect_esp = st.button("⚡ Connect & Sync", type="primary", use_container_width=True)
    with col_esp_sim:
        st.write("")
        st.write("")
        btn_sim_esp = st.button("🔄 Test Telemetry", use_container_width=True)

    if btn_connect_esp:
        st.session_state["esp_ip"] = entered_esp_ip
        with st.spinner(f"Connecting to ESP hardware at {entered_esp_ip}..."):
            res = fetch_esp_vitals(entered_esp_ip)
            if res["success"]:
                st.session_state["esp_temp"] = float(res["temperature"])
                st.session_state["esp_hr"] = int(res["heart_rate"])
                st.session_state["esp_spo2"] = int(res["spo2"])
                st.session_state["esp_sys"] = int(res.get("systolic_bp", 120))
                st.session_state["esp_dia"] = int(res.get("diastolic_bp", 80))
                st.success(f"🟢 **ESP Hardware Synced!** Device: `{res['device_id']}` | Latency: `{res['latency_ms']} ms` | Temp: `{res['temperature']}°C` | HR: `{res['heart_rate']} BPM` | SpO2: `{res['spo2']}%`")
            else:
                st.warning(f"⚠️ {res['message']}")
                st.info("💡 **Tip:** Make sure your PC and ESP board are connected to the same Wi-Fi / Hotspot, or connect your PC directly to the ESP's Access Point `ESP_Health_Sensor` (Default IP: `192.168.4.1`).")

    if btn_sim_esp:
        import random
        st.session_state["esp_temp"] = round(random.uniform(36.5, 37.3), 1)
        st.session_state["esp_hr"] = random.randint(68, 84)
        st.session_state["esp_spo2"] = random.randint(97, 99)
        st.success(f"🟢 **Simulated ESP Telemetry Synced!** Temp: `{st.session_state['esp_temp']}°C` | HR: `{st.session_state['esp_hr']} BPM` | SpO2: `{st.session_state['esp_spo2']}%`")

    st.divider()
    st.markdown("##### 🩺 Preliminary Sensor Readings & Questionnaire")
    with st.form("new_screening_form"):
        col_s1, col_s2 = st.columns(2)

        with col_s1:
            if not donors_df.empty:
                donor_choices = {f"{row['name']} ({row['donor_id']})": row for _, row in donors_df.iterrows()}
                selected_donor_str = st.selectbox("Select Registered Donor *", list(donor_choices.keys()))
                sel_donor = donor_choices[selected_donor_str]
                scr_donor_id = sel_donor['donor_id']
                scr_donor_name = sel_donor['name']
            else:
                scr_donor_id = "DON-1001"
                scr_donor_name = "Jane Doe"

            temp_input = st.number_input(
                "Body Temperature (°C) *", 
                min_value=32.0, max_value=42.0, 
                value=float(st.session_state["esp_temp"]), 
                step=0.1, 
                help="Normal: 36.1°C - 37.5°C"
            )
            hr_input = st.number_input(
                "Heart Rate (bpm) *", 
                min_value=30, max_value=200, 
                value=int(st.session_state["esp_hr"]), 
                step=1, 
                help="Normal: 60 - 100 bpm"
            )
            spo2_input = st.number_input(
                "Oxygen Saturation (SpO2 %) *", 
                min_value=70, max_value=100, 
                value=int(st.session_state["esp_spo2"]), 
                step=1, 
                help="Normal: 95% - 100%"
            )

        with col_s2:
            sys_bp_input = st.number_input(
                "Systolic Blood Pressure (mmHg) *", 
                min_value=60, max_value=220, 
                value=int(st.session_state["esp_sys"]), 
                step=1, 
                help="Normal: 90 - 140 mmHg"
            )
            dia_bp_input = st.number_input(
                "Diastolic Blood Pressure (mmHg) *", 
                min_value=40, max_value=140, 
                value=int(st.session_state["esp_dia"]), 
                step=1, 
                help="Normal: 60 - 90 mmHg"
            )
            
            quest_pass_input = st.checkbox("Health Questionnaire Passed (No fever, recent infection, medication, or high-risk travel)", value=True)
            evaluator_name = st.text_input("Evaluator / Staff Operator Name", value="Nurse Operator")

        submit_screening = st.form_submit_button("🩺 Run Screening Rule Engine", type="primary", use_container_width=True)

        if submit_screening:
            is_valid_vitals, err_vitals = validate_screening_vitals(temp_input, hr_input, spo2_input, sys_bp_input, dia_bp_input)
            if not is_valid_vitals:
                st.error(err_vitals)
            else:
                # Run Rule Engine
                eval_res = evaluate_health_screening(
                    temp_input, hr_input, spo2_input, sys_bp_input, dia_bp_input, quest_pass_input
                )

                # Cross-check Temperature Eligibility via Backend
                temp_elig = check_temperature_eligibility(temp_input)
                if not temp_elig["eligible"] and temp_elig.get("message"):
                    eval_res['warnings'].append(f"Backend Temperature Check: {temp_elig['message']}")

                st.markdown("#### 📊 Rule Engine Preliminary Evaluation Results")
                
                status_lbl = eval_res['status_label']
                if eval_res['is_normal']:
                    st.markdown(f"""
                    <div class="alert-card-success">
                        <h4 style="margin:0; color:#065F46;">✅ Preliminary Outcome: {status_lbl}</h4>
                        <p style="margin:4px 0 0 0;">All sensor readings are within configured reference ranges.</p>
                    </div>
                    """, unsafe_allow_html=True)
                elif eval_res['temporary_deferral']:
                    st.markdown(f"""
                    <div class="alert-card-emergency">
                        <h4 style="margin:0; color:#991B1B;">⛔ Preliminary Outcome: {status_lbl}</h4>
                        <p style="margin:4px 0 0 0;">Warning flags detected. Temporary deferral and reassessment suggested.</p>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div class="alert-card-warning">
                        <h4 style="margin:0; color:#9A3412;">🩺 Preliminary Outcome: {status_lbl}</h4>
                        <p style="margin:4px 0 0 0;">Physician review required prior to donation clearance.</p>
                    </div>
                    """, unsafe_allow_html=True)

                if eval_res['warnings']:
                    st.write("##### ⚠️ Detected Warning Flags:")
                    for w in eval_res['warnings']:
                        st.write(f"- 🔸 {w}")

                # Save record to database
                scr_id = f"SCR-{9000 + len(screenings_df) + 1}"
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                scr_payload = {
                    "screening_id": scr_id,
                    "donor_id": scr_donor_id,
                    "donor_name": scr_donor_name,
                    "screening_datetime": now_str,
                    "temperature": float(temp_input),
                    "heart_rate": int(hr_input),
                    "spo2": int(spo2_input),
                    "systolic_bp": int(sys_bp_input),
                    "diastolic_bp": int(dia_bp_input),
                    "health_questionnaire_passed": 1 if quest_pass_input else 0,
                    "preliminary_status": status_lbl,
                    "review_notes": "; ".join(eval_res['warnings']) if eval_res['warnings'] else "Normal screening.",
                    "evaluated_by": evaluator_name
                }
                insert_health_screening(scr_payload)
                st.success(f"Screening saved with ID: **{scr_id}**")

with tab_backend:
    st.markdown("#### ☕ HEALTH SCREENING SYSTEM")
    st.caption("Backend process for evaluating vital signs: Heart Rate, Body Temperature, and SpO2 levels against blood donation safety thresholds.")

    col_jb1, col_jb2 = st.columns([1, 1])

    with col_jb1:
        st.markdown("##### 📥 Enter Donor Vitals for Health Screening System")
        j_hr = st.number_input("Heart Rate (BPM)", min_value=10.0, max_value=250.0, value=74.0, step=1.0, help="Valid range: 30 - 220 BPM | General resting range: 60 - 100 BPM")
        j_temp = st.number_input("Body Temperature (°C)", min_value=20.0, max_value=50.0, value=36.8, step=0.1, help="Valid range: 30 - 45 °C | High Temperature alert: >= 38.0 °C")
        j_spo2 = st.number_input("SpO2 Level (%)", min_value=30.0, max_value=100.0, value=98.0, step=1.0, help="Valid range: 50 - 100 % | Low Oxygen alert: < 95 %")

        # Live Temperature Eligibility Status from backend
        temp_res = check_temperature_eligibility(j_temp)
        if temp_res["eligible"]:
            st.success(f"🌡️ **Temperature Status:** {temp_res['message']}")
        else:
            st.warning(f"⚠️ **Temperature Warning:** {temp_res['message']}")

        btn_run_backend = st.button("▶ Run Health Screening System", type="primary", use_container_width=True)

    with col_jb2:
        st.markdown("##### 🖥️ Health Screening System Output")
        
        backend_result = run_health_screening_backend(j_hr, j_temp, j_spo2)

        if backend_result["is_valid"]:
            if backend_result["alert"]:
                st.markdown(f"""
                <div class="alert-card-emergency">
                    <h4 style="margin:0; color:#EF4444;">🚨 STATUS: {backend_result['status']}</h4>
                    <p style="margin:4px 0 0 0;">Professional assessment is required before donation clearance.</p>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="alert-card-success">
                    <h4 style="margin:0; color:#10B981;">✅ STATUS: {backend_result['status']}</h4>
                    <p style="margin:4px 0 0 0;">Proceed to professional donor assessment.</p>
                </div>
                """, unsafe_allow_html=True)

            if backend_result.get("warnings"):
                st.write("**⚠️ Detected Alert Warnings:**")
                for w in backend_result["warnings"]:
                    st.write(f"- 🔸 {w}")
        else:
            st.error("❌ Invalid input readings: Readings fall outside physiological boundaries.")

        st.caption(f"Engine: {backend_result['executed_via']}")
        st.code(backend_result["output_log"], language="text")

    st.divider()
    with st.expander("📂 View Exact Backend Source Code (`backend/HealthScreeningDemo.java`)", expanded=False):
        java_code_path = Path(__file__).parent.parent / "backend" / "HealthScreeningDemo.java"
        if java_code_path.exists():
            st.code(java_code_path.read_text(encoding="utf-8"), language="java")
        else:
            st.info("backend/HealthScreeningDemo.java loaded in backend folder.")

with tab_esp:
    st.markdown("#### 📡 ESP Hardware Setup, Circuit Pinout & Firmware Code")
    st.caption("Complete guide to connect your ESP32 / ESP8266 microcontroller hardware with sensors to this blood bank website.")

    col_hw1, col_hw2 = st.columns([1, 1])

    with col_hw1:
        st.markdown("##### 🔌 Hardware Sensor & OLED Wiring Guide")
        st.markdown("""
        | Module | Pin on Module | ESP32 Dev Kit V1 Pin | Notes / I2C Address |
        | :--- | :--- | :--- | :--- |
        | **1.3" OLED Display** | VCC | **3.3V** | Power |
        | *(128x64 I2C)* | GND | **GND** | Ground |
        | | SDA | **GPIO 21** | *Shared I2C Bus (Address: `0x3C`)* |
        | | SCL | **GPIO 22** | *Shared I2C Bus* |
        | **MAX30102 / Pulse** | VIN | **3.3V** | Power |
        | *(Heart Rate & SpO2)* | GND | **GND** | Ground |
        | | SDA | **GPIO 21** | *Shared I2C Bus (Address: `0x57`)* |
        | | SCL | **GPIO 22** | *Shared I2C Bus* |
        | **DS18B20 Temp** | VCC | **3.3V** | Power |
        | *(Digital Probe)* | GND | **GND** | Ground |
        | | DATA (DQ) | **GPIO 4** | *4.7kΩ pull-up resistor to 3.3V* |
        """)

        st.markdown("##### 🛠️ How to Connect (Step-by-Step):")
        st.markdown("""
        1. **Flash Firmware:** Upload the provided Arduino sketch below to your ESP board using Arduino IDE.
        2. **Find ESP IP Address:**
           - **Mode A (Hotspot Mode - Default):** Connect PC/mobile to Wi-Fi `ESP_Health_Sensor` (Pass: `12345678`). The ESP IP is automatically **`192.168.4.1`**.
           - **Mode B (Station Mode):** If configured with your home/hotspot Wi-Fi, open Arduino Serial Monitor (`115200 baud`) to see the assigned IP (e.g., `192.168.1.105`).
        3. **Sync on Website:** Enter the IP into the **ESP Microcontroller Hardware Live Sync Bridge** on Tab 1 and click **⚡ Connect & Sync**.
        """)

    with col_hw2:
        st.markdown("##### 🧪 Live REST API Telemetry Endpoint")
        st.markdown("""
        The ESP hardware runs an internal HTTP REST WebServer on port 80:
        - **Endpoint:** `GET http://<ESP_IP>/vitals`
        - **Format:** JSON
        - **Sample Output:**
        ```json
        {
          "status": "OK",
          "device_id": "ESP-HEALTH-SENSOR-01",
          "temperature": 36.8,
          "heart_rate": 74,
          "spo2": 98,
          "systolic_bp": 120,
          "diastolic_bp": 80,
          "sensor_status": "READY"
        }
        ```
        """)

        # Quick Live Ping test
        test_ip = st.text_input("Test ESP IP Connection directly:", value=st.session_state["esp_ip"], key="test_esp_ip_tab")
        if st.button("📡 Test Ping ESP Hardware", use_container_width=True):
            with st.spinner("Pinging ESP..."):
                ping_res = fetch_esp_vitals(test_ip, timeout=2.0)
                if ping_res["success"]:
                    st.success(f"✅ **ESP Online!** Latency: `{ping_res['latency_ms']} ms` | Temp: `{ping_res['temperature']}°C` | HR: `{ping_res['heart_rate']}` | SpO2: `{ping_res['spo2']}%`")
                    st.json(ping_res["raw_response"])
                else:
                    st.error(f"❌ {ping_res['message']}")

    st.divider()
    st.markdown("##### 💻 Arduino C++ Firmware Sketch (`hardware/esp_health_screening/esp_health_screening.ino`)")
    st.caption("Upload this exact sketch in Arduino IDE. Works on both ESP32 and ESP8266.")
    
    ino_path = Path(__file__).parent.parent / "hardware" / "esp_health_screening" / "esp_health_screening.ino"
    if ino_path.exists():
        st.code(ino_path.read_text(encoding="utf-8"), language="cpp")
    else:
        st.info("Firmware file located at hardware/esp_health_screening/esp_health_screening.ino")

with tab_log:
    st.markdown("##### 📜 Pre-Donation Screening History & Manual Override")
    st.dataframe(
        screenings_df[[
            'screening_id', 'donor_id', 'donor_name', 'screening_datetime', 
            'temperature', 'heart_rate', 'spo2', 'systolic_bp', 'diastolic_bp', 
            'preliminary_status', 'review_notes', 'evaluated_by'
        ]],
        use_container_width=True,
        hide_index=True
    )

    st.divider()
    st.markdown("##### 👩‍⚕️ Authorized Medical Officer Manual Override")
    st.caption("Authorized staff may override automated rule outcomes after clinical consultation.")

    if not screenings_df.empty:
        with st.form("override_form"):
            col_o1, col_o2 = st.columns(2)
            with col_o1:
                sel_scr_id = st.selectbox("Select Screening ID to Override:", screenings_df['screening_id'].tolist())
            with col_o2:
                override_status = st.selectbox("Override Status:", [
                    "Screening Completed", 
                    "No Initial Warning Detected", 
                    "Medical Review Required", 
                    "Temporary Deferral and Reassessment"
                ])
            override_notes = st.text_area("Physician Override Rationale / Medical Notes:", placeholder="e.g. Physician evaluated donor, cleared for standard donation despite mild heart rate elevation.")

            sub_override = st.form_submit_button("Submit Physician Override", type="primary", use_container_width=True)

            if sub_override:
                if not override_notes.strip():
                    st.error("Please provide clinical rationale in the notes field for manual override.")
                else:
                    update_screening_status(sel_scr_id, override_status, f"[PHYSICIAN OVERRIDE]: {override_notes.strip()}")
                    st.success(f"Screening **{sel_scr_id}** status updated to: **{override_status}**")
                    st.rerun()
