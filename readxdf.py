import pyxdf
#import mne  #signal processing
import matplotlib.pyplot as plt  #visualisation
import numpy as np
import tkinter as tk
from tkinter import filedialog


def choose_xdf_file() -> str:
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    path = filedialog.askopenfilename(      #filedialog to select the xdf file
        title='Select an XDF file',
        filetypes=[('XDF files', '*.xdf'), ('All files', '*.*')],
        initialdir='.'  #current directory
    )
    root.destroy()
    if not path:
        raise SystemExit('No file selected.')
    return path


fname = choose_xdf_file()
streams, header = pyxdf.load_xdf(fname) # 1 stream for 1 channel

#streams selection
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
    if not indices:
        raise ValueError('No valid selection.')
    if any(i < 0 or i > max_index for i in indices):
        raise IndexError('Stream index out of bounds.')
    return sorted(indices)

# keep all the streams (even empty) for Polar and other formats
streams_signal = [s for s in streams]

# sort streams alphabetically by name + source
streams_signal.sort(key=lambda s: (s["info"]["name"][0].lower(), s["info"]["source_id"][0].lower()))

#associate all the streams with a number for selection, and display the name, source and shape of the data
print(f"\nStreams available ({len(streams_signal)}) :")
for i, s in enumerate(streams_signal):
    name = s["info"]["name"][0]
    source = s["info"]["source_id"][0]
    shape = s["time_series"].shape
    print(f"  {i}: {name} | {source} | shape: {shape}")

#select the streams to display
selection = input("Choose the streams you want to display (ex: all, 0, 0-2, 0,3) : ").strip()
try:
    selected_indices = parse_selection(selection, len(streams_signal) - 1)
except Exception as exc:
    raise SystemExit(f"Invalid selection : {exc}")

#visualisation of the selected streams
selected_streams = [streams_signal[i] for i in selected_indices]
print(f"\nVisualisation of {len(selected_streams)} stream(s) : {selected_indices}")

# maximum commun time
time_max = max(
    s["time_stamps"][-1] - s["time_stamps"][0] 
    for s in selected_streams
)
n_chanel = len(selected_streams)

#if 3,5 channels --> 3,5 lines, 1 column
fig, axes = plt.subplots(n_chanel, 1, figsize=(12, 2 * n_chanel), sharex=True)

if n_chanel == 1:
    axes = [axes]

# preserve the different time stamps
selected_t_start = min(s["time_stamps"][0] for s in selected_streams)

for i, (ax, s) in enumerate(zip(axes, selected_streams)):
    name = s["info"]["name"][0]
    source = s["info"]["source_id"][0]
    time = s["time_stamps"] - selected_t_start  # same reference for all
    
    # Manage the different data structures (1D, 2D with 1 column, 2D with multiple columns)
    time_series = s["time_series"]
    print(f" {name}: shape={time_series.shape}, dtype={time_series.dtype}")
    
    # Select appropriate column/dimension
    if len(time_series.shape) == 1:
        # Data 1D (simple signal)
        signal = time_series
    elif len(time_series.shape) == 2:
        if time_series.shape[1] == 1:
            # Data 2D with 1 column
            signal = time_series[:, 0]
        else:
            # Data 2D with multiple columns - use the first one
            signal = time_series[:, 0]
            print(f"  → Use of column 0 on {time_series.shape[1]} columns")
    else:
        print(f"  ⚠ Unexpected format with {len(time_series.shape)} dimensions")
        continue
    
    ax.plot(time, signal, linewidth=1)
    ax.set_ylabel(f"{name}\n{source}", fontsize=8)
    ax.set_ylim(np.min(signal), np.max(signal))
    ax.grid(True, alpha=0.3)

axes[-1].set_xlabel("Time (s)")
fig.suptitle("Signals Emotibit", fontsize=12)
plt.tight_layout()
plt.show()