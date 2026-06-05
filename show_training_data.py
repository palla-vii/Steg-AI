"""
show_training_data.py
---------------------
Run this script to visualize the synthetic training data used by StegAI.
Shows sample blocks (ml_module.py) and sample images (steg_detector.py).

Usage:
    python show_training_data.py
"""

import numpy as np
import cv2
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# ── Reproduce exactly what ml_module.py generates ──────────────────────────

np.random.seed(42)

textured_blocks, gradient_blocks, flat_blocks = [], [], []

for _ in range(600):
    block = np.random.randint(0, 256, (8, 8), dtype=np.uint8)
    textured_blocks.append(block)

for _ in range(300):
    ramp = np.tile(np.linspace(0, 200, 8), (8, 1)).astype(np.uint8)
    ramp = np.clip(ramp + np.random.randint(0, 30, (8, 8)), 0, 255).astype(np.uint8)
    gradient_blocks.append(ramp)

for _ in range(600):
    base = np.random.randint(0, 256)
    block = np.full((8, 8), base, dtype=np.uint8)
    block = np.clip(block + np.random.randint(-5, 6, (8, 8)), 0, 255).astype(np.uint8)
    flat_blocks.append(block)

# ── Reproduce what steg_detector.py generates ──────────────────────────────

def make_clean_image(H, W, rng):
    base = float(rng.randint(20, 220))
    img  = np.full((H, W), base, dtype=np.float64)
    for sigma in rng.choice([4, 8, 16, 24], size=2, replace=False):
        blob   = rng.randn(H, W) * rng.uniform(20, 60)
        smooth = cv2.GaussianBlur(blob, (0, 0), float(sigma))
        img   += smooth
    img += rng.normal(0, rng.uniform(4, 14), (H, W))
    return np.clip(img, 0, 255).astype(np.uint8)

def embed_lsb(gray, bits):
    flat     = gray.flatten().copy()
    n        = min(len(bits), len(flat))
    flat[:n] = (flat[:n] & 0xFE) | bits[:n]
    return flat.reshape(gray.shape)

rng = np.random.RandomState(42)
H, W = 128, 128
clean_samples, stego_samples = [], []
for _ in range(8):
    clean = make_clean_image(H, W, rng)
    clean_samples.append(clean)
    capacity    = H * W
    payload_len = rng.randint(int(0.40 * capacity), int(0.80 * capacity))
    bits        = rng.randint(0, 2, payload_len, dtype=np.uint8)
    stego       = embed_lsb(clean, bits)
    stego_samples.append(stego)

# ── PLOT ───────────────────────────────────────────────────────────────────

fig = plt.figure(figsize=(18, 10), facecolor="#0f0f1a")
fig.suptitle(
    "StegAI  —  Synthetic Training Data Visualizer",
    fontsize=18, color="white", fontweight="bold", y=0.97
)

gs = gridspec.GridSpec(3, 1, figure=fig, hspace=0.55)

# ── Section 1: 8×8 block samples ──────────────────────────────────────────
gs_top = gridspec.GridSpecFromSubplotSpec(1, 3, subplot_spec=gs[0], wspace=0.4)
block_groups = [
    ("Textured Blocks  (label: SAFE)", textured_blocks, "#00e5ff"),
    ("Gradient Blocks  (label: SAFE)", gradient_blocks, "#69ff47"),
    ("Flat Blocks       (label: UNSAFE)", flat_blocks,  "#ff4b6e"),
]
for col, (title, blocks, color) in enumerate(block_groups):
    inner = gridspec.GridSpecFromSubplotSpec(2, 5, subplot_spec=gs_top[col], wspace=0.1, hspace=0.1)
    ax_label = fig.add_subplot(gs_top[col])
    ax_label.set_title(title, color=color, fontsize=10, fontweight="bold", pad=28)
    ax_label.axis("off")
    for i in range(10):
        ax = fig.add_subplot(inner[i // 5, i % 5])
        ax.imshow(blocks[i], cmap="gray", vmin=0, vmax=255, interpolation="nearest")
        ax.axis("off")

# Label the section
fig.text(0.01, 0.90,
         "MODULE 1 — Random Forest Block Classifier  (ml_module.py)\n"
         "1,500 synthetic 8×8 blocks  |  5 features each  |  labels: safe=1 / unsafe=0",
         color="#aaaacc", fontsize=8.5, va="top")

# ── Section 2: 128×128 clean images ───────────────────────────────────────
gs_mid = gridspec.GridSpecFromSubplotSpec(1, 8, subplot_spec=gs[1], wspace=0.05)
fig.text(0.01, 0.60,
         "MODULE 2 — MLP Neural Detector  (steg_detector.py)\n"
         "2,000 synthetic 128×128 images  |  7 features each  |  labels: clean=0 / stego=1",
         color="#aaaacc", fontsize=8.5, va="top")
for i in range(8):
    ax = fig.add_subplot(gs_mid[i])
    ax.imshow(clean_samples[i], cmap="gray", vmin=0, vmax=255)
    ax.set_title("CLEAN", color="#69ff47", fontsize=7, pad=2)
    ax.axis("off")

# ── Section 3: 128×128 stego images ───────────────────────────────────────
gs_bot = gridspec.GridSpecFromSubplotSpec(1, 8, subplot_spec=gs[2], wspace=0.05)
for i in range(8):
    ax = fig.add_subplot(gs_bot[i])
    ax.imshow(stego_samples[i], cmap="gray", vmin=0, vmax=255)
    ax.set_title("STEGO", color="#ff4b6e", fontsize=7, pad=2)
    ax.axis("off")

plt.savefig("training_data_visualization.png", dpi=150, bbox_inches="tight",
            facecolor=fig.get_facecolor())
print("Saved -> training_data_visualization.png")
plt.show()

# ── Print a summary table ──────────────────────────────────────────────────
print("\n" + "="*60)
print("  TRAINING DATA SUMMARY")
print("="*60)
print(f"  ml_module.py  (Random Forest)")
print(f"    Textured blocks (safe)   : 600  samples")
print(f"    Gradient blocks (safe)   : 300  samples")
print(f"    Flat blocks     (unsafe) : 600  samples")
print(f"    Total                    : 1500 samples  |  5 features")
print()
print(f"  steg_detector.py  (MLP Neural Net)")
print(f"    Clean images             : 1000 samples")
print(f"    Stego images (40-80% cap): 1000 samples")
print(f"    Total                    : 2000 samples  |  7 features")
print("="*60)
print("  All data is generated synthetically at runtime using NumPy.")
print("  Seed=42 ensures 100% reproducibility.")
print("="*60)
