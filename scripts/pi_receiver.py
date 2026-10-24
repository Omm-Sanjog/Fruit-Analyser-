#!/usr/bin/env python3
"""
Raspberry Pi 5: receive MQ135 + battery data from the ESP32 over BLE and print it.

Install (once):
    sudo apt install -y bluetooth bluez
    python3 -m venv ~/sensor-venv && source ~/sensor-venv/bin/activate
    pip install bleak

Run:
    python3 pi_receiver.py                # print readings
    python3 pi_receiver.py --log data.csv # also save them to a CSV file
"""
import argparse
import asyncio
import csv
import json
import os
from datetime import datetime

from bleak import BleakClient, BleakScanner

DEVICE_NAME = "ESP32-AirSensor"                          # must match the ESP32 code
TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"    # ESP32 -> Pi notifications

FIELDS = ["time", "ppm", "mq_v", "rs", "bat_v", "bat_pct", "warm", "up"]


def air_label(ppm):
    """Very rough label for the MQ135 CO2-equivalent estimate."""
    if ppm < 0:
        return "no reading"
    if ppm < 800:
        return "Good"
    if ppm < 1200:
        return "Moderate"
    if ppm < 2000:
        return "Poor"
    return "Very poor"


class Receiver:
    def __init__(self, log_path=None):
        self.log_path = log_path
        if log_path and not os.path.exists(log_path):
            with open(log_path, "w", newline="") as f:
                csv.writer(f).writerow(FIELDS)

    def on_data(self, _sender, data: bytearray):
        now = datetime.now().strftime("%H:%M:%S")
        text = data.decode("utf-8", errors="replace").strip()
        try:
            d = json.loads(text)
        except json.JSONDecodeError:
            print(f"[{now}] Could not parse (message cut short? check MTU): {text!r}")
            return

        warm_note = "" if d.get("warm") else "  (sensor warming up)"
        print(
            f"[{now}]  Air: {d['ppm']:>6.0f} ppm ({air_label(d['ppm'])}) | "
            f"MQ135 {d['mq_v']:.2f} V, Rs {d['rs']:.1f} kΩ | "
            f"Battery: {d['bat_v']:.2f} V ({d['bat_pct']}%){warm_note}"
        )

        if self.log_path:
            d["time"] = datetime.now().isoformat(timespec="seconds")
            with open(self.log_path, "a", newline="") as f:
                csv.writer(f).writerow([d.get(k, "") for k in FIELDS])

    async def run(self):
        while True:
            print(f"Scanning for '{DEVICE_NAME}'...")
            device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10.0)
            if device is None:
                print("  Not found. Is the ESP32 powered and advertising? Retrying...")
                continue

            disconnected = asyncio.Event()
            try:
                async with BleakClient(device, disconnected_callback=lambda _c: disconnected.set()) as client:
                    print(f"Connected to {device.address} (MTU {client.mtu_size}). Receiving data...\n")
                    await client.start_notify(TX_CHAR_UUID, self.on_data)
                    await disconnected.wait()
                    print("\nDisconnected.")
            except Exception as e:
                print(f"Connection error: {e}")
            await asyncio.sleep(2)   # then scan and reconnect


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", help="save readings to this CSV file")
    args = ap.parse_args()
    try:
        asyncio.run(Receiver(args.log).run())
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
