#!/usr/bin/python

import os
import re
import sys
import glob
import time
import json
import atexit
import fnmatch
import tempfile
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
SYN_TESTPOINT_NODE = 'syn/testpoint'
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
            self.update_queue.put(("log", f"Configuration saved to {file_path}"))
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
            self.update_queue.put(("log", f"Configuration loaded from {file_path}"))

        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            messagebox.showerror("Load Error", f"Failed to load configuration file:\n{e}")

    def start_run(self):
        # Handle "Continue" functionality if the button is in that state
        if self.run_button['text'] == "Continue":
            if self.bob_manager:
                # Distinguish between resuming an INVALID run and a FAILED node
                if self.bob_manager.invalid_run_to_continue:
                    self.bob_manager.continue_invalid_run()
                elif self.bob_manager.failed_node_info:
                    self.bob_manager.resume_from_failure()
                self.run_button.config(state='disabled') # Disable after clicking continue
            return

        # Standard start run logic
        inputs = self.setup_inputs.get_values()
        stages = self.current_selected_stages

        if not self._validate_inputs(inputs): return
        if not stages:
            messagebox.showerror("Input Error", "Please select at least one stage to run.")
            return

        self.set_controls_state('disabled')
        self.stop_button.config(state='normal')
        self.log_text_append("--- PD COMPILER FLOW STARTED ---\n", "header")
        self.status_bar.config(text="Starting...")

        self.bob_manager = BobProcessManager(inputs, stages, self.update_queue, self)
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
    
    def append_status(self, new_message):
        current_text = self.status_bar.cget("text")
        if current_text and current_text != "Idle" and "RUNNING:" in current_text:
            self.status_bar.config(text=f"{current_text} | {new_message}")
        else:
            self.status_bar.config(text=new_message)


    def _periodic_queue_check(self):
        while not self.update_queue.empty():
            try:
                msg_type, data = self.update_queue.get_nowait()
                
                if msg_type == "status":
                    self.status_bar.config(text=data)
                elif msg_type == "append_status":
                    self.append_status(data)
                elif msg_type == "log":
                    self.log_text_append(data)
                elif msg_type == "failed":
                    failed_flow, details = data
                    self.append_status(f"FAILED: {failed_flow}")
                    self.bob_manager.send_failure_email(f"Stage {failed_flow} failed. Details: {details}", self.bob_manager.run_name)
                    # For parallel flows, a custom dialog will be shown from the thread
                    if failed_flow not in ['syn', 'pnr']:
                        RetryDialog(self, self.bob_manager, failed_flow, details)
                    else:
                        messagebox.showerror("Stage Failed", f"Stage {failed_flow} failed: {details}\nAn email notification has been sent.")
                
                elif msg_type == "node_failed_pausing":
                    # This is the new handler for the "pause and continue" logic
                    stage, details, failed_node, run_path = data
                    status_text = f"FAILED at node: {failed_node}"
                    self.status_bar.config(text=status_text, background="#FFA07A") # Light Salmon
                    
                    # Send email and show popup
                    self.bob_manager.send_failure_email(f"Flow paused due to failure at node '{failed_node}'. Details: {details}", self.bob_manager.run_name)
                    messagebox.showerror("Node Failed - Paused", f"Execution has been paused due to a failure.\n\nNode: {failed_node}\nDetails: {details}\n\nYou can now attempt to 'Continue' the run.")

                    # Update buttons
                    self.run_button.config(text="Continue", style="Continue.TButton", state='normal')
                    self.stop_button.config(state='normal')

                elif msg_type == "invalid_run":
                    flow_name, details = data
                    messagebox.showerror("Run Invalid", f"The run for {flow_name} has become INVALID.\nDetails: {details}\n\nPlease check the logs. You can attempt to continue the run.")
                    self.run_button.config(text="Continue", style="Continue.TButton", state='normal')
                    self.stop_button.config(state='normal')

                elif msg_type == "completed":
                    self.append_status("All Selected Stages Completed Successfully!")
                    self.status_bar.config(background="#90EE90")
                    self.reset_controls()
                elif msg_type == "flow_ended":
                    self.append_status("Flow Execution Finished.")
                    self.reset_controls()

            except queue.Empty:
                pass
        self.after(200, self._periodic_queue_check)

    def set_controls_state(self, state):
        # Disable all setup inputs
        for child in self.setup_inputs.winfo_children():
            try:
                child.config(state=state)
            except tk.TclError:
                pass # Some widgets like labels don't have a state
        # Explicitly handle comboboxes if they are direct children or nested
        for combo in self.setup_inputs.comboboxes.values():
             # This assumes comboboxes dictionary holds the widget, not just the var
             # You might need to adjust SetupFrame to store widgets if this fails
             pass

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

        # If work area doesn't have a 'repo', it's a new setup
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

class RetryDialog(tk.Toplevel):
    """A non-blocking dialog for retrying a failed parallel flow."""
    def __init__(self, parent, bob_manager, flow_name, details):
        super(RetryDialog, self).__init__(parent)
        self.bob_manager = bob_manager
        self.flow_name = flow_name

        self.title(f"Flow Failed: {flow_name}")
        self.geometry("400x150")
        self.transient(parent)
        # self.grab_set() # Do not grab, to keep it non-blocking

        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        label = ttk.Label(main_frame, text=f"Flow '{flow_name}' failed.\nDetails: {details}\n\nWhat would you like to do?", wraplength=380)
        label.pack(pady=10)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=10)

        retry_button = ttk.Button(button_frame, text="Retry", command=self.retry)
        retry_button.pack(side=tk.LEFT, padx=10)

        close_button = ttk.Button(button_frame, text="Close", command=self.destroy)
        close_button.pack(side=tk.LEFT, padx=10)

    def retry(self):
        self.bob_manager.retry_parallel_flow(self.flow_name)
        self.destroy()


class BobProcessManager:
    """Handles all backend logic for running BOB commands, now with parallel, dependency-aware execution."""
    def __init__(self, inputs, stages, update_queue, app_ref):
        self.inputs = inputs
        self.run_name = self.inputs['run_name']
        self.selected_stages = stages
        self.queue = update_queue
        self.app = app_ref # Reference to the main app for UI interaction
        self.user_email = self._get_user_email()
        self.work_area_path = os.path.abspath(self.inputs['work_area_path'])
        self.run_dir_path = os.path.join(self.work_area_path, "run")
        
        self.active_processes = {} # Maps run_name to subprocess object
        self.lock = threading.Lock()
        self._stop_event = threading.Event()
        
        # State tracking for the new flow control logic
        self.main_flow_to_run = None
        self.invalid_run_to_continue = None
        self.parallel_flows_to_retry = queue.Queue()
        self.paused_on_failure = threading.Event() # Event to pause/resume the main thread
        self.failed_node_info = None # Stores info about the failed node

        # Tool-specific node lists for SYN completion
        self.SYN_NODES_FC = [
            'syn/libgen', 'syn/elaborate', 'syn/synth', 'syn/invs_libgen', 
            'syn/setup', 'syn/floorplan', 'syn/synthopt', 'syn/testpoint', 
            'syn/synthdft', 'syn/synthdftopt'
        ]
        self.SYN_NODES_GENUS = [
            'syn/libgen', 'syn/elaborate', 'syn/synth', 'syn/testpoint', 
            'syn/synthdft', 'syn/synthdftopt'
        ]


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
            subprocess.run(command, shell=True, check=True, timeout=30, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.queue.put(("log", f"Failure notification email sent to {self.user_email}"))
        except Exception as e:
            self.queue.put(("log", f"ERROR: Failed to send email: {e}"))
            
    def _exec(self, cmd, run_name, cwd=None, is_run_command=False):
        self.queue.put(("log", f"[{run_name}] CMD: {cmd}"))
        if self._stop_event.is_set(): return None
        
        full_cmd = (
            f"source /etc/profile.d/modules.sh; "
            f"module load tools/bob; "
            f"module load tools/gchips-pd/pd-repo/{self.inputs['chip']}/; "
            f"{cmd}"
        )
        
        try:
            # For `bob run`, we just launch it and don't wait.
            process = subprocess.Popen(
                full_cmd, shell=True, executable='/bin/bash',
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, cwd=cwd or self.run_dir_path
            )
            with self.lock:
                self.active_processes[run_name] = process

            # If it's not a `bob run` command, we wait for it to complete.
            if not is_run_command:
                stdout, stderr = process.communicate()
                if process.returncode != 0:
                    self.queue.put(("log", f"[{run_name}] FAILED. STDERR:\n{stderr}"))
                    return None
            
            return process
        except Exception as e:
            self.queue.put(("log", f"ERROR starting process for {run_name}: {e}"))
            return None
            
    def _create_and_start_bob_run(self, flow_name, stages_to_create):
        """Creates and starts a bob run, returning the full path."""
        run_name = f"{self.inputs['run_name']}_{flow_name.upper()}"
        self.queue.put(("status", f"Setting up stage: {flow_name}..."))

        var_file = self._create_final_var_file(flow_name)
        if not var_file:
            self.queue.put(("failed", (flow_name, f"Var file creation failed")))
            return None

        full_run_path = os.path.join(self.run_dir_path, run_name)

        # Only create if the run directory doesn't exist
        if not os.path.exists(full_run_path):
            stages_arg = stages_to_create
            # Special handling for syn when pnr is also selected
            if flow_name == 'syn' and 'pnr' in self.selected_stages:
                stages_arg = "syn pnr"

            create_cmd = f"bob create -r {full_run_path} -s {stages_arg} -v {var_file}"
            if not self._exec(create_cmd, f"{run_name}_create"):
                self.queue.put(("failed", (flow_name, "bob create failed")))
                return None
        
        start_cmd = f"bob start -r {full_run_path}"
        if not self._exec(start_cmd, f"{run_name}_start"):
            self.queue.put(("failed", (flow_name, "bob start failed")))
            return None
        
        return full_run_path
        
    def _create_final_var_file(self, flow_name):
        base_var_path = FLOW_BASE_VAR_MAP.get(flow_name)
        if not base_var_path or not os.path.exists(base_var_path):
            self.queue.put(("log", f"TODO: Generate var file for {flow_name}"))
            # For now, let's create a dummy file to proceed
            final_var_path = os.path.join(self.run_dir_path, f"{flow_name.upper()}.var")
            with open(final_var_path, 'w') as f:
                f.write(f"# Dummy var file for {flow_name}\n")
            return final_var_path
            
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
            
    def wait_for_bob_node(self, run_area, node_pattern, stage=None, is_single_node_check=False, timeout_minutes=1440):
        start_time = time.time()
        timeout_seconds = timeout_minutes * 60

        temp_dir = tempfile.gettempdir()
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        safe_pattern = re.sub(r'[\/\*]', '_', node_pattern)
        json_output_file = os.path.join(temp_dir, f"bob_info_{safe_pattern}_{timestamp}.json")
        
        terminal_states = {"VALID", "FAILED", "INVALID", "ERROR", "KILLED"}
        failure_states = {"FAILED", "ERROR"}


        while time.time() - start_time < timeout_seconds:
            if self._stop_event.is_set(): return "ABORTED", "User requested stop.", None

            # Check for retry requests
            if not self.parallel_flows_to_retry.empty():
                retry_flow = self.parallel_flows_to_retry.get()
                self.queue.put(("log", f"Retrying run for {retry_flow}."))
                run_cmd = f"bob run -r {run_area} --node {node_pattern}"
                self._exec(run_cmd, f"{self.run_name}_{retry_flow}_run", is_run_command=True)

            bob_info_cmd = f"bob info -r {run_area} -o {json_output_file}"
            info_proc = self._exec(bob_info_cmd, f"bob_info_{run_area}")
            
            if not info_proc or info_proc.returncode != 0:
                self.queue.put(("log", f"WARNING: bob info for {run_area} failed. Retrying in 30s."))
                time.sleep(30)
                continue

            try:
                with open(json_output_file, 'r') as f:
                    jobs_data = json.load(f)
                
                # Single node check for triggers
                if is_single_node_check:
                    node_found = next((j for j in jobs_data if fnmatch.fnmatch(j.get("jobname", ""), node_pattern)), None)
                    if node_found:
                        status = node_found.get("status", "").upper()
                        if status == "VALID":
                            return "VALID", f"Node {node_pattern} completed.", node_found.get("jobname")
                        if status in terminal_states and status != "VALID":
                            return status, f"Node {node_pattern} is {status}.", node_found.get("jobname")
                else: # Full flow monitoring
                    nodes_to_check = None
                    if stage == 'syn':
                        if self.inputs.get('tool') == 'FUSION COMPILER':
                            nodes_to_check = self.SYN_NODES_FC
                        elif self.inputs.get('tool') == 'GENUS/INNOVUS':
                            nodes_to_check = self.SYN_NODES_GENUS
                    
                    if nodes_to_check: # This is syn stage
                        jobs_of_interest = [j for j in jobs_data if j.get("jobname") in nodes_to_check]
                        
                        # Prioritize checking for any failed node to enable the pause/continue feature
                        for job in jobs_of_interest:
                            job_status = job.get("status", "").upper()
                            job_name = job.get("jobname")
                            if job_status in failure_states:
                                return "FAILED", f"Node {job_name} failed with status {job_status}.", job_name
                            if job_status == "INVALID":
                                return "INVALID", f"Node {job_name} is INVALID.", job_name

                        valid_nodes = {j.get("jobname") for j in jobs_of_interest if j.get("status", "").upper() == "VALID"}
                        if set(nodes_to_check).issubset(valid_nodes):
                            return "COMPLETED", "All required synthesis nodes completed successfully.", None
                    
                    else: # Generic completion logic for other stages
                        all_nodes_in_pattern = [j for j in jobs_data if fnmatch.fnmatch(j.get("jobname", ""), node_pattern)]
                        if all_nodes_in_pattern: # Only proceed if nodes are found
                            # Check for failures first to allow pause/continue
                            for node in all_nodes_in_pattern:
                                node_status = node.get("status", "").upper()
                                node_name = node.get("jobname")
                                if node_status in failure_states:
                                    return "FAILED", f"Flow failed at node {node_name}", node_name
                                if node_status == "INVALID":
                                    return "INVALID", f"Flow became invalid at node {node_name}", node_name
                            
                            all_valid = all(j.get("status", "").upper() == "VALID" for j in all_nodes_in_pattern)
                            if all_valid:
                                return "COMPLETED", "All nodes completed successfully.", None

            except (json.JSONDecodeError, FileNotFoundError) as e:
                self.queue.put(("log", f"WARNING: Could not read bob info output for {run_area}. Error: {e}. Retrying..."))
            except Exception as e:
                 self.queue.put(("log", f"ERROR: An unexpected error occurred while polling {run_area}: {e}"))
            
            finally:
                if os.path.exists(json_output_file):
                    try:
                        os.remove(json_output_file)
                    except OSError:
                        pass

            time.sleep(60)
        
        return "TIMEOUT", "Operation timed out.", None

    def monitor_and_trigger_parallel_flows(self, main_run_path, main_flow_name):
        """Monitors a main flow (like syn) and triggers dependent parallel flows."""
        triggers = {
            SYN_OPT_NODE: [LEC_R2S_FLOW],
            SYN_COMPLETION_NODE: [LEC_S2S_FLOW, VCLP_S_FLOW],
            PNR_ROUTE_NODE: [LEC_S2P_FLOW, VCLP_P_FLOW],
        }
        
        # New, more robust trigger logic
        unfired_triggers = {node for node in triggers if any(FLOW_TO_BASE_STAGE[f] in self.selected_stages for f in triggers[node])}
        self.queue.put(("log", f"[Monitor] Will watch for triggers: {list(unfired_triggers)}"))

        while unfired_triggers and not self._stop_event.is_set():
            # Check for main flow failure periodically to abort early
            main_status, _, failed_node = self.wait_for_bob_node(main_run_path, f"{main_flow_name}/*", stage=main_flow_name, is_single_node_check=False, timeout_minutes=1)
            if main_status in ["FAILED", "INVALID", "TIMEOUT", "ABORTED"]:
                self.queue.put(("log", f"[Monitor] Main flow '{main_flow_name}' ended or failed. Halting trigger watch."))
                return # Exit the monitor thread

            # Iterate over a copy since we modify the set
            for node in list(unfired_triggers):
                # We use a short timeout check here; the outer loop handles the long polling interval
                status, _, _ = self.wait_for_bob_node(main_run_path, node, stage=main_flow_name, is_single_node_check=True, timeout_minutes=1)
                
                if status == "VALID":
                    self.queue.put(("log", f"SUCCESS: Prerequisite node '{node}' completed. Triggering dependent flows."))
                    flows_to_start = triggers[node]
                    for flow in flows_to_start:
                        if FLOW_TO_BASE_STAGE[flow] in self.selected_stages:
                            self.queue.put(("log", f"--> Starting parallel flow: {flow}"))
                            thread = threading.Thread(target=self._run_parallel_flow, args=(flow,))
                            thread.daemon = True
                            thread.start()
                    unfired_triggers.remove(node) # Mark as fired
                elif status in ["FAILED", "INVALID"]:
                    self.queue.put(("log", f"WARNING: Prerequisite node '{node}' is {status}. Dependent flows will not be triggered."))
                    unfired_triggers.remove(node) # Stop watching this failed trigger

            time.sleep(30) # Wait before the next check cycle
        
        self.queue.put(("log", f"[Monitor] Finished watching triggers for {main_flow_name}."))


    def _run_parallel_flow(self, flow_name):
        """Runs a single parallel flow (e.g., LEC_R2S) and monitors it."""
        base_stage = FLOW_TO_BASE_STAGE[flow_name]
        full_run_path = self._create_and_start_bob_run(flow_name, base_stage)
        if not full_run_path:
            return

        run_cmd = f"bob run -r {full_run_path}"
        self._exec(run_cmd, f"{self.run_name}_{flow_name}_run", is_run_command=True)

        self.queue.put(("log", f"Waiting 10 seconds before polling {flow_name}..."))
        time.sleep(10)

        status, details, _ = self.wait_for_bob_node(full_run_path, f"{base_stage}/*", stage=base_stage)

        if status == "COMPLETED":
            self.queue.put(("append_status", f"{flow_name} completed"))
            self.send_failure_email(f"Flow {flow_name} completed successfully.", f"PD Compiler Success: {self.run_name}")
        elif status not in ["ABORTED", "TIMEOUT"]:
            self.queue.put(("failed", (flow_name, details)))


    def continue_invalid_run(self):
        if self.invalid_run_to_continue:
            flow_name, run_path, node = self.invalid_run_to_continue
            self.queue.put(("log", f"Attempting to continue INVALID run for {flow_name}"))
            run_cmd = f"bob run -r {run_path} --node {node}"
            self._exec(run_cmd, f"{self.run_name}_{flow_name}_run_continue", is_run_command=True)
            self.invalid_run_to_continue = None
            self.main_flow_to_run = (flow_name, run_path, node)
        else:
            self.queue.put(("log", "Continue pressed but no invalid run was identified."))

    def resume_from_failure(self):
        """Resumes a run that was paused on a failed node."""
        if self.failed_node_info:
            stage, details, failed_node, run_path = self.failed_node_info
            self.queue.put(("log", f"--> User initiated CONTINUE. Resuming run for stage: {stage} with -f flag."))
            self.app.status_bar.config(background="#F0F0F0") 
            self.app.status_bar.config(text=f"RUNNING: {stage.upper()} (Resuming from {failed_node})")

            # Corrected command: Re-run the entire stage with the -f flag.
            # bob is smart enough to resume from the failure point.
            run_cmd = f"bob run -r {run_path} -f"
            self._exec(run_cmd, f"{self.run_name}_{stage}_resume", is_run_command=True)

            # Clear the failure info and signal the main thread to wake up
            self.failed_node_info = None
            self.paused_on_failure.set()
        else:
            self.queue.put(("log", "ERROR: Continue pressed, but no failed node information was found."))


    def retry_parallel_flow(self, flow_name):
        self.parallel_flows_to_retry.put(flow_name)


    def run_flow_manager(self):
        """Orchestrates the running of stages based on dependencies."""
        if not os.path.exists(self.run_dir_path):
            os.makedirs(self.run_dir_path, exist_ok=True)

        if not os.path.exists(os.path.join(self.work_area_path, "repo")):
            self.queue.put(("status", "Creating new work area..."))
            wa_cmd = (f"bob wa create --chip {self.inputs['chip']} --process {self.inputs['process']} "
                      f"--ip {self.inputs['ip']} --block {self.inputs['block']} --area {self.work_area_path}")
            if not self._exec(wa_cmd, "work_area_create", cwd=os.path.dirname(self.work_area_path) or '.'):
                self.queue.put(("failed", ("Work Area", "Creation failed.")))
                self.queue.put(("flow_ended", None))
                return
        
        main_stages_to_run = [s for s in ['syn', 'pnr', 'pdp', 'pdv', 'pex', 'emir', 'sta'] if s in self.selected_stages]

        for stage in main_stages_to_run:
            if self._stop_event.is_set(): break
            
            self.queue.put(("status", f"RUNNING: {stage.upper()}"))

            full_run_path = self._create_and_start_bob_run(stage, stage)
            if not full_run_path:
                self.queue.put(("flow_ended", None)); return
            
            run_cmd = f"bob run -r {full_run_path}"
            self._exec(run_cmd, f"{self.run_name}_{stage}_run", is_run_command=True)

            self.queue.put(("log", f"Waiting 10 seconds before polling {stage}..."))
            time.sleep(10)
            
            # Keep looping to allow for retries after a pause
            while not self._stop_event.is_set():
                monitor_thread = None
                if stage in ['syn', 'pnr']:
                    monitor_thread = threading.Thread(target=self.monitor_and_trigger_parallel_flows, args=(full_run_path, stage))
                    monitor_thread.daemon = True
                    monitor_thread.start()

                status, details, failed_node = self.wait_for_bob_node(full_run_path, f"{stage}/*", stage=stage)

                if monitor_thread:
                    self.queue.put(("log", f"Waiting for parallel monitors for {stage} to complete..."))
                    monitor_thread.join()

                if status == "COMPLETED":
                    self.queue.put(("append_status", f"{stage.upper()} completed"))
                    self.send_failure_email(f"Stage {stage.upper()} completed successfully.", f"PD Compiler Success: {self.run_name}")
                    break # Exit the while loop and proceed to the next stage

                elif status == "INVALID":
                    self.invalid_run_to_continue = (stage, full_run_path, f"{stage}/*")
                    self.queue.put(("invalid_run", (stage, details)))
                    return # Exit the flow manager completely

                elif status == "FAILED":
                    # This is the new pause logic
                    self.failed_node_info = (stage, details, failed_node, full_run_path)
                    self.queue.put(("node_failed_pausing", self.failed_node_info))
                    
                    self.paused_on_failure.clear() # Prepare to wait
                    self.paused_on_failure.wait() # Pause this thread until user continues

                    # Once user continues, the loop will restart and re-poll the stage
                    if self._stop_event.is_set():
                        # If user hit stop while paused
                        self.queue.put(("flow_ended", None))
                        return
                    else:
                        self.queue.put(("log", "Resumed. Waiting 10 seconds before re-polling status..."))
                        time.sleep(10)
                        continue # Re-enter the while loop to monitor again
                
                else: # Handles TIMEOUT, ABORTED, etc.
                    self.queue.put(("failed", (stage, details)))
                    self.queue.put(("flow_ended", None))
                    return

        if not self._stop_event.is_set():
             self.queue.put(("completed", None))
        else:
             self.queue.put(("flow_ended", None))


    def stop_all_runs(self):
        """Stops all currently running bob processes."""
        self._stop_event.set()
        # Also signal the pause event in case the thread is waiting on it
        self.paused_on_failure.set()
        with self.lock:
            for run_name, process in list(self.active_processes.items()):
                self.queue.put(("log", f"Terminating process for {run_name} (PID: {process.pid})"))
                try:
                    p = subprocess.Popen(['pkill', '-P', str(process.pid)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    p.communicate()
                    process.terminate()
                except ProcessLookupError:
                    self.queue.put(("log", f"Process for {run_name} already finished."))
                except Exception as e:
                    self.queue.put(("log", f"Error terminating process for {run_name}: {e}"))
            self.active_processes.clear()


if __name__ == "__main__":
    app = PDCompilerApp()
    app.mainloop()


