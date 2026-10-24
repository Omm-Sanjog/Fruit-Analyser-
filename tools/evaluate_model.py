#!/usr/bin/env python3
"""
Evaluate the deployed TFLite model on a labelled test folder.

Produces (in --out, default ./results):
    confusion_matrix.png      counts + row-normalised matrix
    classification_report.txt precision / recall / F1 per class + overall accuracy
    heatmap_<class>_*.png     occlusion-sensitivity heatmaps (where the model "looks")

The test folder must contain one sub-folder per class, e.g. the Kaggle dataset's test/ split:
    test/freshapples/*.jpg   test/rottenbanana/*.jpg   ...
Folder names are matched to models/labels.txt ignoring case, underscores and a trailing "s".

Usage (from the repository root):
    pip install -r requirements-dev.txt
    python tools/evaluate_model.py --test-dir path/to/dataset/test
    python tools/evaluate_model.py --test-dir path/to/dataset/test --heatmaps 2 --out results
"""
import argparse
import glob
import os
import random
import re
import sys

import numpy as np
from PIL import Image

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
            sys.exit("No TFLite runtime found. Run: pip install -r requirements-dev.txt")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def norm(name):
    """'freshapples' / 'fresh_apple' / 'Fresh Apple' -> 'freshapple'"""
    s = re.sub(r"[^a-z]", "", name.lower())
    return s[:-1] if s.endswith("s") else s


class Model:
    def __init__(self, model_path):
        self.interp = Interpreter(model_path=model_path)
        self.interp.allocate_tensors()
        self.inp = self.interp.get_input_details()[0]
        self.out = self.interp.get_output_details()[0]
        _, self.h, self.w, _ = self.inp["shape"]

    def load(self, path):
        return np.asarray(Image.open(path).convert("RGB").resize((int(self.w), int(self.h))), dtype=np.float32)

    def predict(self, arr):
        # Same preprocessing as app/server.py: raw 0-255 pixels (scaling is inside the model).
        x = arr[None]
        if self.inp["dtype"] != np.float32:
            scale, zero = self.inp["quantization"]
            x = (x / scale + zero).astype(self.inp["dtype"])
        self.interp.set_tensor(self.inp["index"], x)
        self.interp.invoke()
        probs = self.interp.get_tensor(self.out["index"])[0].astype(np.float32)
        if self.out["dtype"] != np.float32:
            scale, zero = self.out["quantization"]
            probs = (probs - zero) * scale
        return probs


def collect_samples(test_dir, labels):
    index = {norm(l): i for i, l in enumerate(labels)}
    samples = []
    for folder in sorted(os.listdir(test_dir)):
        path = os.path.join(test_dir, folder)
        if not os.path.isdir(path):
            continue
        if norm(folder) not in index:
            sys.exit(f"Folder '{folder}' does not match any label in labels.txt: {labels}")
        for f in sorted(glob.glob(os.path.join(path, "*"))):
            if f.lower().endswith(IMG_EXT):
                samples.append((f, index[norm(folder)]))
    if not samples:
        sys.exit(f"No images found under {test_dir}")
    return samples


def occlusion_heatmap(model, arr, patch=56, stride=28):
    """Grey out a sliding patch; the drop in confidence shows how much that region matters."""
    base = model.predict(arr)
    cls = int(np.argmax(base))
    h, w = arr.shape[:2]
    ny, nx = (h - patch) // stride + 1, (w - patch) // stride + 1
    heat = np.zeros((ny, nx), dtype=np.float32)
    for i in range(ny):
        for j in range(nx):
            occ = arr.copy()
            occ[i * stride:i * stride + patch, j * stride:j * stride + patch, :] = 127.5
            heat[i, j] = base[cls] - model.predict(occ)[cls]
    heat = np.maximum(heat, 0)
    heat /= heat.max() + 1e-8
    return heat, cls, float(base[cls])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test-dir", required=True, help="folder with one sub-folder per class")
    ap.add_argument("--model", default=os.path.join(ROOT, "models", "fruit_model.tflite"))
    ap.add_argument("--labels", default=os.path.join(ROOT, "models", "labels.txt"))
    ap.add_argument("--out", default="results", help="output folder (default: ./results)")
    ap.add_argument("--heatmaps", type=int, default=1, help="heatmaps per class (0 = skip)")
    args = ap.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns
    from sklearn.metrics import classification_report, confusion_matrix

    os.makedirs(args.out, exist_ok=True)
    labels = [l.strip() for l in open(args.labels) if l.strip()]
    model = Model(args.model)
    samples = collect_samples(args.test_dir, labels)
    print(f"{len(samples)} test images, {len(labels)} classes")

    # ---------- Confusion matrix ----------
    y_true, y_pred = [], []
    for n, (path, true_idx) in enumerate(samples, 1):
        y_pred.append(int(np.argmax(model.predict(model.load(path)))))
        y_true.append(true_idx)
        if n % 250 == 0:
            print(f"  {n}/{len(samples)}")

    idx = list(range(len(labels)))
    cm = confusion_matrix(y_true, y_pred, labels=idx)
    cm_norm = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)

    fig, ax = plt.subplots(1, 2, figsize=(16, 6))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", xticklabels=labels, yticklabels=labels, ax=ax[0])
    ax[0].set_title("Confusion matrix (counts)")
    sns.heatmap(cm_norm, annot=True, fmt=".2f", cmap="Blues", xticklabels=labels, yticklabels=labels, ax=ax[1])
    ax[1].set_title("Confusion matrix (row-normalised)")
    for a in ax:
        a.set_xlabel("Predicted")
        a.set_ylabel("True")
        a.tick_params(axis="x", rotation=45)
    plt.tight_layout()
    plt.savefig(os.path.join(args.out, "confusion_matrix.png"), dpi=300)
    plt.close()

    report = classification_report(y_true, y_pred, labels=idx, target_names=labels, digits=3, zero_division=0)
    acc = float(np.mean(np.array(y_true) == np.array(y_pred)))
    report += f"\nOverall accuracy: {acc * 100:.2f}%  ({len(samples)} images)\n"
    open(os.path.join(args.out, "classification_report.txt"), "w").write(report)
    print(report)

    # ---------- Occlusion heatmaps ----------
    random.seed(0)
    for ci, name in enumerate(labels):
        pool = [p for p, t in samples if t == ci]
        for path in random.sample(pool, min(args.heatmaps, len(pool))):
            arr = model.load(path)
            heat, cls, conf = occlusion_heatmap(model, arr)
            big = np.asarray(Image.fromarray((heat * 255).astype("uint8")).resize(
                (arr.shape[1], arr.shape[0]), Image.BICUBIC), dtype=np.float32) / 255.0
            overlay = (arr * 0.55 + plt.cm.jet(big)[..., :3] * 255 * 0.45).astype("uint8")

            fig, ax = plt.subplots(1, 3, figsize=(12, 4))
            ax[0].imshow(arr.astype("uint8")); ax[0].set_title(f"Original\nTrue: {name}")
            ax[1].imshow(big, cmap="jet");     ax[1].set_title("Occlusion heatmap")
            ax[2].imshow(overlay);             ax[2].set_title(f"Predicted: {labels[cls]} ({conf * 100:.1f}%)")
            for a in ax:
                a.axis("off")
            plt.tight_layout()
            plt.savefig(os.path.join(args.out, f"heatmap_{name}_{os.path.splitext(os.path.basename(path))[0]}.png"), dpi=300)
            plt.close()

    print(f"Saved results to {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
