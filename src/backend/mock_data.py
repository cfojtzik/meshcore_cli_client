"""Mock data generator for MeshCore simulation mode."""

import time
from typing import Any, Dict, List

MOCK_INFO = """MeshCore Node Information (Simulated):
Node Name:      MeshNode-Alpha
Node MAC:       4C:75:25:AA:BB:CC
Node Role:      Companion (USB Client)
Hardware:       Heltec WiFi LoRa 32 V3 (ESP32-S3 / SX1262)
Frequency:      868.125 MHz (EU868)
Bandwidth:      250 kHz
Spreading Fact: 11
Coding Rate:    4/5
TX Power:       22 dBm
Hop Limit:      3
Battery:        4.12 V (92%)
Uptime:         3h 42m 15s
"""

MOCK_VER = "Firmware: MeshCore Companion v1.10.4-esp32s3\nProtocol: Companion Radio Protocol v2"

MOCK_TELEMETRY = """Telemetry Data (Self):
Battery Voltage: 4120 mV (92%)
Channel Util:    3.4%
Air Time (TX):   1.2%
RX Packets:      142
TX Packets:      38
Bad CRC Packets: 2
Temperature:     24.5 °C
"""

MOCK_CONTACTS = [
    {
        "name": "BaseStation-1",
        "key": "a1b2c3d4e5f60101",
        "type": "Repeater",
        "snr": "+6.5 dB",
        "rssi": "-78 dBm",
        "hops": 1,
        "path": "Direct",
        "last_seen": "2 min ago",
    },
    {
        "name": "Mobile-Bravo",
        "key": "b2c3d4e5f6a10202",
        "type": "Companion",
        "snr": "-2.0 dB",
        "rssi": "-98 dBm",
        "hops": 2,
        "path": "BaseStation-1",
        "last_seen": "8 min ago",
    },
    {
        "name": "Sensor-Weather",
        "key": "c3d4e5f6a1b20303",
        "type": "Sensor",
        "snr": "+8.0 dB",
        "rssi": "-65 dBm",
        "hops": 1,
        "path": "Direct",
        "last_seen": "1 min ago",
    },
    {
        "name": "Gateway-North",
        "key": "d4e5f6a1b2c30404",
        "type": "Repeater",
        "snr": "-5.5 dB",
        "rssi": "-104 dBm",
        "hops": 2,
        "path": "BaseStation-1",
        "last_seen": "15 min ago",
    },
]

MOCK_HEARD_NODES = [
    {
        "name": "Delta-Repeater-9",
        "key": "e5f6a1b2c3d40505",
        "type": "Repeater",
        "type_id": 2,
        "snr": "+4.0 dB",
        "rssi": "-82 dBm",
        "hops": 1,
        "path": "Direct",
        "last_heard": "vor 30s",
    },
    {
        "name": "Sensor-Forest-12",
        "key": "f6a1b2c3d4e50606",
        "type": "Sensor",
        "type_id": 4,
        "snr": "+9.5 dB",
        "rssi": "-61 dBm",
        "hops": 1,
        "path": "Direct",
        "last_heard": "vor 1m",
    },
    {
        "name": "Mobile-Echo",
        "key": "a2b3c4d5e6f70707",
        "type": "Companion",
        "type_id": 1,
        "snr": "-3.5 dB",
        "rssi": "-102 dBm",
        "hops": 2,
        "path": "BaseStation-1",
        "last_heard": "vor 4m",
    },
    {
        "name": "ClubStation-DL0",
        "key": "b3c4d5e6f7a80808",
        "type": "Repeater",
        "type_id": 2,
        "snr": "+2.0 dB",
        "rssi": "-89 dBm",
        "hops": 1,
        "path": "Direct",
        "last_heard": "vor 7m",
    },
    {
        "name": "Tracker-Bike-3",
        "key": "c4d5e6f7a8b90909",
        "type": "Sensor",
        "type_id": 4,
        "snr": "-1.0 dB",
        "rssi": "-95 dBm",
        "hops": 2,
        "path": "BaseStation-1",
        "last_heard": "vor 12m",
    },
]

MOCK_CHANNELS = [
    {"num": 0, "name": "Public (Default)", "key": "<Default MeshCore Key>"},
    {"num": 1, "name": "Emergency", "key": "SecretEmergKey999"},
    {"num": 2, "name": "Local-Team", "key": "TeamChannelKey123"},
]

MOCK_MSGS = [
    {"from": "BaseStation-1", "chan": "Public (0)", "time": "12:01", "text": "Beacon broadcast OK."},
    {"from": "Mobile-Bravo", "chan": "Public (0)", "time": "12:05", "text": "Testing signal from North Hill."},
    {"from": "Sensor-Weather", "chan": "Local-Team (2)", "time": "12:10", "text": "Temp: 19.4C, Humidity: 62%, Pressure: 1014hPa"},
]
