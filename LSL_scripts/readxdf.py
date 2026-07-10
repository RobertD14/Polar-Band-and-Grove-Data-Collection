import pyxdf
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import numpy as np
import tkinter as tk
from tkinter import filedialog


def choose_xdf_file() -> str:
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    path = filedialog.askopenfilename(
        title='Select an XDF file',
        filetypes=[('XDF files', '*.xdf'), ('All files', '*.*')],
        initialdir='.'
    )
    root.destroy()
    if not path:
        raise SystemExit('No file selected.')
    return path


# ------------------------------
# XDF_file
# ------------------------------
fname = choose_xdf_file()
streams, header = pyxdf.load_xdf(fname)


# ------------------------------
# streams selection
# ------------------------------
def parse_selection(selection: str, max_index: int) -> list[int]:
    selection = selection.strip().lower()
    if not selection or selection == 'all':
        return list(range(max_index + 1))

    parts = [part.strip() for part in selection.split(',') if part.strip()]
    indices: set[int] = set()
    for part in parts:
        if '-' in part:
            start_str, end_str = part.split('-', 1)
            start = int(start_str)
            end = int(end_str)
            if start > end:
                raise ValueError('Invalid interval')
            indices.update(range(start, end + 1))
        else:
            indices.add(int(part))

    if any(i < 0 or i > max_index for i in indices):
        raise IndexError('Stream index out of bounds.')

    return sorted(indices)


streams_signal = [s for s in streams]
streams_signal.sort(key=lambda s: (s["info"]["name"][0].lower(),
                                   s["info"]["source_id"][0].lower()))

print(f"\nStreams available ({len(streams_signal)}) :")
for i, s in enumerate(streams_signal):
    name = s["info"]["name"][0]
    source = s["info"]["source_id"][0]
    ts = np.array(s["time_series"], dtype=object)
    print(f"  {i}: {name} | {source} | shape: {ts.shape}")

selection = input("Choose the streams you want to display (ex: all, 0, 0-2, 0,3) : ").strip()
selected_indices = parse_selection(selection, len(streams_signal) - 1)
selected_streams = [streams_signal[i] for i in selected_indices]

print(f"\nVisualisation of {len(selected_streams)} stream(s) : {selected_indices}")


# ------------------------------
# plot configuration
# ------------------------------
n_chanel = len(selected_streams)
fig, axes = plt.subplots(n_chanel, 1, figsize=(12, 2 * n_chanel), sharex=True)

if n_chanel == 1:
    axes = [axes]

selected_t_start = min(s["time_stamps"][0] for s in selected_streams)


# ------------------------------
# principal loop
# ------------------------------
for ax, s in zip(axes, selected_streams):

    name = s["info"]["name"][0]
    source = s["info"]["source_id"][0]

    # Temps normalisé
    time = s["time_stamps"] - selected_t_start

    # Charger les données
    ts = np.array(s["time_series"], dtype=object)
    print(f" {name}: shape={ts.shape}, dtype={ts.dtype}")

    # ------------------------------
    # without letters, only numeric data
    # ------------------------------
    if ts.ndim == 2:
        numeric_cols = []
        for col in range(ts.shape[1]):
            try:
                ts[:, col].astype(float)
                numeric_cols.append(col)
            except Exception:
                print(f"  → Colonne {col} ignorée (non numérique)")
        ts = ts[:, numeric_cols]

    elif ts.ndim == 1:
        try:
            ts.astype(float)
        except Exception:
            print("  → Colonne unique non numérique, stream ignoré")
            continue

    try:
        ts = ts.astype(float)
    except Exception:
        print("  → Impossible de convertir en float, stream ignoré")
        continue

    # ------------------------------
    # Column selection
    # ------------------------------
    if ts.ndim == 1:
        signal = ts
    else:
        signal = ts[:, 0]
        if ts.shape[1] > 1:
            print(f"  → Use of column 0 on {ts.shape[1]} columns")

    # ------------------------------
    # plot
    # ------------------------------
    ax.plot(time, signal, linewidth=1)
    ax.set_ylabel(f"{name}\n{source}", fontsize=8)
    ax.set_ylim(np.min(signal), np.max(signal))
    ax.grid(True, alpha=0.3)


axes[-1].set_xlabel("Time (s)")
fig.suptitle("Signals XDF", fontsize=12)
plt.tight_layout()

plt.ioff()
plt.show(block=True)