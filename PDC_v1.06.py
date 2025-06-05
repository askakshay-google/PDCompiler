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
        self.geometry("850x800")

        self.process_thread = None
        self.bob_manager = None
        self.log_visible = False
        self.is_continuing_run = False
        self.update_queue = queue.Queue()

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

        self.stage_selection = StageSelectionFrame(setup_frame)
        self.stage_selection.grid(row=0, column=1, sticky="nsew")

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
            if self.bob_manager:
                self.run_button.config(text="Run", style="Run.TButton")
                self.is_continuing_run = False
                self.set_controls_state('disabled')
                self.stop_button.config(state='normal')
            return

        inputs = self.setup_inputs.get_values()
        stages = self.stage_selection.get_selected_stages()

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
                    messagebox.showerror("Run Failed", "Stage failed at node: {}\nAn email has been sent.\nPress 'Continue' to restart from this point.".format(data))
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
        for widget in [self.setup_inputs, self.stage_selection]:
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

    def _validate_inputs(self, inputs): return True 
    def show_stage_selection(self): self.stage_selection.show()
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
        self.stage_callback = stage_callback
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
        self.stageflow_box = ttk.Button(self, text='Select Stages', command=self.stage_callback, width=15)
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

class StageSelectionFrame(ttk.LabelFrame):
    def __init__(self, parent, **kwargs):
        super(StageSelectionFrame, self).__init__(parent, text="Stages", **kwargs)
        self.vars = {}
        self.grid_columnconfigure([0, 1], weight=1)
        for i, stage in enumerate(DEFAULT_STAGES):
            var = tk.BooleanVar(value=True)
            chk = ttk.Checkbutton(self, text=stage.upper(), variable=var)
            chk.grid(row=i // 2, column=i % 2, sticky="w", padx=20, pady=5)
            self.vars[stage] = var; chk.config(state='disabled')
    def show(self):
        for child in self.winfo_children(): child.config(state='normal')
        messagebox.showinfo("Select Stages", "Choose the stages to include in the flow.", parent=self)
    def get_selected_stages(self): return [s for s, v in self.vars.items() if v.get()]
        
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

    def _wait_for_node_completion(self, run_name, node_pattern, timeout_minutes=120):
        log_prefix = "WAIT({} in {})".format(node_pattern, run_name)
        self.queue.put(("status", "{}: Starting...".format(log_prefix)))
        start_time, fail_states = time.time(), {"FAILED", "INVALID", "ERROR", "KILLED"}
        while True:
            if self._stop_event.is_set(): return "ABORTED"
            if (time.time() - start_time) > (timeout_minutes * 60): return "TIMEOUT"
            
            json_file = os.path.join(self.run_dir_path, "bob_info_{}.json".format(run_name))
            full_run_path = os.path.join(self.run_dir_path, run_name)
            info_cmd = "bob info -r {} -o {}".format(full_run_path, json_file)
            try:
                full_cmd = "source /etc/profile.d/modules.sh; module load tools/bob; module load tools/gchips-pd/pd-repo/{}/; {}".format(self.inputs['chip'], info_cmd)
                subprocess.run(full_cmd, shell=True, executable='/bin/bash', check=True, timeout=60, cwd=self.work_area_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                with open(json_file, 'r') as f: jobs = json.load(f)
                
                found = False
                for job in jobs:
                    if job.get("jobname", "") == node_pattern:
                        found, status = True, job.get("status", "").upper()
                        self.queue.put(("status", "{}: Node {} status is {}".format(log_prefix, node_pattern, status)))
                        if status == "VALID": return "VALID"
                        if status in fail_states: self.failed_node = "{}/{}".format(run_name, node_pattern); return "FAILED"
                        break
                if not found: self.queue.put(("status", "{}: Waiting for node...".format(log_prefix)))
            except Exception as e:
                self.queue.put(("log", "WARN: {}: Poll error: {}. Retrying...".format(log_prefix, e)))
            finally:
                if os.path.exists(json_file):
                    try: os.remove(json_file)
                    except OSError: pass
            time.sleep(30)

    def _setup_work_area(self):
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

    def _run_parallel_flow(self, flow_name, base_stages):
        try:
            run_name = "{}_{}".format(self.inputs['run_name'], flow_name.upper())
            self.active_run_names.append(run_name)
            self.queue.put(("status", "Configuring parallel flow: {}".format(flow_name)))
            var_file = self._create_final_var_file_for_flow(flow_name)
            if not var_file: raise Exception("Var file creation failed")
            
            full_run_path = os.path.join(self.run_dir_path, run_name)
            if not self._exec("bob create -r {} -s {} -v {}".format(full_run_path, base_stages, var_file)): raise Exception("Create failed")
            if not self._exec("bob run -r {}".format(full_run_path)): raise Exception("Run failed")
            if self._wait_for_run_completion(run_name) != "VALID": raise Exception("Flow did not complete")
            self.parallel_run_results.put(("SUCCESS", flow_name))
        except Exception as e:
            self.failed_node = flow_name
            self.queue.put(("log", "ERROR in parallel flow {}: {}".format(flow_name, e)))
            self.parallel_run_results.put(("FAILED", flow_name))

    def _wait_for_run_completion(self, run_name, timeout_minutes=120):
        start_time = time.time()
        while time.time() - start_time < (timeout_minutes * 60):
            if self._stop_event.is_set(): return "ABORTED"
            try:
                full_run_path = os.path.join(self.run_dir_path, run_name)
                info_cmd = "bob info -r {}".format(full_run_path)
                full_cmd = "source /etc/profile.d/modules.sh; module load tools/bob; module load tools/gchips-pd/pd-repo/{}/; {}".format(self.inputs['chip'], info_cmd)
                output = subprocess.check_output(full_cmd, shell=True, executable='/bin/bash', cwd=self.work_area_path, universal_newlines=True, stderr=subprocess.DEVNULL)
                if "status=\"FAILED\"" in output or "status=\"ERROR\"" in output: return "FAILED"
                if "status=\"RUNNING\"" not in output: return "VALID"
            except Exception: pass
            time.sleep(30)
        return "TIMEOUT"

    def run_full_flow(self):
        if not self._setup_work_area(): self.queue.put(("failed", "Work Area Setup")); return
        main_var_file = self._prepare_main_var_file()
        if not main_var_file: self.queue.put(("failed", "Var File Prep")); return

        main_run_name = "{}_main".format(self.inputs['run_name'])
        self.active_run_names.append(main_run_name)
        
        full_main_run_path = os.path.join(self.run_dir_path, main_run_name)
        if not self._exec("bob create -r {} -s syn pnr -v {}".format(full_main_run_path, main_var_file)): self.queue.put(("failed", "Main Create")); return
        if not self._exec("bob run -r {}".format(full_main_run_path)): self.queue.put(("failed", "Main Run")); return

        if self._wait_for_node_completion(main_run_name, SYN_COMPLETION_NODE) != "VALID": 
            if not self._stop_event.is_set(): self.queue.put(("failed", self.failed_node or "SYN")); 
            return
        
        threads = []
        post_syn = {LEC_R2S_FLOW: 'lec', VCLP_S_FLOW: 'vclp'}
        for flow, stage in post_syn.items():
            if stage in self.selected_stages:
                t = threading.Thread(target=self._run_parallel_flow, args=(flow, stage)); threads.append(t); t.start()

        if self._wait_for_node_completion(main_run_name, PNR_COMPLETION_NODE) != "VALID": 
            if not self._stop_event.is_set(): self.queue.put(("failed", self.failed_node or "PNR")); 
            return
        
        post_pnr = {
            PDP_PEX_FLOW: 'pdp pex', 'sta': 'sta', 'emir': 'emir', 'pdv': 'pdv',
            LEC_S2P_FLOW: 'lec', VCLP_P_FLOW: 'vclp',
        }
        for flow, stages in post_pnr.items():
            if any(s in self.selected_stages for s in FLOW_TO_BASE_STAGE.get(flow, flow).split()):
                t = threading.Thread(target=self._run_parallel_flow, args=(flow, stages)); threads.append(t); t.start()
        
        for t in threads: t.join()

        if self._stop_event.is_set():
            return

        num_fails = 0
        while not self.parallel_run_results.empty():
            if self.parallel_run_results.get()[0] == "FAILED": num_fails += 1
        
        if num_fails > 0: self.queue.put(("failed", "{} parallel flow(s) failed.".format(num_fails)))
        else: self.queue.put(("completed", None))

    def stop_bob_runs(self):
        self.queue.put(("status", "Stopping all active runs..."))
        self._stop_event.set()
        self._continue_event.set()
        
        run_names_to_stop = list(self.active_run_names)
        for run_name in run_names_to_stop:
            self.queue.put(("log", "Issuing stop for bob run: {}".format(run_name)))
            full_run_path = os.path.join(self.run_dir_path, run_name)
            self._exec("bob stop -r {}".format(full_run_path), cwd=self.work_area_path)
        
        self.queue.put(("log", "All stop commands issued."))
        self.queue.put(("reset", None))

    def stop(self): 
        self._stop_event.set()
        self._continue_event.set()

if __name__ == "__main__":
    app = PDCompilerApp()
    app.mainloop()

