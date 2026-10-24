# Setup guide

Two ways to run the dashboard: on a **laptop/PC** (quickest way to try it) or on the **Raspberry Pi 5** (the real prototype).
All commands are run from the repository root.

## A. Laptop / PC

```bash
git clone https://github.com/<your-username>/fruit-freshness-detection.git
cd fruit-freshness-detection

python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt

python app/server.py
```

Open <http://localhost:5000>. Use the **Camera** tab (browser webcam) or **Upload** a photo.
Click **Demo sensor** to try the gas/battery panels without the ESP32.

## B. Raspberry Pi 5

```bash
# 1. System packages (once)
sudo apt update
sudo apt install -y python3-venv python3-picamera2 python3-numpy python3-pil bluetooth bluez git

# 2. Get the code (once)
git clone https://github.com/<your-username>/fruit-freshness-detection.git
cd fruit-freshness-detection

# 3. Python environment (once)
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements-pi.txt
#   if ai-edge-litert fails:  pip install tflite-runtime

# 4. Run (every time)
source venv/bin/activate
python app/server.py --ble
```

Then open `http://localhost:5000` on the Pi, or `http://<pi-ip>:5000` from a phone/laptop on the same Wi-Fi
(the server prints the address when it starts). Stop with `Ctrl+C`.

`--ble` makes the Pi connect to the ESP32 itself and feed the readings to the dashboard.
Without it, use the **Connect sensor** button (Web Bluetooth in Chrome/Edge) or **Demo sensor**.

## C. Flash the ESP32

1. Install the Arduino IDE and the **esp32 by Espressif** board package.
2. Open `firmware/esp32_air_sensor/esp32_air_sensor.ino`.
3. Board: **ESP32 Dev Module**. Select the port and upload.
4. Open the Serial Monitor at 115200 baud: you should see `Advertising as "ESP32-AirSensor"`.
5. Calibrate (see [HARDWARE.md](HARDWARE.md#calibration)).

To check the BLE link on its own (no dashboard):

```bash
pip install bleak
python scripts/pi_receiver.py --log readings.csv
```

## D. Evaluate the model (confusion matrix + heatmaps)

1. Download the dataset from Kaggle: <https://www.kaggle.com/datasets/sriramr/fruits-fresh-and-rotten-for-classification>
2. Run:

```bash
python tools/evaluate_model.py --test-dir path/to/dataset/test --heatmaps 2
```

Output goes to `results/`: `confusion_matrix.png`, `classification_report.txt` and `heatmap_*.png`.
Check the dataset's licence on its Kaggle page before redistributing any of its images.

## Troubleshooting

| Problem | Fix |
|---|---|
| `No TFLite runtime found` | `pip install ai-edge-litert` (Pi) or `pip install tensorflow` (laptop) |
| `Missing ... fruit_model.tflite` | Run `python app/server.py` from the repo root and keep the `models/` folder |
| Sensor never connects | Is the ESP32 powered and advertising? The name must match `ESP32-AirSensor` in both the firmware and `app/server.py` |
| Pi camera tab missing | `picamera2` not installed or no camera detected; use the Upload tab instead |
| Gas readings jump around | Let the MQ-135 warm up (first ~2 minutes, ideally 24 h burn-in on first use) and set `MQ_R0` |
