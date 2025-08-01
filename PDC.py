#!/usr/bin/python

import os
import re
import sys
import glob
import time
import json
import atexit
import threading
import subprocess
import datetime
import shutil

# For Python 3.6 compatibility, we check for tkinter's availability.
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext, filedialog
except ImportError:
    print("ERROR: tkinter module not found. Please install it (e.g., 'sudo apt-get install python3-tk')")
    sys.exit(1)

# For Python 3.6, queue is imported directly.
try:
    import queue
except ImportError:
    import Queue as queue


# --- Constants ---
DEFAULT_STAGES = ['syn', 'pnr', 'pdp', 'pdv', 'pex', 'sta', 'vclp', 'lec', 'emir']
PROCESS_OPTIONS = ['n3p', 'n3e', 'n2p']
CHIP_MAP = {'malibu': 'malibu', 'lga': 'lga', 'lajolla': 'laj'}
CHIP_OPTIONS = list(CHIP_MAP.keys())
TOOL_OPTIONS = ['GENUS/INNOVUS', 'FUSION COMPILER']

# --- Stage Flow and Node Constants ---
SYN_OPT_NODE = 'syn/synthopt'
SYN_COMPLETION_NODE = 'syn/synthdftopt'
PNR_PLACE_NODE = 'pnr/placeopt'
PNR_ROUTE_NODE = 'pnr/routeopt'
PNR_CHIPFINISH_NODE = 'pnr/chipfinish'
PDP_COMPLETION_NODE = 'pdp/pdp' # Placeholder, adjust if node name is different
PEX_COMPLETION_NODE = 'pex/pex' # Placeholder, adjust if node name is different


# --- Flow Definitions and Dependencies ---
LEC_R2S_FLOW = 'lec_r2s'
LEC_S2S_FLOW = 'lec_s2s'
VCLP_S_FLOW = 'vclp_s'
LEC_S2P_FLOW = 'lec_s2p'
VCLP_P_FLOW = 'vclp_p'
PDP_FLOW = 'pdp'
PEX_FLOW = 'pex'
STA_FLOW = 'sta'
PDV_FLOW = 'pdv'
EMIR_FLOW = 'emir'

# Map flow name to the base stage(s) it represents from the GUI selection
FLOW_TO_BASE_STAGE = {
    'syn': 'syn',
    'pnr': 'pnr',
    LEC_R2S_FLOW: 'lec',
    LEC_S2S_FLOW: 'lec',
    VCLP_S_FLOW: 'vclp',
    LEC_S2P_FLOW: 'lec',
    VCLP_P_FLOW: 'vclp',
    PDP_FLOW: 'pdp',
    PEX_FLOW: 'pex',
    STA_FLOW: 'sta',
    PDV_FLOW: 'pdv',
    EMIR_FLOW: 'emir',
}

# --- Base Var File Path Constants (Placeholders) ---
# ADD YOUR BASE VAR FILE PATHS HERE
BASE_VAR_SYN = "/google/gchips/workspace/redondo-asia/tpe/user/askakshay/PDCompiler/PDC_files/base_syn.var"
BASE_VAR_PNR = "/google/gchips/workspace/redondo-asia/tpe/user/askakshay/PDCompiler/PDC_files/base_pnr.var"
BASE_VAR_LEC_R2S = "/google/gchips/workspace/redondo-asia/tpe/user/askakshay/PDCompiler/PDC_files/lec_r2s.var"
BASE_VAR_LEC_S2S = "/google/gchips/workspace/redondo-asia/tpe/user/askakshay/PDCompiler/PDC_files/lec_s2s.var"
BASE_VAR_VCLP_S = "/google/gchips/workspace/redondo-asia/tpe/user/askakshay/PDCompiler/PDC_files/vclp_s.var"
BASE_VAR_LEC_S2P = "/google/gchips/workspace/redondo-asia/tpe/user/askakshay/PDCompiler/PDC_files/lec_s2p.var"
BASE_VAR_VCLP_P = "/google/gchips/workspace/redondo-asia/tpe/user/askakshay/PDCompiler/PDC_files/vclp_p.var"
BASE_VAR_PDP = "/google/gchips/workspace/redondo-asia/tpe/user/askakshay/PDCompiler/PDC_files/pdp.var"
BASE_VAR_PEX = "/google/gchips/workspace/redondo-asia/tpe/user/askakshay/PDCompiler/PDC_files/pex.var"
BASE_VAR_STA = "/google/gchips/workspace/redondo-asia/tpe/user/askakshay/PDCompiler/PDC_files/sta.var"
BASE_VAR_PDV = "/google/gchips/workspace/redondo-asia/tpe/user/askakshay/PDCompiler/PDC_files/pdv.var"
BASE_VAR_EMIR = "/google/gchips/workspace/redondo-asia/tpe/user/askakshay/PDCompiler/PDC_files/emir.var"


# Map flow names to their corresponding base var file paths
FLOW_BASE_VAR_MAP = {
    'syn': BASE_VAR_SYN,
    'pnr': BASE_VAR_PNR,
    LEC_R2S_FLOW: BASE_VAR_LEC_R2S,
    LEC_S2S_FLOW: BASE_VAR_LEC_S2S,
    VCLP_S_FLOW: BASE_VAR_VCLP_S,
    LEC_S2P_FLOW: BASE_VAR_LEC_S2P,
    VCLP_P_FLOW: BASE_VAR_VCLP_P,
    PDP_FLOW: BASE_VAR_PDP,
    PEX_FLOW: BASE_VAR_PEX,
    STA_FLOW: BASE_VAR_STA,
    PDV_FLOW: BASE_VAR_PDV,
    EMIR_FLOW: BASE_VAR_EMIR,
}


class PDCompilerApp(tk.Tk):
    """
    Main application window for the PD Compiler GUI.
    """
    def __init__(self):
        super(PDCompilerApp, self).__init__()
        self.title("PD Compiler Utility")

        self.process_thread = None
        self.bob_manager = None
        self.log_visible = False
        self.is_continuing_run = False
        self.update_queue = queue.Queue()
        self.current_selected_stages = DEFAULT_STAGES[:] # Initialize with all stages

        self._setup_style()
        self._setup_ui()
        self._periodic_queue_check()
        atexit.register(self._cleanup)

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure("TLabel", padding=5, font=('Arial', 10))
        style.configure("TButton", padding=5, font=('Arial', 10))
        style.configure("TCombobox", padding=5, font=('Arial', 10))
        style.configure("TEntry", padding=5, font=('Arial',10))
        style.configure("Header.TLabel", font=("Arial", 14, "bold"))
        style.configure("Status.TLabel", font=("Arial", 11, "bold"), anchor="center")
        style.configure("Run.TButton", font=("Arial", 12, "bold"), foreground="white", background="#4A00B4")
        style.configure("Stop.TButton", font=("Arial", 12, "bold"), foreground="white", background="#FF6347") # Tomato Red
        style.configure("Continue.TButton", font=("Arial", 12, "bold"), foreground="white", background="#FF8C00")
        style.configure("Exit.TButton", font=("Arial", 12, "bold"), foreground="white", background="#D22B2B")
        style.configure("Credit.TLabel", font=("Arial", 7), foreground="grey")

    def _setup_ui(self):
        # --- Footer is packed first to stay at the bottom ---
        footer_frame = ttk.Frame(self, padding=(10, 5, 10, 10))
        footer_frame.pack(side=tk.BOTTOM, fill=tk.X, anchor='s')

        # --- Main frame is packed second to fill the remaining space ---
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Widgets inside the main frame ---
        setup_frame = ttk.Frame(main_frame)
        setup_frame.pack(fill=tk.X, pady=5)
        setup_frame.columnconfigure(1, weight=1)
        
        self.setup_inputs = SetupFrame(setup_frame, self.show_stage_selection)
        self.setup_inputs.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        status_header = ttk.Label(main_frame, text="Current Status", style="Header.TLabel")
        status_header.pack(fill=tk.X, pady=(20, 5))

        self.status_bar = ttk.Label(main_frame, text="Idle", style="Status.TLabel", relief="groove", background="#F0F0F0")
        self.status_bar.pack(fill=tk.X, ipady=10)

        # --- Button Frame in Footer ---
        button_frame_top_row = ttk.Frame(footer_frame)
        button_frame_top_row.pack(fill=tk.X, pady=(0, 5))
        button_frame_top_row.columnconfigure([0, 1], weight=1)

        self.save_cfg_button = ttk.Button(button_frame_top_row, text="Save Cfg", command=self.save_configuration)
        self.save_cfg_button.grid(row=0, column=0, sticky="ew", padx=5)

        self.load_cfg_button = ttk.Button(button_frame_top_row, text="Load Cfg", command=self.load_configuration)
        self.load_cfg_button.grid(row=0, column=1, sticky="ew", padx=5)
        
        button_frame_bottom_row = ttk.Frame(footer_frame)
        button_frame_bottom_row.pack(fill=tk.X)
        button_frame_bottom_row.columnconfigure([0, 1, 2, 3], weight=1)

        self.run_button = ttk.Button(button_frame_bottom_row, text="Run", style="Run.TButton", command=self.start_run)
        self.run_button.grid(row=0, column=0, sticky="ew", padx=5)

        self.stop_button = ttk.Button(button_frame_bottom_row, text="Stop", style="Stop.TButton", command=self.stop_run, state='disabled')
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=5)

        self.toggle_log_button = ttk.Button(button_frame_bottom_row, text="Show Log", command=self.toggle_log)
        self.toggle_log_button.grid(row=0, column=2, sticky="ew", padx=5)

        self.exit_button = ttk.Button(button_frame_bottom_row, text="Exit", style="Exit.TButton", command=self.quit)
        self.exit_button.grid(row=0, column=3, sticky="ew", padx=5)
        
        credit_label = ttk.Label(footer_frame, text="Developed by askakshay", style="Credit.TLabel")
        credit_label.pack(side=tk.RIGHT, anchor='se', pady=(5,0))
        
        # Log frame is created but not packed until the button is pressed
        self.log_frame = ttk.Frame(main_frame)
        self.log_text = scrolledtext.ScrolledText(self.log_frame, wrap=tk.WORD, height=15, state='disabled', font=('Courier New', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_frame.pack_forget() # Initially hidden

    def save_configuration(self):
        """Saves the current GUI configuration to a JSON file."""
        config_data = self.setup_inputs.get_values()
        config_data['selected_stages'] = self.current_selected_stages
        
        file_path = filedialog.asksaveasfilename(
            title="Save Configuration",
            defaultextension=".cfg",
            filetypes=[("Config files", "*.cfg"), ("All files", "*.*")]
        )
        
        if not file_path:
            return

        try:
            with open(file_path, 'w') as f:
                json.dump(config_data, f, indent=4)
            self.queue.put(("log", f"Configuration saved to {file_path}"))
        except IOError as e:
            messagebox.showerror("Save Error", f"Failed to save configuration file:\n{e}")

    def load_configuration(self):
        """Loads a configuration from a JSON file into the GUI."""
        file_path = filedialog.askopenfilename(
            title="Load Configuration",
            filetypes=[("Config files", "*.cfg"), ("All files", "*.*")]
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r') as f:
                config_data = json.load(f)
            
            self.setup_inputs.set_values(config_data)
            self.current_selected_stages = config_data.get('selected_stages', DEFAULT_STAGES)
            self.queue.put(("log", f"Configuration loaded from {file_path}"))

        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            messagebox.showerror("Load Error", f"Failed to load configuration file:\n{e}")


    def start_run(self):
        # This function now only handles starting and validation.
        inputs = self.setup_inputs.get_values()
        stages = self.current_selected_stages

        if not self._validate_inputs(inputs): return
        if not stages:
            messagebox.showerror("Input Error", "Please select at least one stage to run.")
            return

        self.set_controls_state('disabled')
        self.stop_button.config(state='normal')
        self.log_text_append("--- PD COMPILER FLOW STARTED ---\n", "header")

        self.bob_manager = BobProcessManager(inputs, stages, self.update_queue)
        self.process_thread = threading.Thread(target=self.bob_manager.run_flow_manager)
        self.process_thread.daemon = True
        self.process_thread.start()
        
    def stop_run(self):
        if messagebox.askyesno("Confirm Stop", "Are you sure you want to stop all active runs?"):
            if self.bob_manager:
                self.update_queue.put(("log", "--- STOP BUTTON PRESSED ---"))
                self.bob_manager.stop_all_runs()
                self.stop_button.config(state='disabled') # Prevent multiple clicks
    
    def toggle_log(self):
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_frame.pack(fill=tk.BOTH, expand=True, pady=10)
            self.toggle_log_button.config(text="Hide Log")
        else:
            self.log_frame.pack_forget()
            self.toggle_log_button.config(text="Show Log")

    def _periodic_queue_check(self):
        while not self.update_queue.empty():
            try:
                msg_type, data = self.update_queue.get_nowait()
                
                if msg_type == "status":
                    self.status_bar.config(text=data)
                elif msg_type == "log":
                    self.log_text_append(data)
                elif msg_type == "failed":
                    # This is now a notification that A stage failed. Others might still be running.
                    self.status_bar.config(text=f"FAILED: {data}", background="#FFA07A")
                    run_name = self.bob_manager.inputs.get('run_name', 'UnknownRun')
                    self.bob_manager.send_failure_email(data, run_name)
                    messagebox.showerror("Stage Failed", f"Stage failed: {data}\nAn email notification has been sent.")
                elif msg_type == "completed":
                    self.status_bar.config(text="All Selected Stages Completed Successfully!", background="#90EE90")
                    self.reset_controls()
                elif msg_type == "flow_ended":
                    # This message is sent when the orchestrator finishes, regardless of success/failure
                    self.status_bar.config(text="Flow Execution Finished. Check logs for details.")
                    self.reset_controls()

            except queue.Empty:
                pass
        self.after(200, self._periodic_queue_check)

    def set_controls_state(self, state):
        for widget in self.setup_inputs.winfo_children():
            try:
                widget.config(state=state)
            except tk.TclError:
                pass # Ignore widgets that don't have a state option
        self.run_button.config(state=state)
        self.save_cfg_button.config(state=state)
        self.load_cfg_button.config(state=state)
    
    def reset_controls(self):
        self.set_controls_state('normal')
        self.run_button.config(text="Run", style="Run.TButton")
        self.stop_button.config(state='disabled')
        self.status_bar.config(background="#F0F0F0")

    def _validate_inputs(self, inputs):
        if not inputs.get('run_name', '').strip():
            messagebox.showerror("Input Error", "Run Name is a mandatory field.")
            return False

        work_area = inputs.get('work_area_path', '').strip()
        if not work_area:
             messagebox.showerror("Input Error", "Work Area Path is a mandatory field.")
             return False

        if not os.path.exists(os.path.join(work_area, 'repo')):
            mandatory_fields = {'process': "PROCESS", 'chip': "CHIP", 'ip': "IP", 'block': "BLOCK", 'tool': "TOOL"}
            for key, name in mandatory_fields.items():
                value = inputs.get(key, '').strip()
                if not value or value == '--Select Option--':
                    messagebox.showerror("Input Error", f"{name} is a mandatory field when creating a new work area.")
                    return False
        return True

    def show_stage_selection(self):
        dialog = StageSelectionFrame(self, current_stages=self.current_selected_stages)
        self.wait_window(dialog)
        if hasattr(dialog, 'confirmed') and dialog.confirmed:
            self.current_selected_stages = dialog.final_selection

    def log_text_append(self, text, tag=None):
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, text + "\n", tag)
        self.log_text.config(state='disabled')
        self.log_text.see(tk.END)

    def _cleanup(self):
        if self.process_thread and self.process_thread.is_alive(): 
            if self.bob_manager:
                self.bob_manager.stop_all_runs()


class SetupFrame(ttk.LabelFrame):
    """ The GUI frame for user inputs. """
    def __init__(self, parent, stage_callback, **kwargs):
        super(SetupFrame, self).__init__(parent, text="Configuration", **kwargs)
        self.stage_callback = stage_callback
        self.entries = {}
        self.comboboxes = {}
        fields = [
            ("PROCESS", "combo", PROCESS_OPTIONS, True),
            ("CHIP", "combo", CHIP_OPTIONS, True),
            ("IP", "entry", "", True),
            ("BLOCK", "entry", "", True),
            ("Work Area Path", "file_browse", "", True),
            ("Run Name", "entry", "", True),
            ("CUSTOM VAR", "file_browse", "", False),
            ("TOOL", "combo", TOOL_OPTIONS, True),
        ]
        for i, (label, field_type, data, mandatory) in enumerate(fields):
            lbl_text = f"{label}:{' *' if mandatory else ''}"
            ttk.Label(self, text=lbl_text).grid(row=i, column=0, sticky="w", padx=5, pady=5)
            key = label.lower().replace(" ", "_")
            
            if field_type == "combo":
                var = tk.StringVar()
                combo = ttk.Combobox(self, textvariable=var, values=data, state="readonly")
                combo.grid(row=i, column=1, columnspan=2, sticky="ew", padx=5)
                combo.set('--Select Option--')
                self.comboboxes[key] = var
                if key == 'chip':
                    combo.bind("<<ComboboxSelected>>", self._update_work_area_path)
            elif field_type == "file_browse":
                var = tk.StringVar()
                entry = ttk.Entry(self, textvariable=var, width=40)
                entry.grid(row=i, column=1, sticky="ew", padx=5)
                browse_cmd = lambda v=var, l=label: self._browse(v, l)
                btn = ttk.Button(self, text="Browse...", command=browse_cmd)
                btn.grid(row=i, column=2, sticky="w", padx=5)
                self.entries[key] = var
            else: # entry
                var = tk.StringVar()
                entry = ttk.Entry(self, textvariable=var, width=40)
                entry.grid(row=i, column=1, columnspan=2, sticky="ew", padx=5)
                self.entries[key] = var
                
        ttk.Label(self, text="STAGES:").grid(row=len(fields), column=0, sticky="w", padx=5, pady=10)
        self.stageflow_box = ttk.Button(self, text='Select Stages', command=self.stage_callback, width=15)
        self.stageflow_box.grid(row=len(fields), column=1, sticky="w", padx=5, pady=10)
        self._update_work_area_path()

    def _browse(self, var, label):
        if "Path" in label:
            path = filedialog.askdirectory(title=f"Select {label}")
        else:
            path = filedialog.askopenfilename(title=f"Select {label}")
        if path:
            var.set(path)

    def _update_work_area_path(self, event=None):
        top_path = os.environ.get('UFS_TOP')
        chip = self.comboboxes['chip'].get()
        if top_path and chip and chip != '--Select Option--':
            self.entries['work_area_path'].set(os.path.join(top_path, CHIP_MAP.get(chip, chip)))
        elif top_path:
            self.entries['work_area_path'].set(top_path)

    def get_values(self):
        vals = {k: v.get() for k, v in self.entries.items()}
        vals.update({k: v.get() for k, v in self.comboboxes.items()})
        return vals
    
    def set_values(self, data):
        """Sets the values of the GUI widgets from a dictionary."""
        for key, var in self.entries.items():
            if key in data:
                var.set(data[key])
        for key, var in self.comboboxes.items():
            if key in data:
                var.set(data[key])


class StageSelectionFrame(tk.Toplevel):
    """ A modal dialog for selecting stages. """
    def __init__(self, parent, current_stages, **kwargs):
        super(StageSelectionFrame, self).__init__(parent, **kwargs)
        self.title("Select Stages")
        self.transient(parent)
        self.grab_set()

        self.confirmed = False
        self.final_selection = []
        self.vars = {}

        content_frame = ttk.Frame(self, padding="10")
        content_frame.pack(expand=True, fill=tk.BOTH)
        content_frame.grid_columnconfigure([0, 1], weight=1)

        for i, stage in enumerate(DEFAULT_STAGES):
            var = tk.BooleanVar(value=(stage in current_stages))
            chk = ttk.Checkbutton(content_frame, text=stage.upper(), variable=var)
            chk.grid(row=i // 2, column=i % 2, sticky="w", padx=20, pady=5)
            self.vars[stage] = var

        button_frame = ttk.Frame(content_frame)
        button_frame.grid(row=(len(DEFAULT_STAGES) + 1) // 2, columnspan=2, pady=10)

        ok_button = ttk.Button(button_frame, text="OK", command=self._on_ok)
        ok_button.pack(side=tk.LEFT, padx=5)
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self.destroy)
        cancel_button.pack(side=tk.LEFT, padx=5)

    def _on_ok(self):
        self.final_selection = [s for s, v in self.vars.items() if v.get()]
        self.confirmed = True
        self.destroy()


class BobProcessManager:
    """Handles all backend logic for running BOB commands, now with parallel, dependency-aware execution."""
    def __init__(self, inputs, stages, update_queue):
        self.inputs = inputs
        self.selected_stages = stages
        self.queue = update_queue
        self.user_email = self._get_user_email()
        self.work_area_path = os.path.abspath(self.inputs['work_area_path'])
        self.run_dir_path = os.path.join(self.work_area_path, "run")
        
        self.active_processes = {} # Maps run_name to subprocess object
        self.completed_nodes = set()
        self.failed_flows = set()
        self.lock = threading.Lock()
        self._stop_event = threading.Event()
        
    def _get_user_email(self):
        try:
            username_bytes = subprocess.check_output(['whoami'])
            username = username_bytes.decode('utf-8').strip()
            return f"{username}@google.com"
        except Exception:
            return "askakshay@google.com" # Fallback

    def send_failure_email(self, failed_info, run_name_input):
        """Sends an email using the command line mail tool."""
        if not self.user_email:
            self.queue.put(("log", "ERROR: Could not determine user email. Cannot send notification."))
            return
            
        subject = f"PD Compiler Run Failed: {run_name_input}"
        body = f"The PD Compiler run '{run_name_input}' failed.\nDetails: {failed_info}"
        
        command = f'echo "{body}" | mail -s "{subject}" {self.user_email}'
        
        try:
            # For Python 3.6 compatibility, use stdout/stderr instead of capture_output
            subprocess.run(command, shell=True, check=True, timeout=30, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.queue.put(("log", f"Failure notification email sent to {self.user_email}"))
        except subprocess.CalledProcessError as e:
            self.queue.put(("log", f"ERROR: 'mail' command failed with exit code {e.returncode}"))
            self.queue.put(("log", f"STDERR: {e.stderr.decode('utf-8').strip()}"))
        except FileNotFoundError:
            self.queue.put(("log", "ERROR: 'mail' command not found. Cannot send failure email."))
        except Exception as e:
            self.queue.put(("log", f"ERROR: Failed to send email: {e}"))
            
    def _exec(self, cmd, run_name, cwd=None):
        self.queue.put(("log", f"[{run_name}] CMD: {cmd}"))
        if self._stop_event.is_set(): return None
        
        full_cmd = (
            f"source /etc/profile.d/modules.sh; "
            f"module load tools/bob; "
            f"module load tools/gchips-pd/pd-repo/{self.inputs['chip']}/; "
            f"{cmd}"
        )
        
        try:
            process = subprocess.Popen(
                full_cmd, shell=True, executable='/bin/bash',
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, cwd=cwd or self.run_dir_path
            )
            with self.lock:
                self.active_processes[run_name] = process
            return process
        except Exception as e:
            self.queue.put(("log", f"ERROR starting process for {run_name}: {e}"))
            return None

    def _wait_for_process(self, process, run_name):
        """Waits for a process to complete and logs its output selectively."""
        if not process: return False
        
        stdout, stderr = process.communicate()
        
        if process.returncode != 0 and stderr:
            self.queue.put(("log", f"[{run_name}] STDERR:\n{stderr}"))
        
        with self.lock:
            if run_name in self.active_processes:
                del self.active_processes[run_name]
            
        return process.returncode == 0

    def _create_final_var_file(self, flow_name):
        base_var_path = FLOW_BASE_VAR_MAP.get(flow_name)
        if not base_var_path or not os.path.exists(base_var_path):
            self.queue.put(("log", f"ERROR: Base var file for '{flow_name}' not found at {base_var_path}"))
            return None
            
        try:
            with open(base_var_path, 'r') as f:
                base_content = f.read()

            custom_var_content = ""
            custom_var_path = self.inputs.get('custom_var')
            if custom_var_path and os.path.exists(custom_var_path):
                with open(custom_var_path, 'r') as f:
                    custom_var_content = f.read()

            final_content = f"{base_content}\n\n# --- Custom Vars ---\n{custom_var_content}"
            
            final_var_path = os.path.join(self.run_dir_path, f"{flow_name.upper()}.var")
            with open(final_var_path, 'w') as f:
                f.write(final_content)
            return final_var_path
        except IOError as e:
            self.queue.put(("log", f"ERROR creating var file for {flow_name}: {e}"))
            return None

    def _run_stage_task(self, flow_name, stages_to_create, completion_node):
        """A target function for a thread to run a single stage/flow using create -> start -> run --node."""
        run_name = f"{self.inputs['run_name']}_{flow_name.upper()}"
        self.queue.put(("status", f"Starting stage: {flow_name}..."))

        var_file = self._create_final_var_file(flow_name)
        if not var_file:
            self.queue.put(("failed", f"Var file creation for {flow_name}"))
            with self.lock: self.failed_flows.add(flow_name)
            return

        full_run_path = os.path.join(self.run_dir_path, run_name)

        if not os.path.exists(full_run_path):
            if flow_name == 'syn':
                stages_arg = "syn" if 'pnr' not in self.selected_stages else "syn pnr"
            else:
                stages_arg = stages_to_create

            create_cmd = f"bob create -r {full_run_path} -s {stages_arg} -v {var_file}"
            create_proc = self._exec(create_cmd, f"{run_name}_create")
            if not self._wait_for_process(create_proc, f"{run_name}_create"):
                self.queue.put(("failed", f"bob create for {flow_name}"))
                with self.lock: self.failed_flows.add(flow_name)
                return
        
        start_cmd = f"bob start -r {full_run_path}"
        start_proc = self._exec(start_cmd, f"{run_name}_start")
        if not self._wait_for_process(start_proc, f"{run_name}_start"):
            self.queue.put(("failed", f"bob start for {flow_name}"))
            with self.lock: self.failed_flows.add(flow_name)
            return
        
        self.queue.put(("status", f"Waiting for {flow_name} to complete node: {completion_node}..."))
        run_cmd = f"bob run -r {full_run_path} --node {completion_node}"
        run_proc = self._exec(run_cmd, run_name)
        
        if not self._wait_for_process(run_proc, run_name):
            self.queue.put(("failed", f"Stage {flow_name} failed at or before node {completion_node}"))
            with self.lock: self.failed_flows.add(flow_name)
            return

        self.queue.put(("log", f"DEBUG: Stage {flow_name} completed node {completion_node} successfully."))
        with self.lock:
            self.completed_nodes.add(completion_node)

    def run_flow_manager(self):
        """Orchestrates the running of stages based on dependencies."""
        if not os.path.exists(self.run_dir_path):
            os.makedirs(self.run_dir_path, exist_ok=True)

        if not os.path.exists(os.path.join(self.work_area_path, "repo")):
            self.queue.put(("status", "Creating new work area..."))
            wa_cmd = (f"bob wa create --chip {self.inputs['chip']} --process {self.inputs['process']} "
                      f"--ip {self.inputs['ip']} --block {self.inputs['block']} --area {self.work_area_path}")
            wa_proc = self._exec(wa_cmd, "work_area_create", cwd=os.path.dirname(self.work_area_path) or '.')
            if not self._wait_for_process(wa_proc, "work_area_create"):
                self.queue.put(("failed", "Work area creation"))
                self.queue.put(("flow_ended", None))
                return
        
        dependency_graph = {
            'syn': ('syn', SYN_COMPLETION_NODE, []),
            'pnr': ('pnr', PNR_ROUTE_NODE, [SYN_COMPLETION_NODE]),
            LEC_R2S_FLOW: ('lec', f'{LEC_R2S_FLOW}/lec', [SYN_OPT_NODE]),
            LEC_S2S_FLOW: ('lec', f'{LEC_S2S_FLOW}/lec', [SYN_COMPLETION_NODE]),
            VCLP_S_FLOW: ('vclp', f'{VCLP_S_FLOW}/vclp', [SYN_COMPLETION_NODE]),
            LEC_S2P_FLOW: ('lec', f'{LEC_S2P_FLOW}/lec', [PNR_PLACE_NODE]),
            VCLP_P_FLOW: ('vclp', f'{VCLP_P_FLOW}/vclp', [PNR_ROUTE_NODE]),
            PDP_FLOW: ('pdp', PDP_COMPLETION_NODE, [PNR_CHIPFINISH_NODE]),
            PDV_FLOW: ('pdv', f'{PDV_FLOW}/pdv', [PDP_COMPLETION_NODE]),
            PEX_FLOW: ('pex', PEX_COMPLETION_NODE, [PDP_COMPLETION_NODE]),
            EMIR_FLOW: ('emir', f'{EMIR_FLOW}/emir', [PEX_COMPLETION_NODE]),
            STA_FLOW: ('sta', f'{STA_FLOW}/sta', [PEX_COMPLETION_NODE]),
        }
        
        threads = {}
        selected_flows = {f for f, s in FLOW_TO_BASE_STAGE.items() if s in self.selected_stages}
        
        while len(self.completed_nodes) + len(self.failed_flows) < len(selected_flows):
            if self._stop_event.is_set():
                self.queue.put(("log", "Flow manager stopping due to user request."))
                break

            runnable_flows = set()
            with self.lock:
                for flow, (_, _, deps) in dependency_graph.items():
                    if (flow in selected_flows and 
                        flow not in threads and 
                        flow not in self.failed_flows and 
                        all(dep in self.completed_nodes for dep in deps)):
                        runnable_flows.add(flow)
            
            for flow in runnable_flows:
                stages, completion_node, _ = dependency_graph[flow]
                thread = threading.Thread(target=self._run_stage_task, args=(flow, stages, completion_node))
                threads[flow] = thread
                thread.start()
            
            finished_threads = [flow for flow, t in threads.items() if not t.is_alive()]
            for flow in finished_threads:
                del threads[flow]

            if not threads and not runnable_flows and (len(self.completed_nodes) + len(self.failed_flows) < len(selected_flows)):
                self.queue.put(("log", "ERROR: No running stages and no new stages can be started. Aborting."))
                break
            
            time.sleep(10)

        if not self._stop_event.is_set():
            if not self.failed_flows and len(self.completed_nodes) == len(selected_flows):
                self.queue.put(("completed", None))
            else:
                self.queue.put(("flow_ended", None))
        else:
             self.queue.put(("flow_ended", None))


    def stop_all_runs(self):
        """Stops all currently running bob processes."""
        self._stop_event.set()
        with self.lock:
            for run_name, process in list(self.active_processes.items()):
                self.queue.put(("log", f"Terminating process for {run_name} (PID: {process.pid})"))
                try:
                    process.terminate()
                except ProcessLookupError:
                    self.queue.put(("log", f"Process for {run_name} already finished."))
                except Exception as e:
                    self.queue.put(("log", f"Error terminating process for {run_name}: {e}"))
            self.active_processes.clear()


if __name__ == "__main__":
    app = PDCompilerApp()
    app.mainloop()


