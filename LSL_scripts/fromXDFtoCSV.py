import pyxdf
import pandas as pd
from tkinter import Tk, filedialog, messagebox
import os

root = Tk()
root.withdraw()

# 1. Select a XDF file
path_xdf = filedialog.askopenfilename(
    title="Select an XDF file",
    filetypes=[("XDF Files", "*.xdf"), ("All files", "*.*")]
)
if not path_xdf:
    print("No file selected.")
    exit()

print(f"File loaded: {path_xdf}")

# 2. Load the XDF file
streams, header = pyxdf.load_xdf(path_xdf)
print(f"\n{len(streams)} stream(s) found:\n")

# 3. Display all available streams
for i, stream in enumerate(streams):
    name = stream['info']['name'][0]
    stype = stream['info']['type'][0]
    n_samples = len(stream['time_stamps'])
    if n_samples > 0:
        duration = stream['time_stamps'][-1] - stream['time_stamps'][0]
    else:
        duration = 0
    print(f"  [{i}] {name} | type: {stype} | {n_samples} samples | {duration:.1f}s")

# 4. Select output folder
output_folder = filedialog.askdirectory(
    title="Select output folder for CSV files"
)
if not output_folder:
    print("Save cancelled.")
    exit()

base_name = os.path.splitext(os.path.basename(path_xdf))[0]

# 5. Export
def export_stream(stream, path):
    data = stream['time_series']
    timestamps = stream['time_stamps']
    df = pd.DataFrame(data)

    try:
        desc = stream['info']['desc'][0]
        col_names = [desc[f'channel_{j}'][0] for j in range(len(data[0]))]
        df.columns = col_names
    except (KeyError, IndexError, TypeError):
        pass

    df.insert(0, 'Timestamp', timestamps)
    df.to_csv(path, index=False, sep=';')
    print(f"  ✓ Exported: {path}")


def sort_key(s):
    name = s["info"]["name"][0].lower()
    source = s["info"]["source_id"][0].lower()
    if "h10" in name or "h10" in source:
        return (0, source, name)
    elif "oh1" in name or "oh1" in source:
        return (1, source, name)
    else:
        return (2, source, name)


streams.sort(key=sort_key)

for i, stream in enumerate(streams):
    source = stream['info']['source_id'][0].replace(' ', '_')
    name = stream['info']['name'][0].replace(' ', '_')
    filename = f"{base_name}_stream{i}_{name}_{source}.csv"
    full_path = os.path.join(output_folder, filename)
    export_stream(stream, full_path)

print("\nDone!")