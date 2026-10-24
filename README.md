<div align="center">

```
 _____ ____  _   _ ___ _____   _____ ____  _____ ____  _   _ _   _ _____ ____ ____
|  ___|  _ \| | | |_ _|_   _| |  ___|  _ \| ____/ ___|| | | | \ | | ____/ ___/ ___|
| |_  | |_) | | | || |  | |   | |_  | |_) |  _| \___ \| |_| |  \| |  _| \___ \___ \
|  _| |  _ <| |_| || |  | |   |  _| |  _ <| |___ ___) |  _  | |\  | |___ ___) |__) |
|_|   |_| \_\\___/|___| |_|   |_|   |_| \_\_____|____/|_| |_|_| \_|_____|____/____/

```

# Fruit Freshness Detection using AI and Gas Sensing

**A portable edge-AI system that tells fresh fruit from rotten fruit, runs fully offline on a Raspberry Pi 5, and watches the air with an ESP32 + MQ-135 gas sensor.**

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![TensorFlow Lite](https://img.shields.io/badge/TensorFlow%20Lite-INT8-FF6F00?logo=tensorflow&logoColor=white)
![MobileNetV2](https://img.shields.io/badge/Model-MobileNetV2-4c9be8)
![Raspberry Pi 5](https://img.shields.io/badge/Raspberry%20Pi-5-C51A4A?logo=raspberrypi&logoColor=white)
![ESP32](https://img.shields.io/badge/ESP32-BLE-E7352C?logo=espressif&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-Dashboard-000000?logo=flask&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

</div>

---

## Table of contents

1. [Overview](#overview)
2. [Features](#features)
3. [How it works](#how-it-works)
4. [The model](#the-model)
5. [Hardware](#hardware)
6. [Repository structure](#repository-structure)
7. [Quick start](#quick-start)
8. [Using the dashboard](#using-the-dashboard)
9. [Evaluating the model](#evaluating-the-model)
10. [Results and limitations](#results-and-limitations)
11. [Roadmap](#roadmap)
12. [Dataset and acknowledgements](#dataset-and-acknowledgements)
13. [License](#license)

---

## Overview

Spoiled fruit means food waste and lost money, and judging freshness by eye is inconsistent. This project puts a small
image classifier and a gas sensor into one portable prototype:

* A **webcam** photographs the fruit.
* A **MobileNetV2** model running locally on a **Raspberry Pi 5** classifies it into one of six classes
  (fresh / rotten apple, banana, orange).
* An **ESP32** reads an **MQ-135** gas sensor and the battery voltage and sends them to the Pi over **Bluetooth Low Energy**.
* A **Flask web dashboard** shows the prediction, confidence, live sensor readings and a printable batch report.

No internet connection is needed once it is set up.

## Features

* **Six-class fruit-condition classifier**: fresh and rotten apples, bananas and oranges.
* **Runs offline on the edge**: a 2.72 MB INT8-quantized TensorFlow Lite model.
* **Honest uncertainty**: predictions below **60 % confidence** are shown as *Uncertain* instead of forcing a label.
* **Live gas and battery monitoring** over BLE (ESP32 + MQ-135, 3S Li-ion pack).
* **Web dashboard**: browser webcam, photo upload or Raspberry Pi camera, live charts, dark mode.
* **Batch reports**: collects samples and issues an **Accept / Review / Reject** recommendation, exportable as CSV, PDF or HTML.
* **Automatic logging**: every analysed photo is saved with its result and sensor values in `captures/log.csv`.
* **Demo mode**: simulated sensor data so the dashboard can be tried without any hardware.

## How it works

```
   +-----------+     +--------------------------------+     +----------------------+
   |  Webcam   |---->|        Raspberry Pi 5          |---->|  Web dashboard       |
   | (USB 1080p)|    |                                |     |  (any browser, LAN)  |
   +-----------+     |  Flask server (app/server.py)  |     |                      |
                     |   |                            |     |  * prediction        |
                     |   +--> MobileNetV2 (TFLite)    |     |  * confidence        |
                     |   |    224x224 -> 6 classes    |     |  * live gas/battery  |
                     |   |                            |     |  * batch report      |
                     |   +--> captures/log.csv        |     +----------------------+
                     +---------------^----------------+
                                     | BLE (JSON, every 2 s)
                          +----------+-----------+
                          |        ESP32         |
                          |  MQ-135  +  battery  |
                          |  monitor (3S Li-ion) |
                          +----------------------+
```

1. The fruit image is resized to 224 x 224 and passed to the classifier (input scaling is built into the model).
2. The model returns six class probabilities; the top class and its confidence are shown.
3. If the top confidence is below 60 %, the result is marked **Uncertain**.
4. In parallel the ESP32 streams `{"ppm", "mq_v", "rs", "bat_v", "bat_pct", ...}` over BLE. The dashboard shows the gas
   reading next to each prediction and stores both in the log. The gas reading is **not** an input to the image model.

Sensor message sent by the ESP32:

```json
{"mq_v":1.234,"rs":3.12,"ppm":512,"bat_v":12.31,"bat_pct":92,"warm":1,"up":356}
```

## The model

| | |
|---|---|
| Architecture | MobileNetV2 (ImageNet pre-trained) + global average pooling + dropout 0.2 + 6-way softmax |
| Parameters | about 2.27 million |
| Input | 224 x 224 x 3 RGB, raw 0-255 pixels (scaling is inside the model) |
| Output | 6 probabilities: `freshapples`, `freshbanana`, `freshoranges`, `rottenapples`, `rottenbanana`, `rottenoranges` |
| Deployed file | `models/fruit_model.tflite`, about 2.72 MB, integer-quantized weights, float32 input/output |
| Training data | Public Kaggle dataset *Fruits Fresh and Rotten for Classification* (10,901 training/validation images, 85:15 split; separate test split of 2,698 images) |
| Confidence rule | Below 60 % shows as *Uncertain* (`MIN_CONF` in `app/server.py`) |

## Hardware

| Part | Purpose |
|---|---|
| Raspberry Pi 5 (8 GB) | Runs the classifier and the dashboard |
| Lenovo FHD USB webcam | Image capture |
| ESP32 DevKit | Reads MQ-135 and battery voltage, BLE transmitter |
| MQ-135 gas sensor | Supplementary gas reading |
| 3S Li-ion pack + 3S BMS + 12 V to 5 V buck converter | Portable power |
| ABS enclosure + exhaust fan | Sample chamber (about 13.6 L) with ventilation |

Wiring diagram, resistor dividers, power and calibration notes: **[docs/HARDWARE.md](docs/HARDWARE.md)**.

> **Warning:** do not wire an MQ-135 module powered from 5 V straight into an ESP32 pin. Use the 10k/15k divider described in the hardware guide.

## Repository structure

```
fruit-freshness-detection/
|-- README.md
|-- LICENSE
|-- .gitignore
|-- requirements.txt            # core dependencies
|-- requirements-pi.txt         # Raspberry Pi (LiteRT + BLE)
|-- requirements-dev.txt        # laptop + evaluation tools
|
|-- app/
|   |-- server.py               # Flask server: inference, camera, BLE link, logging
|   `-- dashboard.html          # single-page dashboard (served by server.py)
|
|-- models/
|   |-- fruit_model.tflite      # quantized MobileNetV2 classifier
|   `-- labels.txt              # the 6 class names, in model output order
|
|-- firmware/
|   `-- esp32_air_sensor/
|       `-- esp32_air_sensor.ino   # ESP32 BLE sensor node (MQ-135 + battery)
|
|-- scripts/
|   `-- pi_receiver.py          # stand-alone BLE receiver / CSV logger (for testing the sensor)
|
|-- tools/
|   `-- evaluate_model.py       # confusion matrix, classification report, heatmaps
|
`-- docs/
    |-- SETUP.md                # laptop, Raspberry Pi and ESP32 setup + troubleshooting
    |-- HARDWARE.md             # BOM, wiring, power, calibration, enclosure
    `-- images/                 # put your photos and screenshots here
```

## Quick start

```bash
git clone https://github.com/<your-username>/fruit-freshness-detection.git
cd fruit-freshness-detection

python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt

python app/server.py
```

Open **http://localhost:5000**, choose the *Camera* or *Upload* tab and analyse a fruit photo.
Press **Demo sensor** to see the gas/battery panels without any hardware.

On the Raspberry Pi use `pip install -r requirements-pi.txt` and `python app/server.py --ble`.
Full instructions (Pi packages, flashing the ESP32, troubleshooting) are in **[docs/SETUP.md](docs/SETUP.md)**.

## Using the dashboard

1. **Capture**: take a photo with the browser camera, upload one, or use the Pi camera tab.
2. **Preview**: check the prediction (fruit, fresh/rotten, confidence, top-3 scores) and the sensor values at that moment.
3. **Add to report**: repeat for each fruit in the batch.
4. **Generate final report**: get a batch recommendation.

| Recommendation | Rule |
|---|---|
| **Accept** | No rotten and no uncertain samples |
| **Review** | Some rotten samples (at most 20 %) or any uncertain sample |
| **Reject** | More than 20 % of classified samples are rotten |

The air-quality tile uses these bands on the ppm estimate: `< 800` Good, `800-1200` Moderate, `1200-2000` Poor, `> 2000` Very poor.
Reports can be printed / saved as PDF or downloaded as HTML, and the sample table exported as CSV.

## Evaluating the model

```bash
python tools/evaluate_model.py --test-dir path/to/dataset/test --heatmaps 2
```

Creates in `results/`: a **confusion matrix** (counts and normalised), a per-class **precision / recall / F1** report,
and **occlusion-sensitivity heatmaps** that show which part of the fruit the model relies on.

## Results and limitations

This is a **working prototype**, not a validated measuring instrument.

| Measure | Status |
|---|---|
| Preliminary functional test (10 images, 5 fresh + 5 rotten) | 10 / 10 correct, mean confidence 98.2 % (range 87.1 % to 99.6 %) |
| Full held-out evaluation (2,698 images) | Run `tools/evaluate_model.py` and add the numbers here |
| Raspberry Pi inference time / capture-to-result time | To be measured |
| Battery runtime | To be measured |

Known limitations:

* The ten-image test is too small to estimate general accuracy; the images were not independent fruit specimens.
* The model was trained on dataset photos, so different lighting, backgrounds and fruit varieties can reduce accuracy.
* The MQ-135 responds to many gases and to temperature and humidity. Its `ppm` value is a rough CO2-equivalent
  estimate, not a calibrated concentration, and needs warm-up and clean-air calibration (see the hardware guide).
* Confidence is a model output, not a guarantee that a prediction is correct.

## Roadmap

- [ ] Publish full held-out test metrics and confusion matrix
- [ ] Add a "no fruit in frame" check before classification
- [ ] Controlled gas experiment: fresh vs rotten, repeated across independent fruits
- [ ] Measure inference time, capture-to-result time and battery runtime
- [ ] Support more fruit types

<!--
## Gallery
Uncomment after adding your own images to docs/images/ (see docs/images/README.md).

![Prototype](docs/images/prototype.jpg)
![Dashboard](docs/images/dashboard.png)
![Confusion matrix](docs/images/confusion_matrix.png)
-->

## Dataset and acknowledgements

* Training images: [Fruits Fresh and Rotten for Classification](https://www.kaggle.com/datasets/sriramr/fruits-fresh-and-rotten-for-classification) on Kaggle.
  The dataset is **not** included in this repository; check its licence on the Kaggle page before reusing the images.
* Sandler, M., Howard, A., Zhu, M., Zhmoginov, A., Chen, L.-C. (2018). *MobileNetV2: Inverted Residuals and Linear Bottlenecks.* CVPR. <https://doi.org/10.1109/CVPR.2018.00474>
* Built with TensorFlow / TensorFlow Lite (LiteRT), Flask, Pillow, NumPy and Bleak.

## License

Released under the [MIT License](LICENSE).
