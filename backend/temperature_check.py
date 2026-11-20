"""
Backend Service: Temperature & Vital Signs Blood Donation Eligibility Checker.
Directly implements and runs the HealthScreeningDemo.java logic.
"""

import subprocess
import shutil
from pathlib import Path

# Correct Blood Donation Clinical Reference Ranges
MIN_ELIGIBLE_TEMP = 36.0  # Minimum safe body temperature (°C)
MAX_ELIGIBLE_TEMP = 37.5  # Maximum safe body temperature (°C)
FEVER_ALERT_TEMP = 38.0   # Definite fever threshold (°C) from HealthScreeningDemo.java

def check_temperature_eligibility(temperature_c: float) -> dict:
    """
    Checks if a donor's body temperature is correct ('crt') and eligible for blood donation.
    
    Standard Blood Banking Standards:
    - Normal / Eligible: 36.1°C to 37.5°C (97.0°F - 99.5°F)
    - Warning / High Temperature: >= 38.0°C (Ineligible - Pyrexia / Active infection)
    - Borderline / Review: 37.6°C to 37.9°C (Mild elevation, re-measure in 15 mins)
    - Low Temperature: < 36.0°C (Hypothermia check required)
    """
    is_valid = 30.0 <= temperature_c <= 45.0
    if not is_valid:
        return {
            "eligible": False,
            "status": "INVALID",
            "message": "Temperature reading outside physiological boundary (30°C - 45°C).",
            "temperature": temperature_c
        }

    if temperature_c >= FEVER_ALERT_TEMP:
        return {
            "eligible": False,
            "status": "INELIGIBLE_FEVER",
            "warning": "WARNING: High body temperature.",
            "message": f"Temperature {temperature_c:.1f}°C is elevated (>= {FEVER_ALERT_TEMP}°C). Donor has a fever and is temporarily deferred.",
            "temperature": temperature_c
        }
    elif temperature_c > MAX_ELIGIBLE_TEMP:
        return {
            "eligible": False,
            "status": "BORDERLINE_ELEVATED",
            "warning": "WARNING: Mildly elevated body temperature.",
            "message": f"Temperature {temperature_c:.1f}°C is above optimal threshold (37.5°C). Medical rest and re-screening recommended.",
            "temperature": temperature_c
        }
    elif temperature_c < MIN_ELIGIBLE_TEMP:
        return {
            "eligible": False,
            "status": "LOW_TEMPERATURE",
            "warning": "WARNING: Below normal body temperature.",
            "message": f"Temperature {temperature_c:.1f}°C is below standard reference range (< {MIN_ELIGIBLE_TEMP}°C). Clinical review required.",
            "temperature": temperature_c
        }
    else:
        return {
            "eligible": True,
            "status": "ELIGIBLE",
            "warning": None,
            "message": f"Temperature {temperature_c:.1f}°C is within normal blood donation parameters (36.0°C - 37.5°C).",
            "temperature": temperature_c
        }


def run_health_screening_backend(heart_rate: float, temperature: float, spo2: float) -> dict:
    """
    Executes the exact HealthScreeningDemo backend process:
    - Checks validity:
      heartRate < 30 || heartRate > 220
      temperature < 30 || temperature > 45
      spo2 < 50 || spo2 > 100
    - Warnings:
      heartRate < 60 || heartRate > 100
      temperature >= 38.0
      spo2 < 95
    - Status:
      alert ? 'NEEDS MEDICAL REVIEW' : 'NO BASIC SCREENING ALERTS'
    """
    java_bin = shutil.which("java")
    java_file = Path(__file__).parent / "HealthScreeningDemo.java"

    # If Java runtime is installed, attempt native execution
    if java_bin and java_file.exists():
        try:
            stdin_input = f"{heart_rate}\n{temperature}\n{spo2}\n"
            proc = subprocess.run(
                [java_bin, str(java_file)],
                input=stdin_input,
                text=True,
                capture_output=True,
                timeout=5
            )
            if proc.returncode == 0:
                raw_output = proc.stdout.strip()
                alert = ("STATUS: NEEDS MEDICAL REVIEW" in raw_output)
                return {
                    "is_valid": "Invalid input readings." not in raw_output,
                    "alert": alert,
                    "status": "NEEDS MEDICAL REVIEW" if alert else "NO BASIC SCREENING ALERTS",
                    "output_log": raw_output,
                    "executed_via": "Native Java JVM (HealthScreeningDemo.java)"
                }
        except Exception:
            pass

    # Pure Python Engine identical to HealthScreeningDemo.java
    lines = []
    lines.append("==================================")
    lines.append(" BLOOD DONOR HEALTH SCREENING")
    lines.append("==================================")
    lines.append(f"Enter Heart Rate (BPM): {heart_rate}")
    lines.append(f"Enter Body Temperature (C): {temperature}")
    lines.append(f"Enter SpO2 Level (%): {spo2}")

    # Boundary check from HealthScreeningDemo.java
    if (heart_rate < 30 or heart_rate > 220 or
        temperature < 30 or temperature > 45 or
        spo2 < 50 or spo2 > 100):
        lines.append("\nInvalid input readings.")
        return {
            "is_valid": False,
            "alert": True,
            "status": "INVALID READINGS",
            "output_log": "\n".join(lines),
            "executed_via": "HealthScreeningDemo Process Engine"
        }

    lines.append("\n========== SCREENING REPORT ==========")
    lines.append(f"Heart Rate  : {heart_rate} BPM")
    lines.append(f"Temperature : {temperature} C")
    lines.append(f"SpO2 Level  : {spo2} %")

    alert = False
    warnings = []
    lines.append("\n========== SCREENING RESULT ==========")

    if heart_rate < 60 or heart_rate > 100:
        lines.append("WARNING: Heart rate outside general resting range.")
        warnings.append("Heart rate outside general resting range (60-100 BPM).")
        alert = True

    if temperature >= 38.0:
        lines.append("WARNING: High body temperature.")
        warnings.append("High body temperature (>= 38.0°C). Possible pyrexia/infection.")
        alert = True

    if spo2 < 95:
        lines.append("WARNING: Low oxygen saturation.")
        warnings.append("Low oxygen saturation (SpO2 < 95%).")
        alert = True

    if alert:
        lines.append("\nSTATUS: NEEDS MEDICAL REVIEW")
        lines.append("Professional assessment is required.")
        final_status = "NEEDS MEDICAL REVIEW"
    else:
        lines.append("\nSTATUS: NO BASIC SCREENING ALERTS")
        lines.append("Proceed to professional donor assessment.")
        final_status = "NO BASIC SCREENING ALERTS"

    lines.append("\nNote: This is a prototype only.")
    lines.append("It does not medically approve a donor.")

    return {
        "is_valid": True,
        "alert": alert,
        "warnings": warnings,
        "status": final_status,
        "output_log": "\n".join(lines),
        "executed_via": "HealthScreeningDemo Process Engine (backend/HealthScreeningDemo.java)"
    }

