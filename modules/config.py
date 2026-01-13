import os
import json
import gi

gi.require_version('Gimp', '3.0')
from gi.repository import Gimp

class PluginConfig:
    """
    Central configuration management
    Handles directory structures, file paths, and default generation parameters
    """

    # Default connection settings
    DEFAULT_SERVER = "127.0.0.1:8188"
    DEFAULT_TIMEOUT = 60

    # Fallback lists used if the API connection cannot be established
    SAMPLERS = [
        "euler", "euler_cfg_pp", "euler_ancestral", "euler_ancestral_cfg_pp", 
        "heun", "heunpp2", "dpm_2", "dpm_2_ancestral", "lsm", "dpm_fast", 
        "dpm_adaptive", "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_sde_gpu", 
        "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_2m_sde_gpu", "dpmpp_3m_sde", 
        "dpmpp_3m_sde_gpu", "ddpm", "lcm", "ipndm", "ipndm_v", "deis", 
        "ddim", "uni_pc", "uni_pc_bh2", "None"
    ]

    SCHEDULERS = [
        "normal", "karras", "exponential", "sgm_uniform", 
        "simple", "ddim_uniform", "beta", "None"
    ]

    def __init__(self):
        self._init_paths()
        self._ensure_directories()
        
        # Runtime settings
        self.default_server_address = self.DEFAULT_SERVER
        self.timeout_duration = self.DEFAULT_TIMEOUT

    def _init_paths(self):
        """Initialize all directory and file paths"""
        # Base Directories
        self.gimp_dir = Gimp.directory()
        self.comfy_dir = os.path.join(self.gimp_dir, "comfy")
        
        # Subdirectories
        self.data_dir = os.path.join(self.comfy_dir, "data")
        self.workflows_dir = os.path.join(self.comfy_dir, "Workflows")
        self.temp_images_dir = os.path.join(self.comfy_dir, "temporary_images")
        self.styles_dir = os.path.join(self.comfy_dir, "styles")

        # File Paths
        self.error_log_path = os.path.join(self.comfy_dir, "logfile.txt")
        self.workflows_json_path = os.path.join(self.workflows_dir, "workflows.json")
        self.temp_workflow_path = os.path.join(self.workflows_dir, "temp_workflow.json")
        self.last_inputs_path = os.path.join(self.data_dir, "last_inputs_persistent.json")
        self.generic_workflow_path = os.path.join(self.data_dir, "GIMP_workflow.json")
        
        # Filenames
        self.log_file_name = "data_receive_log.txt"

    def _ensure_directories(self):
        """Ensure the plugin directory structure exists."""
        required_dirs = [
            self.comfy_dir,
            self.data_dir,
            self.workflows_dir,
            self.temp_images_dir,
            self.styles_dir
        ]
        
        for directory in required_dirs:
            os.makedirs(directory, exist_ok=True)

    def load_workflows(self):
        """
        Loads workflows from disk
        Returns:
            list: A list of workflow dictionaries, or an empty list on failure
        """
        if not os.path.exists(self.workflows_json_path):
            return []
            
        try:
            with open(self.workflows_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("workflows", [])
        except (IOError, json.JSONDecodeError):
            # Return empty list if file is unreadable or corrupt
            return []

    def get_workflow_path(self, filename):
        """Helper to resolve a full path for a file in the data directory"""
        return os.path.join(self.data_dir, filename)

settings = PluginConfig()