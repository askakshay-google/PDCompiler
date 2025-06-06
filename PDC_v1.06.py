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
SYN_COMPLETION_NODE = 'syn/synthdftopt'
PNR_COMPLETION_NODE = 'pnr/routeopt'
LEC_R2S_FLOW = 'lec_r2s'
VCLP_S_FLOW = 'vclp_s'
LEC_S2P_FLOW = 'lec_s2p'
VCLP_P_FLOW = 'vclp_p'
PDP_PEX_FLOW = 'pdp_pex'

FLOW_TO_BASE_STAGE = {
    LEC_R2S_FLOW: 'lec', VCLP_S_FLOW: 'vclp', LEC_S2P_FLOW: 'lec',
    VCLP_P_FLOW: 'vclp', PDP_PEX_FLOW: 'pdp', 'sta': 'sta',
    'emir': 'emir', 'pdv': 'pdv',
}

# --- Base Var File Template Constants for Special Flows ---
#TODO
LEC_R2S_VAR_TEMPLATE = 'set ::BOB_STAGE_CFG(lec,EXTRA_OPTS) -rtl2syn\n'
VCLP_S_VAR_TEMPLATE = (
    'bbset vclp.pnr.NetlistFile "{work_area_path}/run/{main_run_name}/main/syn/synthdftopt/outs/{block}.final.v.gz"\n'
    'bbset vclp.pnr.UPFFile "{work_area_path}/run/{main_run_name}/main/syn/synthdftopt/outs/{block}.upf"\n'
)
LEC_S2P_VAR_TEMPLATE = "set ::BOB_STAGE_CFG(lec,EXTRA_OPTS) -syn2pnr\n"
VCLP_P_VAR_TEMPLATE = "set ::BOB_STAGE_CFG(vclp,EXTRA_OPTS) -pnr\n"
PDP_PEX_VAR_TEMPLATE = ""
STA_VAR_TEMPLATE = ""
EMIR_VAR_TEMPLATE = ""
PDV_VAR_TEMPLATE = ""

FLOW_VAR_TEMPLATE_MAP = {
    LEC_R2S_FLOW: LEC_R2S_VAR_TEMPLATE, VCLP_S_FLOW: VCLP_S_VAR_TEMPLATE,
    LEC_S2P_FLOW: LEC_S2P_VAR_TEMPLATE, VCLP_P_FLOW: VCLP_P_VAR_TEMPLATE,
    PDP_PEX_FLOW: PDP_PEX_VAR_TEMPLATE, 'sta': STA_VAR_TEMPLATE,
    'emir': EMIR_VAR_TEMPLATE, 'pdv': PDV_VAR_TEMPLATE,
}

# --- Base Var File Path Constants (Placeholders) ---
BASE_VAR_LEC_R2S = "/google/gchips/workspace/redondo-asia/tpe/user/askakshay/PDCompiler/PDC_files/lec_r2s.var"
BASE_VAR_VCLP_S = "/google/gchips/workspace/redondo-asia/tpe/user/askakshay/PDCompiler/PDC_files/vclp_s.var"
BASE_VAR_LEC_S2P = "TODO filepath"
BASE_VAR_VCLP_P = "TODO filepath"
BASE_VAR_PDP_PEX = "TODO filepath"
BASE_VAR_STA = "TODO filepath"
BASE_VAR_EMIR = "TODO filepath"
BASE_VAR_PDV = "TODO filepath"


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

        button_frame = ttk.Frame(footer_frame)
        button_frame.pack(fill=tk.X)
        button_frame.columnconfigure([0, 1, 2, 3], weight=1)

        self.run_button = ttk.Button(button_frame, text="Run", style="Run.TButton", command=self.start_run)
        self.run_button.grid(row=0, column=0, sticky="ew", padx=5)

        self.stop_button = ttk.Button(button_frame, text="Stop", style="Stop.TButton", command=self.stop_run, state='disabled')
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=5)

        self.toggle_log_button = ttk.Button(button_frame, text="Show Log", command=self.toggle_log)
        self.toggle_log_button.grid(row=0, column=2, sticky="ew", padx=5)

        self.exit_button = ttk.Button(button_frame, text="Exit", style="Exit.TButton", command=self.quit)
        self.exit_button.grid(row=0, column=3, sticky="ew", padx=5)
        
        credit_label = ttk.Label(footer_frame, text="Developed by askakshay", style="Credit.TLabel")
        credit_label.pack(side=tk.RIGHT, anchor='se', pady=(5,0))

        # --- Main frame is packed second to fill the remaining space ---
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Widgets inside the main frame ---
        setup_frame = ttk.Frame(main_frame)
        setup_frame.pack(fill=tk.X, pady=5)
        setup_frame.columnconfigure(1, weight=1)
        
        self.setup_inputs = SetupFrame(setup_frame, self.show_stage_selection)
        self.setup_inputs.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        # self.stage_selection = StageSelectionFrame(setup_frame) # Dialog now, created on demand
        # self.stage_selection.grid(row=0, column=1, sticky="nsew")

        status_header = ttk.Label(main_frame, text="Current Status", style="Header.TLabel")
        status_header.pack(fill=tk.X, pady=(20, 5))

        self.status_bar = ttk.Label(main_frame, text="Idle", style="Status.TLabel", relief="groove", background="#F0F0F0")
        self.status_bar.pack(fill=tk.X, ipady=10)
        
        # Log frame is created but not packed until the button is pressed
        self.log_frame = ttk.Frame(main_frame)
        self.log_text = scrolledtext.ScrolledText(self.log_frame, wrap=tk.WORD, height=15, state='disabled', font=('Courier New', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_frame.pack_forget() # Initially hidden

    def start_run(self):
        if self.is_continuing_run:
            self.run_button.config(text="Run", style="Run.TButton") # Reset button text
            self.is_continuing_run = False # Reset flag

            if self.bob_manager:
                # Set a flag indicating this is a continued run
                self.bob_manager.is_continue_run_flag = True

                # Re-initialize and start the process thread
                self.process_thread = threading.Thread(target=self.bob_manager.run_full_flow)
                self.process_thread.daemon = True
                self.process_thread.start()

                # Keep controls disabled and stop button enabled
                self.set_controls_state('disabled')
                self.stop_button.config(state='normal')
            else:
                # This case should ideally not happen if continue is triggered after a failure
                self.log_text_append("ERROR: Continue pressed but no Bob Manager instance found.", "error_tag") # Or handle error appropriately
                self.reset_controls()
            return # Important: Return after handling the continue logic

        inputs = self.setup_inputs.get_values()
        stages = self.current_selected_stages # Use the updated list of stages

        if not self._validate_inputs(inputs): return
        if not stages:
            messagebox.showerror("Input Error", "Please select at least one stage to run.")
            return

        self.set_controls_state('disabled')
        self.stop_button.config(state='normal')
        self.log_text_append("--- PD COMPILER FLOW STARTED ---\n", "header")

        self.bob_manager = BobProcessManager(inputs, stages, self.update_queue)
        self.process_thread = threading.Thread(target=self.bob_manager.run_full_flow)
        self.process_thread.daemon = True
        self.process_thread.start()

    def stop_run(self):
        if messagebox.askyesno("Confirm Stop", "Are you sure you want to stop all active runs?"):
            if self.bob_manager:
                self.update_queue.put(("log", "--- STOP BUTTON PRESSED ---"))
                self.bob_manager.stop_bob_runs()
                self.stop_button.config(state='disabled')
    
    def toggle_log(self):
        if self.log_visible:
            self.log_frame.pack_forget()
            self.toggle_log_button.config(text="Show Log")
            self.log_visible = False
        else:
            self.log_frame.pack(fill=tk.BOTH, expand=True, pady=10)
            self.toggle_log_button.config(text="Hide Log")
            self.log_visible = True

    def _periodic_queue_check(self):
        while not self.update_queue.empty():
            try:
                msg_type, data = self.update_queue.get_nowait()
                
                if msg_type == "status":
                    self.status_bar.config(text=data)
                elif msg_type == "log":
                    self.log_text_append(data)
                elif msg_type == "failed":
                    self.status_bar.config(text="FAILED: {}".format(data), background="#FFA07A")
                    self.run_button.config(text="Continue", style="Continue.TButton")
                    self.is_continuing_run = True
                    self.run_button.config(state='normal') # Allow continue
                    self.exit_button.config(state='normal')
                    self.stop_button.config(state='disabled')

                    email_status_message = "An email notification has been sent." # Default message
                    if self.bob_manager and hasattr(self.bob_manager, 'send_failure_email'):
                        run_name = self.bob_manager.inputs.get('run_name', 'UnknownRun')
                        email_sent_successfully = self.bob_manager.send_failure_email(data, run_name)
                        if not email_sent_successfully:
                            email_status_message = "Attempted to send email notification, but it failed."
                    else:
                        email_status_message = "Email notification system not available." # Should not happen if bob_manager is there

                    messagebox.showerror("Run Failed", f"Stage failed at node: {data}\n{email_status_message}\nPress 'Continue' to restart from this point.")
                elif msg_type == "completed":
                    self.status_bar.config(text="Flow Completed Successfully!", background="#90EE90")
                    self.reset_controls()
                elif msg_type == "reset":
                    self.reset_controls()
                    self.status_bar.config(text="Run Aborted By User")
            except queue.Empty:
                pass
        self.after(200, self._periodic_queue_check)

    def set_controls_state(self, state):
        for widget in [self.setup_inputs]: # self.stage_selection is no longer a persistent widget here
            for child in widget.winfo_children():
                try: child.config(state=state)
                except tk.TclError: pass
        self.run_button.config(state=state)
    
    def reset_controls(self):
        self.set_controls_state('normal')
        self.run_button.config(text="Run", style="Run.TButton")
        self.is_continuing_run = False
        self.stop_button.config(state='disabled')
        self.status_bar.config(background="#F0F0F0")

    def _validate_inputs(self, inputs):
        # Rule 1: Run Name is always mandatory.
        # The key for Run Name in the inputs dictionary is 'run_name'.
        if not inputs.get('run_name', '').strip():
            messagebox.showerror("Input Error", "Run Name is a mandatory field.")
            return False

        # The key for Work Area Path in the inputs dictionary is 'work_area_path'.
        work_area = inputs.get('work_area_path', '').strip()

        # Check if the special condition (Work Area Path with 'run' and 'repo' folders) is met.
        condition_met = False
        if work_area: # work_area path must be provided for the condition to be evaluated
            # Construct full paths for 'run' and 'repo' subdirectories
            run_dir = os.path.join(work_area, 'run')
            repo_dir = os.path.join(work_area, 'repo')
            # Check if both are existing directories
            if os.path.isdir(run_dir) and os.path.isdir(repo_dir):
                condition_met = True

        if condition_met:
            # Rule 2: If Work Area Path is provided and has 'run' and 'repo' subdirectories,
            # then only Run Name (already checked) and Work Area Path itself are strictly mandatory.
            # Other fields typically marked mandatory become optional.
            # Since 'work_area' must be non-empty for condition_met to be True, it's implicitly checked.
            return True
        else:
            # Rule 2 is not met. This means either:
            # a) Work Area Path was not provided, OR
            # b) Work Area Path was provided but does not contain both 'run' and 'repo' subdirectories.
            # In this scenario, fields are mandatory based on their default status in SetupFrame.

            # List of fields that are mandatory by default (excluding Run Name, already checked).
            # Keys are from the 'inputs' dictionary. Values are their display names for error messages.
            default_mandatory_fields = {
                'process': "PROCESS",
                'chip': "CHIP",
                'ip': "IP",
                'block': "BLOCK",
                'work_area_path': "Work Area Path", # Mandatory if condition_met is False.
                'tool': "TOOL"
                # Fields like 'rtl_list', 'upf', 'sdc', 'custom_var' are optional by default
                # as per their 'False' mandatory flag in SetupFrame.
            }

            for field_key, display_name in default_mandatory_fields.items():
                value = inputs.get(field_key, '').strip()
                # Comboboxes might have a default "--Select Option--" value.
                if not value or value == '--Select Option--':
                    messagebox.showerror("Input Error", f"{display_name} is a mandatory field.")
                    return False

            # If all checks pass under this condition.
            return True

    def show_stage_selection(self):
        # Create and show the dialog
        dialog = StageSelectionFrame(self, current_stages=self.current_selected_stages)
        self.wait_window(dialog) # Wait for the dialog to close

        if hasattr(dialog, 'confirmed') and dialog.confirmed:
            self.current_selected_stages = dialog.final_selection
            # Optionally, update UI or log the change
            # print("Updated selected stages:", self.current_selected_stages)
        # else:
            # print("Stage selection cancelled or dialog closed without confirmation.")

    def log_text_append(self, text, tag=None):
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, text + "\n", tag)
        self.log_text.config(state='disabled')
        self.log_text.see(tk.END)
    def _cleanup(self):
        if self.process_thread and self.process_thread.is_alive(): 
            if self.bob_manager:
                self.bob_manager.stop()

class SetupFrame(ttk.LabelFrame):
    def __init__(self, parent, stage_callback, **kwargs):
        super(SetupFrame, self).__init__(parent, text="Configuration", **kwargs)
        self.stage_callback = stage_callback # This callback will now create and show the dialog
        self.entries = {}
        self.comboboxes = {}
        fields = [
            ("PROCESS", "combo", PROCESS_OPTIONS, True), ("CHIP", "combo", CHIP_OPTIONS, True),
            ("IP", "entry", "", True), ("BLOCK", "entry", "", True),
            ("Work Area Path", "file_browse", "", True),("Run Name", "entry", "", True),
            ("RTL_FILE_LIST", "entry", "", False), ("UPF", "entry", "", False),
            ("SDC", "entry", "", False), ("CUSTOM VAR", "entry", "", False),
            ("TOOL", "combo", TOOL_OPTIONS, True),
        ]
        for i, (label, field_type, data, mandatory) in enumerate(fields):
            lbl_text = "{}:{}".format(label, " *" if mandatory else "")
            ttk.Label(self, text=lbl_text).grid(row=i, column=0, sticky="w", padx=5, pady=5)
            key = label.lower().replace(" ", "_").replace("_file_list", "_list")
            if field_type == "combo":
                var = tk.StringVar(); combo = ttk.Combobox(self, textvariable=var, values=data, state="readonly")
                combo.grid(row=i, column=1, columnspan=2, sticky="ew", padx=5); combo.set('--Select Option--')
                self.comboboxes[key] = var
                if key == 'chip': combo.bind("<<ComboboxSelected>>", self._update_work_area_path)
            elif field_type == "file_browse":
                var = tk.StringVar(); entry = ttk.Entry(self, textvariable=var, width=40)
                entry.grid(row=i, column=1, sticky="ew", padx=5)
                btn = ttk.Button(self, text="Browse...", command=lambda v=var: self._browse_dir(v))
                btn.grid(row=i, column=2, sticky="w", padx=5); self.entries[key] = var
            else:
                var = tk.StringVar(); entry = ttk.Entry(self, textvariable=var, width=40)
                entry.grid(row=i, column=1, columnspan=2, sticky="ew", padx=5); self.entries[key] = var
        ttk.Label(self, text="STAGES:").grid(row=len(fields), column=0, sticky="w", padx=5, pady=10)
        self.stageflow_box = ttk.Button(self, text='Select Stages', command=self.stage_callback, width=15) # Button in SetupFrame
        self.stageflow_box.grid(row=len(fields), column=1, sticky="w", padx=5, pady=10)
        self._update_work_area_path()
    def _browse_dir(self, var):
        d = filedialog.askdirectory(title="Select Work Area");
        if d: var.set(d)
    def _update_work_area_path(self, event=None):
        top_path = os.environ.get('UFS_TOP'); chip = self.comboboxes['chip'].get()
        if top_path and chip and chip != '--Select Option--':
            self.entries['work_area_path'].set(os.path.join(top_path, CHIP_MAP.get(chip, chip)))
        elif top_path: self.entries['work_area_path'].set(top_path)
    def get_values(self):
        vals = {k: v.get() for k, v in self.entries.items()}
        vals.update({k: v.get() for k, v in self.comboboxes.items()}); return vals

class StageSelectionFrame(tk.Toplevel):
    def __init__(self, parent, current_stages, **kwargs):
        super(StageSelectionFrame, self).__init__(parent, **kwargs)
        self.title("Select Stages")
        self.transient(parent) # Make it modal
        self.grab_set()       # Grab all events

        self.confirmed = False
        self.final_selection = []
        self.vars = {}

        # Ensure content is placed correctly in Toplevel
        content_frame = ttk.Frame(self, padding="10")
        content_frame.pack(expand=True, fill=tk.BOTH)
        content_frame.grid_columnconfigure([0, 1], weight=1)

        for i, stage in enumerate(DEFAULT_STAGES):
            # Initialize checkbox based on current_stages
            var = tk.BooleanVar(value=(stage in current_stages))
            chk = ttk.Checkbutton(content_frame, text=stage.upper(), variable=var)
            # Grid within the content_frame
            chk.grid(row=i // 2, column=i % 2, sticky="w", padx=20, pady=5)
            self.vars[stage] = var

        # Add an OK and Cancel button
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

    def get_selected_stages(self): # This can still be useful if needed before confirmation
        return [s for s, v in self.vars.items() if v.get()]

class BobProcessManager:
    """Handles all backend logic for running BOB commands."""
    def __init__(self, inputs, stages, update_queue):
        self.inputs, self.selected_stages, self.queue = inputs, stages, update_queue
        self.failed_node, self.user_email = None, self._get_user_email()
        self.work_area_path = os.path.abspath(self.inputs['work_area_path'])
        self.run_dir_path = os.path.join(self.work_area_path, "run")
        self.active_run_names = []
        self.parallel_run_results = queue.Queue()
        self._stop_event = threading.Event()
        self._continue_event = threading.Event()
        self.is_continue_run_flag = False # Initialize the new flag

    def send_failure_email(self, failed_node_info, run_name_input):
        """Sends an email notification about the failed run."""
        if not self.user_email:
            self.queue.put(("log", "ERROR: User email not found, cannot send failure email."))
            return False

        subject = f"PD Compiler Run Failed: {run_name_input}"
        body = f"The PD Compiler run '{run_name_input}' failed at node/stage: {failed_node_info}.\nPlease check the logs in the GUI or work area for more details."

        # Basic mail command: echo "body" | mail -s "subject" user@example.com
        cmd = ['mail', '-s', subject, self.user_email]

        try:
            process = subprocess.run(cmd, input=body, text=True, check=False, capture_output=True, timeout=30) # Added timeout
            if process.returncode == 0:
                self.queue.put(("log", f"Failure notification email sent to {self.user_email} for run '{run_name_input}'."))
                return True
            else:
                error_msg = f"ERROR: Failed to send email. 'mail' command exited with code {process.returncode}."
                if process.stderr:
                    error_msg += f"\nSTDERR: {process.stderr.strip()}"
                if process.stdout: # mail command might output info on stdout on error too
                    error_msg += f"\nSTDOUT: {process.stdout.strip()}"
                self.queue.put(("log", error_msg))
                return False
        except FileNotFoundError:
            self.queue.put(("log", "ERROR: 'mail' command not found. Cannot send failure email."))
            return False
        except subprocess.TimeoutExpired:
            self.queue.put(("log", "ERROR: Timeout while trying to send failure email via 'mail' command."))
            return False
        except Exception as e:
            self.queue.put(("log", f"ERROR: Unexpected error sending email: {e}"))
            return False

    def _execute_bob_info_command(self, command_str, cwd_path=None):
        """
        Executes a bob command (typically 'bob info') and returns the CompletedProcess object.
        Does not send output to the main application queue by default.
        Raises FileNotFoundError or subprocess.CalledProcessError on failure.
        """
        full_cmd = "source /etc/profile.d/modules.sh; module load tools/bob; module load tools/gchips-pd/pd-repo/{}/; {}".format(
            self.inputs['chip'], command_str
        )
        try:
            # Using a short timeout as bob info should be quick.
            # Capture output to prevent it from going to console unless needed for debug.
            process = subprocess.run(
                full_cmd, shell=True, executable='/bin/bash',
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, check=True,
                cwd=cwd_path or self.run_dir_path, timeout=60
            )
            return process
        except subprocess.CalledProcessError as e:
            # Log specific error from the command execution
            error_message = "Bob info command failed: {}\nSTDOUT: {}\nSTDERR: {}".format(e.cmd, e.stdout, e.stderr)
            self.queue.put(("log", error_message)) # Log to main queue for this specific error
            raise # Re-raise to be handled by calling method
        except FileNotFoundError as e:
            self.queue.put(("log", "ERROR: Bob executable or environment setup not found for info command. {}".format(e)))
            raise
        except Exception as e: # Catch any other unexpected errors
            self.queue.put(("log", "ERROR: Unexpected error executing bob info: {}".format(e)))
            raise

    def _get_node_status(self, run_name, node_pattern):
        full_run_path = os.path.join(self.run_dir_path, run_name)
        # Sanitize node_pattern for use in filename
        sanitized_node_pattern = re.sub(r'[^a-zA-Z0-9_.-]', '_', node_pattern)
        json_file_name = "bob_info_temp_{}_{}.json".format(run_name, sanitized_node_pattern)
        json_file_path = os.path.join(self.run_dir_path, json_file_name)

        info_cmd_str = "bob info -r {} -o {}".format(full_run_path, json_file_path)

        try:
            self._execute_bob_info_command(info_cmd_str, cwd_path=self.work_area_path)
            if not os.path.exists(json_file_path):
                self.queue.put(("log", "ERROR: Bob info command created no output JSON file: {}".format(json_file_path)))
                return 'UNKNOWN'

            with open(json_file_path, 'r') as f:
                jobs_data = json.load(f)

            for job in jobs_data:
                if job.get("jobname", "") == node_pattern:
                    return job.get("status", "UNKNOWN").upper()
            return 'NOT_FOUND'
        except FileNotFoundError: # Raised by _execute_bob_info_command
             self.queue.put(("log", "ERROR (_get_node_status): bob execution environment issue for '{}'.".format(run_name)))
             return 'UNKNOWN'
        except subprocess.CalledProcessError: # Raised by _execute_bob_info_command
            self.queue.put(("log", "ERROR (_get_node_status): 'bob info' failed for run '{}', node '{}'.".format(run_name, node_pattern)))
            return 'UNKNOWN' # Error already logged by _execute_bob_info_command
        except json.JSONDecodeError:
            self.queue.put(("log", "ERROR: Could not decode JSON from '{}' for node status.".format(json_file_path)))
            return 'UNKNOWN'
        except Exception as e:
            self.queue.put(("log", "ERROR (_get_node_status): Unexpected error processing '{}', node '{}': {}".format(run_name, node_pattern, e)))
            return 'UNKNOWN'
        finally:
            if os.path.exists(json_file_path):
                try:
                    os.remove(json_file_path)
                except OSError as e:
                    self.queue.put(("log", "WARN: Could not delete temp JSON file '{}': {}".format(json_file_path, e)))

    def _is_run_completed(self, run_name):
        full_run_path = os.path.join(self.run_dir_path, run_name)
        # Sanitize run_name for use in filename
        sanitized_run_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', run_name)
        json_file_name = "bob_info_temp_run_{}.json".format(sanitized_run_name)
        json_file_path = os.path.join(self.run_dir_path, json_file_name)

        info_cmd_str = "bob info -r {} -o {}".format(full_run_path, json_file_path)

        fail_states = {"FAILED", "ERROR", "KILLED", "INVALID"}
        running_states = {"RUNNING", "PENDING", "SUBMITTED", "WAITING"} # Add any other relevant non-terminal states

        try:
            self._execute_bob_info_command(info_cmd_str, cwd_path=self.work_area_path)
            if not os.path.exists(json_file_path):
                self.queue.put(("log", "ERROR: Bob info command created no output JSON file for run completion check: {}".format(json_file_path)))
                return False

            with open(json_file_path, 'r') as f:
                jobs_data = json.load(f)

            if not jobs_data: # No jobs reported
                self.queue.put(("log", "WARN: No jobs found in 'bob info' output for run '{}'. Considering not completed.".format(run_name)))
                return False

            found_valid_job = False
            for job in jobs_data:
                status = job.get("status", "UNKNOWN").upper()
                if status in fail_states:
                    return False # Any failed job means the run is not successfully completed
                if status in running_states:
                    return False # Any running/pending job means not yet complete
                if status == "VALID":
                    found_valid_job = True

            # If we went through all jobs, none failed, none are running,
            # then completion depends on if we found at least one valid job.
            return found_valid_job

        except FileNotFoundError:
             self.queue.put(("log", "ERROR (_is_run_completed): bob execution environment issue for '{}'.".format(run_name)))
             return False
        except subprocess.CalledProcessError: # Error already logged by _execute_bob_info_command
            self.queue.put(("log", "ERROR (_is_run_completed): 'bob info' failed for run '{}'.".format(run_name)))
            return False
        except json.JSONDecodeError:
            self.queue.put(("log", "ERROR: Could not decode JSON from '{}' for run completion check.".format(json_file_path)))
            return False
        except Exception as e:
            self.queue.put(("log", "ERROR (_is_run_completed): Unexpected error processing '{}': {}".format(run_name, e)))
            return False
        finally:
            if os.path.exists(json_file_path):
                try:
                    os.remove(json_file_path)
                except OSError as e:
                    self.queue.put(("log", "WARN: Could not delete temp JSON file '{}': {}".format(json_file_path, e)))

    def _get_user_email(self):
        try: return "{}@google.com".format(subprocess.check_output('whoami', universal_newlines=True).strip())
        except Exception: return "askakshay@google.com" 

    def _exec(self, cmd, cwd=None):
        self.queue.put(("log", "CMD: {}".format(cmd)))
        if self._stop_event.is_set(): return False
        try:
            full_cmd = "source /etc/profile.d/modules.sh; module load tools/bob; module load tools/gchips-pd/pd-repo/{}/; {}".format(self.inputs['chip'], cmd)
            p = subprocess.run(full_cmd, shell=True, executable='/bin/bash', stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, check=True, cwd=cwd or self.run_dir_path)
            if p.stdout: self.queue.put(("log", p.stdout))
            if p.stderr: self.queue.put(("log", "STDERR: {}".format(p.stderr)))
            return True
        except Exception as e:
            err_msg = e.stderr if hasattr(e, 'stderr') else str(e)
            self.queue.put(("log", "ERROR executing command: {}\n{}".format(cmd, err_msg)))
            return False

    def _generate_final_var_content(self, flow_name, base_var_template=""):
        try:
            main_run_name = "{}_main".format(self.inputs['run_name'])
            base_content = base_var_template.format(work_area_path=self.work_area_path, main_run_name=main_run_name, block=self.inputs['block'])
            
            gui_custom_var = ""
            if self.inputs.get('custom_var') and os.path.exists(self.inputs['custom_var']):
                with open(self.inputs['custom_var'], 'r') as f: gui_custom_var = f.read()
           #TODO , use and if , elif loop for the extra vars for each stage 
            extra_vars = '#bbset EXTRA_VAR_synth "{}/run/{}/main/syn"\n'.format(self.work_area_path, main_run_name) + \
                         '#bbset EXTRA_VAR_pnr "{}/run/{}/main/pnr"\n'.format(self.work_area_path, main_run_name)
            
            return "{}\n{}\n{}".format(base_content, gui_custom_var, extra_vars)
        except Exception as e:
            self.queue.put(("log", "ERROR generating var content for {}: {}".format(flow_name, e))); return None

    def _create_final_var_file_for_flow(self, flow_name):
        try:
            template = FLOW_VAR_TEMPLATE_MAP.get(flow_name, "")
            final_content = self._generate_final_var_content(flow_name, base_var_template=template)
            if final_content is None: return None
            
            var_path = os.path.join(self.run_dir_path, "{}.var".format(flow_name.upper()))
            with open(var_path, 'w') as f: f.write(final_content)
            self.queue.put(("log", "Created var file for '{}' at {}".format(flow_name, var_path)))
            return var_path
        except IOError as e:
            self.queue.put(("log", "ERROR creating var file for {}: {}".format(flow_name, e))); return None

    # _wait_for_node_completion is now removed. Polling is integrated into run_full_flow.

    def _setup_work_area(self):
        # This method is called at the beginning of a new run.
        # For resuming, this should ideally be idempotent or skipped if already done.
        # Current implementation is fine as it checks for "repo" dir.
        if os.path.isdir(os.path.join(self.work_area_path, "repo")): return True
        self.queue.put(("status", "Creating work area..."))
        cmd = "bob wa create --chip {} --process {} --ip {} --block {} --area {}".format(self.inputs['chip'], self.inputs['process'], self.inputs['ip'], self.inputs['block'], self.work_area_path)
        return self._exec(cmd, cwd=os.path.dirname(self.work_area_path) or '.')

    def _prepare_main_var_file(self):
        main_var_path = os.path.join(self.run_dir_path, "MAIN_RUN.var")
        try:
            gui_var = ""
            if self.inputs.get('custom_var') and os.path.exists(self.inputs['custom_var']):
                with open(self.inputs['custom_var'], 'r') as f: gui_var = f.read()
            prepended = "bbset syn.elaborate.RTLFileList {{{}}}\n" \
                        "bbset syn.elaborate.InputUPFFile {{{}}}\n" \
                        "set ::FUNC_SDC_FILE_POINTER {{{}}}\n".format(self.inputs['rtl_list'], self.inputs['upf'], self.inputs['sdc'])
            with open(main_var_path, 'w') as f: f.write(prepended + gui_var)
            return main_var_path
        except IOError as e:
            self.queue.put(("log", "ERROR writing main var file: {}".format(e))); return None

    def _run_parallel_flow(self, flow_name, base_stages, is_forced_rerun):
        try:
            run_name = "{}_{}".format(self.inputs['run_name'], flow_name.upper())
             # Ensure this parallel run is tracked if it's going to be started
            if run_name not in self.active_run_names:
                self.active_run_names.append(run_name) # Add here before any exec calls for this run_name

            self.queue.put(("status", "Configuring parallel flow: {}".format(flow_name)))
            var_file = self._create_final_var_file_for_flow(flow_name)
            if not var_file: raise Exception("Var file creation failed for {}".format(flow_name))
            
            full_run_path = os.path.join(self.run_dir_path, run_name)

            # If this is a forced re-run and the directory already exists, remove it to ensure a clean create
            if is_forced_rerun and os.path.exists(full_run_path):
                self.queue.put(("log", f"INFO: Deleting existing directory for forced re-run of {run_name}: {full_run_path}"))
                try:
                    shutil.rmtree(full_run_path)
                    self.queue.put(("log", f"INFO: Successfully deleted directory {full_run_path}"))
                except Exception as e:
                    self.queue.put(("log", f"ERROR: Failed to delete directory {full_run_path}: {e}"))
                    # If deletion fails, it's a critical issue for a forced re-run
                    raise Exception(f"Directory deletion failed for forced re-run of {flow_name}: {e}")

            if not os.path.exists(full_run_path):
                if not self._exec("bob create -r {} -s {} -v {}".format(full_run_path, base_stages, var_file)):
                    raise Exception("Create failed for {}".format(flow_name))
            # else: # Commenting out the skip message as it might be confusing if run is re-triggered.
                # self.queue.put(("log", "Bob create skipped for existing run directory: {}".format(full_run_path)))

            # Determine if this parallel flow needs a forced re-run
            bob_run_cmd_parallel = "bob run -r {}".format(full_run_path)
            # The is_forced_rerun parameter is passed to this function
            # This parameter is determined in run_full_flow based on is_resuming and if the parallel flow was previously completed.
            if is_forced_rerun: # is_forced_rerun is a new parameter for this method
                bob_run_cmd_parallel += " -f"
                self.queue.put(("log", "Adding -f to parallel flow {} bob run cmd: {}".format(flow_name, bob_run_cmd_parallel)))

            if not self._exec(bob_run_cmd_parallel):
                raise Exception("Run failed for {}".format(flow_name))

            # Polling for parallel flow completion
            self.queue.put(("status", "Waiting for {} completion...".format(run_name)))
            start_time_parallel = time.time()
            timeout_parallel = 300 * 60 # Example 5hr timeout for parallel flows, adjust as needed
            while time.time() - start_time_parallel < timeout_parallel:
                if self._stop_event.is_set():
                    self.queue.put(("log", "Stop event for parallel flow {}.".format(run_name)))
                    # Mark as failed due to stop, so it's not considered successful if stop occurs
                    self.failed_node = self.failed_node or run_name + " (Stopped)"
                    self.parallel_run_results.put(("FAILED", flow_name))
                    return # Exit this thread

                if self._is_run_completed(run_name):
                    self.queue.put(("log", "Parallel flow {} completed successfully.".format(run_name)))
                    self.parallel_run_results.put(("SUCCESS", flow_name))
                    return # Exit this thread

                # Check if the run failed explicitly (not just not completed)
                # This requires checking individual job statuses if _is_run_completed only returns True on all VALID
                # For simplicity, we'll rely on timeout or _is_run_completed finding a FAILED state.
                # A more granular check could use _get_node_status on critical nodes if they exist for parallel runs.
                self.queue.put(("status", "Polling {}... Elapsed: {}s".format(run_name, int(time.time() - start_time_parallel))))
                time.sleep(60) # Poll interval

            # If loop finishes, it's a timeout
            self.failed_node = self.failed_node or run_name + " (Timeout)"
            self.queue.put(("log", "ERROR: Parallel flow {} timed out.".format(run_name)))
            self.parallel_run_results.put(("FAILED", flow_name))

        except Exception as e: # Catch exceptions from create/run or other issues
            self.failed_node = self.failed_node or flow_name # Use flow_name if run_name wasn't set
            self.queue.put(("log", "ERROR in parallel flow {}: {}".format(flow_name, e)))
            self.parallel_run_results.put(("FAILED", flow_name))


    # def _wait_for_run_completion(self, run_name, timeout_minutes=120): # Commented out as polling is now in _run_parallel_flow
    #     ...

    def run_full_flow(self):
        is_resuming = self.is_continue_run_flag
        self.is_continue_run_flag = False # Reset flag

        if is_resuming:
            self.queue.put(("log", "--- PD COMPILER RESUMING FLOW ---"))
            self.failed_node = None
            self.active_run_names = []
            self.parallel_run_results = queue.Queue()
        else:
            self.queue.put(("log", "--- PD COMPILER STARTING NEW FLOW ---"))
            if not self._setup_work_area(): return

        main_var_file = self._prepare_main_var_file()
        if not main_var_file: return

        main_run_name = "{}_main".format(self.inputs['run_name'])
        full_main_run_path = os.path.join(self.run_dir_path, main_run_name)

        # --- SYN Stage ---
        self.queue.put(("status", "Processing SYN Stage..."))
        syn_completed_successfully = False
        initial_syn_check_was_valid = False # For -f flag logic
        if is_resuming:
            syn_status = self._get_node_status(main_run_name, SYN_COMPLETION_NODE)
            self.queue.put(("log", "[Resume] Initial SYN status: {}".format(syn_status)))
            if syn_status == 'VALID':
                syn_completed_successfully = True
                initial_syn_check_was_valid = True
        
        if not syn_completed_successfully:
            if main_run_name not in self.active_run_names:
                 self.active_run_names.append(main_run_name)

            if not os.path.exists(full_main_run_path) or not is_resuming: # If dir missing, or fresh run
                if not self._exec("bob create -r {} -s syn pnr -v {}".format(full_main_run_path, main_var_file)):
                    self.queue.put(("failed", self.failed_node or "Main Create (SYN)")); return

            bob_run_cmd_syn = "bob run -r {}".format(full_main_run_path)
            if is_resuming and not initial_syn_check_was_valid:
                bob_run_cmd_syn += " -f"
                self.queue.put(("log", "Adding -f to SYN bob run cmd: {}".format(bob_run_cmd_syn)))
            if not self._exec(bob_run_cmd_syn):
                self.queue.put(("failed", self.failed_node or "Main Run (SYN)")); return

            self.queue.put(("status", "Waiting for SYN completion..."))
            start_time_syn = time.time(); timeout_syn = 300 * 60
            while time.time() - start_time_syn < timeout_syn:
                if self._stop_event.is_set(): self.queue.put(("log", "Stop event during SYN.")); return
                status = self._get_node_status(main_run_name, SYN_COMPLETION_NODE)
                if status == 'VALID': syn_completed_successfully = True; break
                if status in {'FAILED', 'ERROR', 'KILLED', 'INVALID'}:
                    self.failed_node = "{}/{} ({})".format(main_run_name, SYN_COMPLETION_NODE, status)
                    self.queue.put(("failed", self.failed_node)); return
                self.queue.put(("status", "Polling SYN... Last status: {}. Elapsed: {}s".format(status, int(time.time() - start_time_syn))))
                time.sleep(60)

            if not syn_completed_successfully:
                self.failed_node = self.failed_node or "{}/{} (Timeout)".format(main_run_name, SYN_COMPLETION_NODE)
                self.queue.put(("failed", self.failed_node)); return

        self.queue.put(("log", "SYN stage: {}".format("COMPLETED" if syn_completed_successfully else "SKIPPED/FAILED")))
        if not syn_completed_successfully: return

        # --- Post-SYN Parallel Flows ---
        self.queue.put(("status", "Processing Post-SYN Parallel Flows..."))
        post_syn_flows = {LEC_R2S_FLOW: 'lec', VCLP_S_FLOW: 'vclp'}
        active_threads_post_syn = []
        for flow_name, base_stage_for_flow in post_syn_flows.items():
            if base_stage_for_flow in self.selected_stages:
                parallel_run_name = "{}_{}".format(self.inputs['run_name'], flow_name.upper())
                flow_already_completed = False
                if is_resuming and self._is_run_completed(parallel_run_name):
                    self.queue.put(("log", "[Resume] Post-SYN flow {} already completed.".format(parallel_run_name)))
                    flow_already_completed = True

                if not flow_already_completed:
                    is_current_flow_a_forced_rerun = False
                    if is_resuming: # and not flow_already_completed (implicit from above)
                        is_current_flow_a_forced_rerun = True # Force if resuming and not completed

                    t = threading.Thread(target=self._run_parallel_flow, args=(flow_name, base_stage_for_flow, is_current_flow_a_forced_rerun))
                    active_threads_post_syn.append(t); t.start()
        for t in active_threads_post_syn: t.join()
        if self.failed_node and any(fn.startswith(self.inputs['run_name']+"_"+key.upper()) for key in post_syn_flows.keys() for fn in [self.failed_node]): return


        # --- PNR Stage ---
        self.queue.put(("status", "Processing PNR Stage..."))
        pnr_completed_successfully = False
        initial_pnr_check_was_valid = False # For -f flag logic
        if is_resuming: # SYN must have been valid to reach here
            pnr_status = self._get_node_status(main_run_name, PNR_COMPLETION_NODE)
            self.queue.put(("log", "[Resume] Initial PNR status: {}".format(pnr_status)))
            if pnr_status == 'VALID':
                pnr_completed_successfully = True
                initial_pnr_check_was_valid = True

        if not pnr_completed_successfully:
            if main_run_name not in self.active_run_names: self.active_run_names.append(main_run_name)

            bob_run_cmd_pnr = "bob run -r {}".format(full_main_run_path)
            if is_resuming and not initial_pnr_check_was_valid:
                bob_run_cmd_pnr += " -f"
                self.queue.put(("log", "Adding -f to PNR bob run cmd: {}".format(bob_run_cmd_pnr)))
            if not self._exec(bob_run_cmd_pnr): # Idempotent, add -f if needed for resume
                 self.queue.put(("failed", self.failed_node or "Main Run (PNR)")); return

            self.queue.put(("status", "Waiting for PNR completion..."))
            start_time_pnr = time.time(); timeout_pnr = 300 * 60
            while time.time() - start_time_pnr < timeout_pnr:
                if self._stop_event.is_set(): self.queue.put(("log", "Stop event during PNR.")); return
                status = self._get_node_status(main_run_name, PNR_COMPLETION_NODE)
                if status == 'VALID': pnr_completed_successfully = True; break
                if status in {'FAILED', 'ERROR', 'KILLED', 'INVALID'}:
                    self.failed_node = "{}/{} ({})".format(main_run_name, PNR_COMPLETION_NODE, status)
                    self.queue.put(("failed", self.failed_node)); return
                self.queue.put(("status", "Polling PNR... Last status: {}. Elapsed: {}s".format(status, int(time.time() - start_time_pnr))))
                time.sleep(60)

            if not pnr_completed_successfully:
                self.failed_node = self.failed_node or "{}/{} (Timeout)".format(main_run_name, PNR_COMPLETION_NODE)
                self.queue.put(("failed", self.failed_node)); return

        self.queue.put(("log", "PNR stage: {}".format("COMPLETED" if pnr_completed_successfully else "SKIPPED/FAILED")))
        if not pnr_completed_successfully: return

        # --- Post-PNR Parallel Flows ---
        self.queue.put(("status", "Processing Post-PNR Parallel Flows..."))
        post_pnr_flows = {
            PDP_PEX_FLOW: 'pdp pex', 'sta': 'sta', 'emir': 'emir', 'pdv': 'pdv',
            LEC_S2P_FLOW: 'lec', VCLP_P_FLOW: 'vclp',
        }
        active_threads_post_pnr = []
        for flow_name, stages_for_flow in post_pnr_flows.items():
            if any(s in self.selected_stages for s in FLOW_TO_BASE_STAGE.get(flow_name, stages_for_flow).split()):
                parallel_run_name = "{}_{}".format(self.inputs['run_name'], flow_name.upper())
                flow_already_completed = False
                if is_resuming and self._is_run_completed(parallel_run_name):
                    self.queue.put(("log", "[Resume] Post-PNR flow {} already completed.".format(parallel_run_name)))
                    flow_already_completed = True

                if not flow_already_completed:
                    is_current_flow_a_forced_rerun = False
                    if is_resuming: # and not flow_already_completed
                        is_current_flow_a_forced_rerun = True # Force if resuming and not completed

                    t = threading.Thread(target=self._run_parallel_flow, args=(flow_name, stages_for_flow, is_current_flow_a_forced_rerun))
                    active_threads_post_pnr.append(t); t.start()
        for t in active_threads_post_pnr: t.join()
        if self.failed_node and any(fn.startswith(self.inputs['run_name']+"_"+key.upper()) for key in post_pnr_flows.keys() for fn in [self.failed_node]): return
        
        # --- Final Completion ---
        if self._stop_event.is_set(): self.queue.put(("log", "Stop event before final completion.")); return
        if self.failed_node: self.queue.put(("log", "Flow ended with failure at: {}.".format(self.failed_node))); return

        final_parallel_failures = 0
        processed_results = []
        while not self.parallel_run_results.empty():
            status, flow_name = self.parallel_run_results.get_nowait()
            processed_results.append({'name': flow_name, 'status': status}) # Store for logging/debugging if needed
            if status == "FAILED":
                final_parallel_failures += 1
                if not self.failed_node:
                    self.failed_node = "Parallel flow {} failed.".format(flow_name)
        
        if final_parallel_failures > 0:
            self.queue.put(("failed", self.failed_node or "{} parallel flow(s) failed.".format(final_parallel_failures)))
            return

        self.queue.put(("completed", None))

    def stop_bob_runs(self):
        self.queue.put(("status", "Stopping all active runs..."))
        self._continue_event.set()

if __name__ == "__main__":
    app = PDCompilerApp()
    app.mainloop()

