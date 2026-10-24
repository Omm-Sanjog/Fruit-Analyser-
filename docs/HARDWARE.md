# Hardware

## Bill of materials

| Part | Purpose |
|---|---|
| Raspberry Pi 5 (8 GB) | Runs the classifier and the dashboard server |
| Lenovo FHD USB webcam (1080p) | Captures the fruit image (the dashboard requests 720p) |
| ESP32 DevKit (classic) | Reads the gas sensor + battery voltage, sends them over BLE |
| MQ-135 gas sensor module | Supplementary gas reading |
| 3S Li-ion battery pack + 3S BMS | Portable power (9.0 V empty to 12.6 V full) |
| Buck converter (12 V to 5 V) | Powers the Pi / ESP32 / MQ-135 from the pack |
| Resistors: 32 kΩ, 7.5 kΩ, 10 kΩ, 15 kΩ | Battery divider and MQ-135 output divider |
| ABS enclosure + exhaust fan | Defined sample area and ventilation |

## Wiring (ESP32)

```
                         MQ-135 module
                      +-------------------+
        5V ---------- | VCC           AO  |----[ 10k ]----+---- GPIO34 (ADC1)
       GND ---------- | GND               |                |
                      +-------------------+             [ 15k ]
                                                           |
                                                          GND

   Battery + ----[ 32k ]----+---- GPIO35 (ADC1)
                            |
                         [ 7.5k ]
                            |
   Battery - ---------------+---- GND   (battery, MQ-135 and ESP32 grounds must be common)
```

* Use **ADC1 pins only** (GPIO32 to 39). ADC2 does not work while Bluetooth is on.
* **Never connect the MQ-135 `AO` pin straight to the ESP32** when the module runs on 5 V: AO can reach about 5 V and the ESP32 ADC tolerates 3.3 V. The 10k/15k divider gives 3.0 V at 5 V.
* With that divider set `MQ_AO_RATIO = 1.667` in the firmware (`(10k + 15k) / 15k`). With no divider leave it at `1.0`.
* Battery divider ratio: `(32k + 7.5k) / 7.5k = 5.27`, so a full 3S pack (12.6 V) reads 2.39 V at the pin.

## Power

* The 3S BMS sits between the cells and everything else; take the pack output from the BMS `P+ / P-` pads.
* Charge with a **12.6 V CC/CV charger** connected to the BMS charge input.
* Step the pack down to 5 V with a buck converter (not a linear regulator, which would run hot at 12 V).
* Battery percentage is mapped linearly from `BAT_EMPTY_V = 9.0` (0 %) to `BAT_FULL_V = 12.6` (100 %).

## Calibration

The MQ-135 needs a warm-up and a clean-air baseline before its numbers mean anything.

1. Power it for a long first burn-in (commonly 24 h) and at least 2 minutes before every session (`MQ_WARMUP_MS`).
2. Leave it in fresh air. The Serial Monitor prints `MQ135 R0 estimate for clean air`.
3. Copy that value into `MQ_R0` in the firmware and re-flash.
4. Set `MQ_RL` to the load resistor on your module (`102` = 1 kΩ, `103` = 10 kΩ).
5. Compare `BAT_CAL` against a multimeter reading and adjust until they agree.

**Note on units:** the reported `ppm` is a rough CO2-equivalent estimate from a generic MQ-135 curve. The MQ-135 responds to many gases and to temperature and humidity, so treat it as a relative index, not a calibrated concentration.

## Enclosure

* External size about 342 x 212 x 212 mm, 6 mm ABS panels with 3D-printed tab-and-slot joints.
* Inner chamber about 330 x 200 x 206 mm (about 13.6 L), open front for loading fruit.
* MQ-135 sits close to the sample; Pi, ESP32 and battery are mounted on the roof, outside the sample volume.
* Keep the opening, fan state, ventilation time and exposure time the same between trials.
