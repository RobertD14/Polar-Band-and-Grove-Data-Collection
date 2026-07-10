import os
import tkinter as tk
import subprocess
import threading
import socket
from tkinter import messagebox
from datetime import datetime


from clock1 import Stopwatch

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
process = None
child_processes = []  # keeps track of every external process opened from this window

PARENT_DIR = os.path.dirname(os.getcwd())
LOG_DIR = os.path.join(PARENT_DIR, "log_history")
os.makedirs(LOG_DIR, exist_ok=True)

START_TIME = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILE_NAME = f"log_{START_TIME}.log"
CURRENT_LOG_FILE = os.path.join(LOG_DIR, FILE_NAME)

def read_output(): #read the subprocess output and display it
    global process
    if process and process.stdout:
        try:
            for ligne in process.stdout:
                root.after(0, log, ligne)
        except Exception:
            pass

def run_script():
    global process

    if process is not None and process.poll() is None:
        log("The script is already running.\n")
        return

    log("Make sure your bluetooth is on\n")
    
    # Configuration for forcing UTF-8 and disabling Python's buffering
    env_utf8 = os.environ.copy()
    env_utf8["PYTHONIOENCODING"] = "utf-8"
    env_utf8["PYTHONUNBUFFERED"] = "1"
    
    process = subprocess.Popen(
        ["python", "-u", "main.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        env=env_utf8,
        bufsize=0,  # Transmission in real time
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    )

    child_processes.append(process)

    # Starting console display
    threading.Thread(target=read_output, daemon=True).start()


def send_key(letter):
    print(f"Output via UDP : {letter}")
    try:
        paquet = str(letter).strip().lower().encode('utf-8')
        sock.sendto(paquet, ("localhost", 5005))
    except Exception as e:
        log(f"Error network output : {e}\n")

def verify_and_kill_processes():
    global process
    if process is not None and process.poll() is None:
        process.terminate()
        log("The process has been stopped.\n")
    process = None

def stop_script():
    global process
    if process is not None and process.poll() is None:
        try:
            log("Sending stop signal\n")
            process.stdin.write("\x03\n")
            process.stdin.flush()
            
            # Security : If program doesn't stop after 2 seconds, kill the process
            root.after(2000, verify_and_kill_processes)
        except Exception as e:
            log(f"Error when stopped : {e}\n")
    else:
        log("No process to stop.\n")

def open_lab_recorder():
    p=subprocess.Popen([
        r"LabRecorder-1.17.0-Win_amd64\LabRecorder.exe"
    ])
    child_processes.append(p)

def open_Emotibit_oscilloscope():
    p=subprocess.Popen([
        r"EmotiBit\EmotiBit Oscilloscope\EmotiBitOscilloscope.exe"       
    ])
    child_processes.append(p)

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
LOG_FILE = f"logs_{timestamp}.txt"  # ex: logs_2024-01-15_14-30-45.txt

def log(message):
    console.insert(tk.END, message + "\n")
    console.see(tk.END)
    
    timestamp_content = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(CURRENT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp_content}] {message}\n")

def forced_stop():
    global process
    confirmation = messagebox.askyesno(
        title="Confirmation", 
        message="Did you stop recording on LabRecorder ?"
    )
    
    if not confirmation:
        log("Stopping cancelled.\n")
        return

    if process is not None and process.poll() is None:
        if os.name == 'nt':
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)], 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
        else:
            process.kill()
        
        log("Stop the process\n")
        
    process = None

def on_close():
    """Terminate every external process opened from the main window, then close it."""
    for p in child_processes:
        if p.poll() is None:  # still running
            try:
                if os.name == 'nt':
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                else:
                    p.terminate()
            except Exception as e:
                print(f"Error while closing process {p.pid}: {e}")
    child_processes.clear()
    root.destroy()

root = tk.Tk()
root.title("Multi-sensor synchronizer")
root.geometry("700x500")
root.protocol("WM_DELETE_WINDOW", on_close)

# Fixed headings
frame_header = tk.Frame(root, bg="#534AB7", height=40)
frame_header.pack(fill="x")
frame_header.pack_propagate(False)
tk.Label(frame_header, text="Steps to collect the data streams from multiple devices", bg="#534AB7", fg="white", font=("Arial", 16, "bold")).pack(side="left", padx=12, pady=8)

# PanedWindow vertical below
paned_v = tk.PanedWindow(root, orient="vertical", bg="#111", sashwidth=4)
paned_v.pack(fill="both", expand=True)

# PanedWindow vertical (top / bottom)
paned_v = tk.PanedWindow(root, orient="vertical", bg="#333", sashwidth=4)
paned_v.pack(fill="both", expand=True)

# --- Top : 2 panels side by side ---
paned_h = tk.PanedWindow(paned_v, orient="horizontal", bg="#111", sashwidth=4)

frame_left = tk.Frame(paned_h, bg="#2b2b3b")
# Top bar with Label + buttons
top_bar = tk.Frame(frame_left, bg="#2b2b3b")
top_bar.pack(side="top", fill="x", padx=0, pady=8)

tk.Label(top_bar, text="LSL streaming for Polar devices", bg="#2b2b3b", fg="white", font=("Arial", 14, "bold")).pack(side="left", padx=20)

tk.Button(top_bar, text="Start streaming", command=run_script, bg="#047913", fg="black",font=10).pack(side="left", padx=20)
tk.Button(top_bar, text="Y", width=5, command=lambda: send_key("y"), bg="#444466", fg="white").pack(side="left", padx=15)
tk.Button(top_bar, text="N", width=5, command=lambda: send_key("n"), bg="#444466", fg="white").pack(side="left", padx=2)

# Console below
console = tk.Text(frame_left, width=80, height=15, bg="#0f0f1a", fg="white", relief="flat")
console.pack(fill="both", expand=True, pady=10)
paned_h.add(frame_left, width=700, height=450) 

# --- FRAME RIGHT (INTEGRATION DE CLOCK1) ---
frame_right = tk.Frame(paned_h, bg="#1e1e2e")
tk.Label(frame_right, text="LSL streaming for other devices", bg="#1e1e2e", fg="white", font=("Arial", 14, "bold")).pack(side="top", padx=0, pady=0)
tk.Button(frame_right, text="Open Emotibit Oscilloscope", command=open_Emotibit_oscilloscope, width=35, bg="#534AB7", fg="white",font=8).pack(side="top", padx=15, pady=20)

# INTEGRATION OF CLOCK1 :
stopwatch_embed = Stopwatch(frame_right)

for widget in frame_right.winfo_children():

    if isinstance(widget, tk.Label) and widget["text"] == "00:00:00.0":
        widget.pack_forget()
        widget.configure(font=("Courier", 24, "bold"), padx=10, pady=5)
        widget.pack(side="bottom", fill="x") #At the bottom
        
    elif isinstance(widget, tk.Frame) and widget != frame_right:
        widget.pack_forget()
        widget.pack(side="bottom", pady=10)

paned_h.add(frame_right, width=350)

paned_v.add(paned_h, height=550)  # little on top

# --- Bottom : Big pannel ---
frame_bottom = tk.Frame(paned_v, bg="#0f0f1a")

top_bar = tk.Frame(frame_bottom, bg="#0f0f1a")
top_bar.pack(side="top", fill="x", padx=0, pady=8)

# Horizontal frame for aligning the elements
frame_tasks = tk.Frame(top_bar, bg=top_bar["bg"])
frame_tasks.pack(side="top", anchor="w", pady=5)


tk.Label(frame_tasks, text="Start recording", bg="#0f0f1a", fg="white", font=("Arial", 14, "bold")).pack(side="left", padx=20)
tk.Button(frame_tasks, text="Open LabRecorder", command=open_lab_recorder, bg="#444466", fg="white", font=10).pack(side="left", padx=50)

tk.Button(frame_tasks, text="Reaction Test", command=lambda: send_key("r"), width=12, bg="#534AB7", fg="white").pack(side="left", padx=15)
tk.Button(frame_tasks, text="Stroop Test",   command=lambda: send_key("s"), width=12, bg="#534AB7", fg="white").pack(side="left", padx=15)
tk.Button(frame_tasks, text="N-back",        command=lambda: send_key("n"), width=12, bg="#534AB7", fg="white").pack(side="left", padx=15)
tk.Button(frame_tasks, text="Rest",          command=lambda: send_key("t"), width=12, bg="#534AB7", fg="white").pack(side="left", padx=15)
tk.Button(frame_tasks, text="Test1",          command=lambda: send_key("q"), width=12, bg="#534AB7", fg="white").pack(side="left", padx=15)
tk.Button(frame_tasks, text="Test2",          command=lambda: send_key("w"), width=12, bg="#534AB7", fg="white").pack(side="left", padx=15)
tk.Button(frame_tasks, text="Test3",          command=lambda: send_key("e"), width=12, bg="#534AB7", fg="white").pack(side="left", padx=15)
#HERE TO ADD MORE BUTTONS

tk.Label(
    frame_tasks, 
    text="(Choose the phase of the test)", 
    bg="#0f0f1a", 
    fg="white", 
    font=("Arial", 11)
).pack(side="left", padx=20)

# ─── STOP BUTTON (BELOW) ───
tk.Button(top_bar, text="Stop streaming Polar devices", command=forced_stop, bg="#F90303", fg="white", font=8).pack(side="right", padx=15, pady=5)

# fixed height to not crush top_bar
tk.Text(frame_bottom, bg="#0f0f1a", fg="white", relief="flat", height=3).pack(fill="x", expand=False)

paned_v.add(frame_bottom, height=250)
root.mainloop()