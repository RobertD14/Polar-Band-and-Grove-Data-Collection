import pyxdf
import pandas as pd
from tkinter import Tk, filedialog, simpledialog, messagebox
import os

root = Tk()
root.withdraw()

# 1. Select a XDF file
chemin_xdf = filedialog.askopenfilename(
    title="Select an XDF file",
    filetypes=[("XDF Files", "*.xdf"), ("All files", "*.*")]
)
if not chemin_xdf:
    print("No file selected.")
    exit()

print(f"File loaded: {chemin_xdf}")

# 2. Load the XDF file
streams, header = pyxdf.load_xdf(chemin_xdf)
print(f"\n{len(streams)} stream(s) found:\n")

# 3. Display all available streams
for i, stream in enumerate(streams):
    name = stream['info']['name'][0]
    stype = stream['info']['type'][0]
    n_samples = len(stream['time_stamps'])
    if n_samples > 0:
        duree = stream['time_stamps'][-1] - stream['time_stamps'][0]
    else:
        duree = 0
    print(f"  [{i}] {name} | type: {stype} | {n_samples} samples | {duree:.1f}s")

# 4. Ask which stream to export (or all)
choix = simpledialog.askstring(
    "Stream selection",
    f"Enter stream index (0 to {len(streams)-1}), or 'all' to export all streams:"
)
if choix is None:
    exit()

# 5. Determine the output directory
chemin_csv_base = filedialog.asksaveasfilename(
    title="Save CSV (base name)",
    defaultextension=".csv",
    filetypes=[("CSV Files", "*.csv")],
    initialfile=os.path.splitext(os.path.basename(chemin_xdf))[0] + ".csv"
)
if not chemin_csv_base:
    print("Save cancelled.")
    exit()

# 6. Export
def exporter_stream(stream, chemin):
    data = stream['time_series']
    timestamps = stream['time_stamps']
    df = pd.DataFrame(data)
    df.insert(0, 'Timestamp', timestamps)
    df.to_csv(chemin, index=False, sep=';')  # Point-virgule pour Excel FR
    print(f"  ✓ Exported: {chemin}")

base, ext = os.path.splitext(chemin_csv_base)

if choix.strip().lower() == 'all':
    for i, stream in enumerate(streams):
        name = stream['info']['name'][0].replace(' ', '_')
        chemin = f"{base}_stream{i}_{name}{ext}"
        exporter_stream(stream, chemin)
else:
    try:
        idx = int(choix)
        exporter_stream(streams[idx], chemin_csv_base)
    except (ValueError, IndexError):
        messagebox.showerror("Error", f"Invalid index: {choix}")
        exit()

print("\nDone!")