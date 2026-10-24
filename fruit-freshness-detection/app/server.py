#!/usr/bin/env python3
"""
Fruit Freshness Dashboard - server

Repository layout it expects:
    app/server.py   app/dashboard.html   models/fruit_model.tflite   models/labels.txt

Run (from the repository root):
    python app/server.py            # then open http://localhost:5000
    python app/server.py --ble      # also read the ESP32 sensor from this machine (e.g. the Raspberry Pi)

Every analysed photo is saved in ./captures together with a log.csv of results and sensor readings.
"""
import argparse
import asyncio
import base64
import csv
import io
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime

import numpy as np
from flask import Flask, jsonify, request, send_file
from PIL import Image, ImageOps

# ---------- TFLite runtime: LiteRT (Pi) -> tflite-runtime -> TensorFlow (laptop) ----------
try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    try:
        from tflite_runtime.interpreter import Interpreter
    except ImportError:
        try:
            import tensorflow as tf
            Interpreter = tf.lite.Interpreter
        except ImportError:
            sys.exit("No TFLite runtime found. Install one:  pip install ai-edge-litert   (or: pip install tensorflow)")

HERE = os.path.dirname(os.path.abspath(__file__))        # .../app
ROOT = os.path.dirname(HERE)                             # repository root
MODEL = os.path.join(ROOT, "models", "fruit_model.tflite")
LABELS = os.path.join(ROOT, "models", "labels.txt")
PAGE = os.path.join(HERE, "dashboard.html")
CAPTURE_DIR = os.path.join(ROOT, "captures")
MIN_CONF = 0.60

ESP32_NAME = "ESP32-AirSensor"
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

SENSOR_KEYS = ["ppm", "mq_v", "rs", "bat_v", "bat_pct", "warm", "up"]


def split_label(label):
    """'freshapples' -> ('Apple', 'Fresh')"""
    label = label.lower()
    for s in ("fresh", "rotten"):
        if label.startswith(s):
            return label[len(s):].rstrip("s").strip("_ ").capitalize(), s.capitalize()
    return label.capitalize(), "?"


# ---------- Image classifier ----------
class Classifier:
    def __init__(self):
        for f in (MODEL, LABELS):
            if not os.path.exists(f):
                sys.exit(f"Missing {f} - keep the models/ folder in the repository root")
        self.labels = [l.strip() for l in open(LABELS) if l.strip()]
        self.interp = Interpreter(model_path=MODEL, num_threads=4)
        self.interp.allocate_tensors()
        self.inp = self.interp.get_input_details()[0]
        self.out = self.interp.get_output_details()[0]
        _, self.h, self.w, _ = self.inp["shape"]
        self.lock = threading.Lock()

    def predict(self, img: Image.Image):
        img = ImageOps.exif_transpose(img).convert("RGB")
        x = np.asarray(img.resize((int(self.w), int(self.h))), dtype=np.float32)[None]
        if self.inp["dtype"] != np.float32:
            scale, zero = self.inp["quantization"]
            x = (x / scale + zero).astype(self.inp["dtype"])
        with self.lock:
            self.interp.set_tensor(self.inp["index"], x)
            t = time.perf_counter()
            self.interp.invoke()
            ms = (time.perf_counter() - t) * 1000
            probs = self.interp.get_tensor(self.out["index"])[0].astype(np.float32).copy()
        if self.out["dtype"] != np.float32:
            scale, zero = self.out["quantization"]
            probs = (probs - zero) * scale

        order = np.argsort(probs)[::-1]
        scores = []
        for i in order:
            fruit, state = split_label(self.labels[i])
            scores.append({"label": self.labels[i], "fruit": fruit, "state": state, "p": float(probs[i])})
        best = scores[0]
        uncertain = best["p"] < MIN_CONF
        return {
            "label": best["label"],
            "fruit": best["fruit"],
            "state": "Uncertain" if uncertain else best["state"],
            "guess_state": best["state"],
            "confidence": best["p"],
            "uncertain": uncertain,
            "scores": scores,
            "ms": round(ms, 1),
        }


# ---------- Optional Raspberry Pi camera ----------
class PiCamera:
    def __init__(self):
        self.cam = None
        self.available = False
        self.lock = threading.Lock()
        try:
            from picamera2 import Picamera2
            self.Picamera2 = Picamera2
            self.available = len(Picamera2.global_camera_info()) > 0
        except Exception:
            pass

    def capture(self) -> Image.Image:
        with self.lock:
            if self.cam is None:
                cam = self.Picamera2()
                cam.configure(cam.create_still_configuration(main={"size": (1024, 768), "format": "RGB888"}))
                cam.start()
                time.sleep(1.5)  # let exposure settle
                self.cam = cam
            frame = self.cam.capture_array()  # RGB888 = BGR byte order
        return Image.fromarray(frame[:, :, ::-1])


# ---------- Optional ESP32 sensor read by the server (use with --ble) ----------
class SensorLink:
    def __init__(self):
        self.latest = None
        self.t = 0.0
        self.connected = False

    def start(self):
        threading.Thread(target=lambda: asyncio.run(self._run()), daemon=True).start()

    def _on_data(self, _sender, data):
        try:
            self.latest = json.loads(data.decode("utf-8"))
            self.t = time.time()
        except Exception:
            pass

    async def _run(self):
        from bleak import BleakClient, BleakScanner
        while True:
            try:
                dev = await BleakScanner.find_device_by_name(ESP32_NAME, timeout=10.0)
                if dev is not None:
                    done = asyncio.Event()
                    async with BleakClient(dev, disconnected_callback=lambda _c: done.set()) as client:
                        self.connected = True
                        print(f"[sensor] connected to {dev.address}")
                        await client.start_notify(TX_UUID, self._on_data)
                        await done.wait()
                    print("[sensor] disconnected")
            except Exception as e:
                print(f"[sensor] {e}")
            self.connected = False
            await asyncio.sleep(2)

    def snapshot(self):
        if self.latest and time.time() - self.t < 15:
            return dict(self.latest)
        return None


# ---------- Save every analysed photo + a CSV log ----------
LOG_FIELDS = ["time", "file", "fruit", "state", "confidence"] + SENSOR_KEYS


def save_capture(img: Image.Image, result: dict, sensor):
    os.makedirs(CAPTURE_DIR, exist_ok=True)
    now = datetime.now()
    name = f"{now:%Y%m%d_%H%M%S}_{now.microsecond // 1000:03d}_{result['fruit']}_{result['state']}.jpg".lower()
    img.convert("RGB").save(os.path.join(CAPTURE_DIR, name), quality=90)
    log = os.path.join(CAPTURE_DIR, "log.csv")
    new = not os.path.exists(log)
    with open(log, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_FIELDS)
        s = sensor or {}
        w.writerow([now.isoformat(timespec="seconds"), name, result["fruit"], result["state"],
                    f"{result['confidence']:.4f}"] + [s.get(k, "") for k in SENSOR_KEYS])
    return name


def parse_sensor(form_value):
    """Sensor snapshot sent by the browser (JSON), if any."""
    if not form_value:
        return None
    try:
        d = json.loads(form_value)
        return {k: d[k] for k in SENSOR_KEYS if k in d} or None
    except Exception:
        return None


# ---------- Web app ----------
def create_app(clf, cam, sensor):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

    @app.get("/")
    def index():
        return send_file(PAGE)

    @app.get("/api/info")
    def info():
        return jsonify(model=os.path.basename(MODEL), labels=clf.labels,
                       input=[int(clf.h), int(clf.w)], min_conf=MIN_CONF,
                       camera=cam.available, ble=sensor is not None)

    @app.get("/api/sensor")
    def get_sensor():
        if sensor is None:
            return jsonify(enabled=False)
        return jsonify(enabled=True, connected=sensor.connected, reading=sensor.latest,
                       age=round(time.time() - sensor.t, 1) if sensor.t else None)

    def finish(img, sensor_data):
        if sensor_data is None and sensor is not None:
            sensor_data = sensor.snapshot()
        result = clf.predict(img)
        result["saved_as"] = save_capture(img, result, sensor_data)
        result["sensor"] = sensor_data
        result["time"] = datetime.now().isoformat(timespec="seconds")
        return result

    @app.post("/api/predict")
    def predict():
        f = request.files.get("image")
        if f is None:
            return jsonify(error="No image uploaded"), 400
        try:
            img = Image.open(f.stream)
            img.load()
        except Exception:
            return jsonify(error="That file isn't an image we can read"), 400
        return jsonify(finish(img, parse_sensor(request.form.get("sensor"))))

    @app.post("/api/capture")
    def capture():
        if not cam.available:
            return jsonify(error="No Raspberry Pi camera found on the server"), 400
        img = cam.capture()
        result = finish(img, parse_sensor(request.form.get("sensor")))
        buf = io.BytesIO()
        small = img.copy()
        small.thumbnail((1024, 1024))
        small.save(buf, "JPEG", quality=88)
        result["image"] = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        return jsonify(result)

    return app


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="Fruit Freshness Dashboard server")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = reachable from other devices on your network")
    ap.add_argument("--ble", action="store_true", help="read the ESP32 sensor from this machine (needs: pip install bleak)")
    args = ap.parse_args()

    if not os.path.exists(PAGE):
        sys.exit("Missing dashboard.html - it must sit next to server.py in app/")

    clf = Classifier()
    cam = PiCamera()
    sensor = None
    if args.ble:
        sensor = SensorLink()
        sensor.start()

    print(f"Model: {os.path.basename(MODEL)}  classes: {', '.join(clf.labels)}")
    print(f"Pi camera: {'found' if cam.available else 'not found'}  |  Sensor via server: {'on' if sensor else 'off'}")
    print(f"\nOpen  http://localhost:{args.port}  on this machine")
    ip = lan_ip()
    if ip and args.host == "0.0.0.0":
        print(f"  or  http://{ip}:{args.port}  from another device on the same Wi-Fi")
    print()
    create_app(clf, cam, sensor).run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
