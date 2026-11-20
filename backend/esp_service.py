"""
Backend Service: ESP32 / ESP8266 Microcontroller Hardware Telemetry Bridge.
Handles HTTP REST polling from ESP IoT hardware over local Wi-Fi.
"""

import requests
import time
from typing import Dict, Any, Optional

DEFAULT_ESP_IP = "192.168.4.1"  # Default SoftAP IP of ESP8266/ESP32

def clean_esp_url(ip_or_url: str) -> str:
    """Sanitize IP or URL input from user."""
    cleaned = ip_or_url.strip()
    if not cleaned.startswith("http://") and not cleaned.startswith("https://"):
        cleaned = f"http://{cleaned}"
    cleaned = cleaned.rstrip("/")
    return cleaned

def fetch_esp_vitals(ip_or_url: str, timeout: float = 2.5) -> Dict[str, Any]:
    """
    Attempts to fetch live donor vitals (Heart Rate, Temperature, SpO2) from ESP hardware.
    Expected ESP JSON response format:
    {
        "temperature": 36.8,
        "heart_rate": 74,
        "spo2": 98,
        "sensor_status": "READY",
        "device_id": "ESP32-VITALS-01"
    }
    """
    base_url = clean_esp_url(ip_or_url)
    endpoint = f"{base_url}/vitals"

    start_time = time.time()
    try:
        response = requests.get(endpoint, timeout=timeout)
        latency_ms = round((time.time() - start_time) * 1000, 1)

        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "connected": True,
                "latency_ms": latency_ms,
                "temperature": float(data.get("temperature", 36.8)),
                "heart_rate": int(data.get("heart_rate", 74)),
                "spo2": int(data.get("spo2", 98)),
                "systolic_bp": int(data.get("systolic_bp", 120)),
                "diastolic_bp": int(data.get("diastolic_bp", 80)),
                "device_id": data.get("device_id", "ESP-HEALTH-SENSOR"),
                "raw_response": data,
                "message": f"Successfully synced with ESP hardware ({latency_ms} ms)."
            }
        else:
            return {
                "success": False,
                "connected": True,
                "latency_ms": latency_ms,
                "message": f"ESP hardware replied with HTTP {response.status_code}."
            }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "connected": False,
            "message": f"Connection timed out after {timeout}s. Check if ESP IP is reachable on your Wi-Fi."
        }
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "connected": False,
            "message": f"Unable to reach {endpoint}. Make sure your PC and ESP are on the same Wi-Fi / Hotspot network."
        }
    except Exception as e:
        return {
            "success": False,
            "connected": False,
            "message": f"Error communicating with ESP hardware: {str(e)}"
        }

