#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Python imports
import os
import json
import random
import sys

import importlib.util

gimp_dialogs_import_path = os.path.join(os.path.dirname(__file__), "gimp_dialogs.py")
gimp_dialogs_spec = importlib.util.spec_from_file_location("gimp_dialogs", gimp_dialogs_import_path)
GimpDialogs = importlib.util.module_from_spec(gimp_dialogs_spec)
gimp_dialogs_spec.loader.exec_module(GimpDialogs)

gimp_utils_import_path = os.path.join(os.path.dirname(__file__), "gimp_utils.py")
gimp_utils_spec = importlib.util.spec_from_file_location("gimp_utils", gimp_utils_import_path)
GimpUtils = importlib.util.module_from_spec(gimp_utils_spec)
gimp_utils_spec.loader.exec_module(GimpUtils)

comfy_utils_import_path = os.path.join(os.path.dirname(__file__), "comfy_utils.py")
comfy_utils_spec = importlib.util.spec_from_file_location("comfy_utils", comfy_utils_import_path)
ComfyUtils = importlib.util.module_from_spec(comfy_utils_spec)
comfy_utils_spec.loader.exec_module(ComfyUtils)

# GIMP imports
import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
gi.require_version('GimpUi', '3.0')
from gi.repository import GimpUi
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gegl

# ****************************************
#           User defaults
# ****************************************

comfy_dir_name = "comfy"
gimp_dir = Gimp.directory()
comfy_dir = os.path.join(gimp_dir, comfy_dir_name)
os.makedirs(comfy_dir, exist_ok=True)

default_server_address = "127.0.0.1:8188"

# Find the directory containing this script
error_log_file_path = os.path.join(comfy_dir, "logfile.txt")

# Create a temporary images directory
temp_images_dir = os.path.join(comfy_dir, "temporary_images")
os.makedirs(temp_images_dir, exist_ok=True)

# Read favorites.json from comfy_dir and check existence
workflows_dir = os.path.join(comfy_dir, "Workflows")
os.makedirs(workflows_dir, exist_ok=True)

favorites_json_path = os.path.join(workflows_dir, "favorites.json")
favorites_exists = os.path.exists(favorites_json_path)
if favorites_exists:
    with open(favorites_json_path, "r", encoding="utf-8") as f:
        favorites_data = json.load(f)
    favorites = favorites_data.get("favorites", [])
else:
    favorites = []

### Set values for defaults ###
data_dir = os.path.join(comfy_dir, "data")
os.makedirs(data_dir, exist_ok=True)

last_inputs_file_name = "last_inputs.json"
last_inputs_file_path = os.path.join(data_dir, last_inputs_file_name)

generic_workflow_file_name = "GIMP_workflow.json"
generic_workflow_file_path = os.path.join(data_dir, generic_workflow_file_name)
generated_workflow_file_name = "GIMP_generate_workflow.json"
generated_workflow_file_path = os.path.join(data_dir, generated_workflow_file_name)

log_file_name = "data_receive_log.txt"

timeout_duration = 60  # Timeout duration in seconds

############################################################################################################
# Create Sampler and Scheduler options
SamplerOptions = ["euler", "euler_cfg_pp", "euler_ancestral", "euler_ancestral_cfg_pp", "heun", "heunpp2", "dpm_2", "dpm_2_ancestral", "lsm", "dpm_fast", "dpm_adaptive",
                    "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_sde_gpu", "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_2m_sde_gpu", "dpmpp_3m_sde", "dpmpp_3m_sde_gpu", "ddpm", "lcm", "ipndm", 
                    "ipndm_v", "deis", "ddim", "uni_pc", "uni_pc_bh2", "None"]

SchedulerOptions = ["normal", "karras", "exponential", "sgm_uniform", "simple", "ddim_uniform", "beta", "None"]

def get_main_dialog(procedure, config, previous_inputs):
    GimpUi.init('nc-gimp-generate')
    Gegl.init(None)
    main_dict = {}
    dialog = GimpDialogs.MainProcedureDialog(procedure, config, previous_inputs)
    response = dialog.run()
    if response:
        try:
            dialog.save_current_inputs_to_history()
            main_dict["positive_prompt"], main_dict["negative_prompt"] = dialog.get_text_results()
            main_dict["workflow"] = dialog.selected_workflow_path
        except Exception as e:
            GimpUtils.write_to_log_file(f"Error in get_main_dialog (workflow): {e}\n", error_log_file_path)
        try:
            checkpoint_index = dialog.get_selected_items(dialog.checkpoints_view)
            if checkpoint_index:
                main_dict["checkpoint_selection"] = dialog.get_selected_checkpoint(dialog.checkpoints_view)
            else:
                main_dict["checkpoint_selection"] = None
        except:
            main_dict["checkpoint_selection"] = None
        try:
            main_dict["lora_selection"] = dialog.get_selected_lora_data(dialog.loras_view)
        except:
            main_dict["lora_selection"] = None
    else:
        return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

    main_dict["seed"] = config.get_property('seed')
    main_dict["image_height"] = config.get_property('height')
    main_dict["image_width"] = config.get_property('width')
    main_dict["export_format"] = config.get_property('format')
    ksampler_dict = {"steps": config.get_property('steps'), "cfg": config.get_property('cfg'), "sampler": config.get_property('sampler'), "scheduler": config.get_property('scheduler')}
    if ksampler_dict["steps"] == 0:
        ksampler_dict = None
    dialog.destroy()

    return main_dict, ksampler_dict

def get_lora_dialog(procedure, config, lora_selection):
    # Lora Dialog
    if lora_selection:
        lora_dialog = GimpDialogs.LoraDialog(procedure, config, lora_selection)
        lora_response = lora_dialog.run()
        if lora_response:
            lora_dict = lora_dialog.get_lora_dict()
            lora_dialog.destroy()
        else:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
    else:
        lora_dict = None
    return lora_dict


# ***********************************************
#           GIMP Plugin
# ***********************************************
class GimpGenerate (Gimp.PlugIn):
    def do_query_procedures(self):
        return [ "nc-gimp-generate" ]
    
    def do_set_i18n (self, name):
        return False
    
    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name, 
                                            Gimp.PDBProcType.PLUGIN, 
                                            self.run_iti, None)
        procedure.set_sensitivity_mask (Gimp.ProcedureSensitivityMask.ALWAYS)
        
        procedure.set_image_types("*")
        procedure.set_menu_label("Generate")
        procedure.add_menu_path('<Image>/Generate')
        procedure.set_documentation("ComfyUI Generate", 
                                    "Generate an image with ComfyUI", 
                                    name)
        procedure.set_attribution("Nicholas Chenevey", 
                                  "Nicholas Chenevey", 
                                  "2025")

        ## Ksampler Settings ##
        # Steps
        procedure.add_int_argument("steps", "_Steps", "Steps", 0, 100, 0,
                                   GObject.ParamFlags.READWRITE)
        # Cfg
        procedure.add_double_argument("cfg", "_CFG", "CFG", 0.0, 100.0, 5.0,
                                      GObject.ParamFlags.READWRITE)
        # Sampler
        sampler_choice = Gimp.Choice.new()
        for idx, sampler in enumerate(SamplerOptions):
            sampler_choice.add(sampler, idx, sampler, sampler)
        procedure.add_choice_argument("sampler", "_Sampler", 
                                    "Sampler", sampler_choice, SamplerOptions[0],
                                    GObject.ParamFlags.READWRITE)
        # Scheduler
        scheduler_choice = Gimp.Choice.new()
        for idx, scheduler in enumerate(SchedulerOptions):
            scheduler_choice.add(scheduler, idx, scheduler, scheduler)
        procedure.add_choice_argument("scheduler", "_Scheduler", 
                                    "Scheduler", scheduler_choice, SchedulerOptions[0],
                                    GObject.ParamFlags.READWRITE)
        
        # Image Height
        procedure.add_int_argument("height", "_Height", "Height", 1, 10000, 1152,
                                GObject.ParamFlags.READWRITE)
        # Image Width
        procedure.add_int_argument("width", "_Width", "Width", 1, 10000, 896,
                                GObject.ParamFlags.READWRITE)
        # Seed
        procedure.add_int_argument("seed", "_Seed", "Seed", -1, 2147483647, -1,
                                GObject.ParamFlags.READWRITE)

        # Export Format
        export_format_choice = Gimp.Choice.new()
        export_format_choice.add("PNG", 1, "PNG", "PNG")
        export_format_choice.add("JPG", 2, "JPG", "JPG")
        procedure.add_choice_argument("format", "_Format", 
                                    "Format", export_format_choice, "PNG",
                                    GObject.ParamFlags.READWRITE)
        
        return procedure
    
    def run_iti(self, procedure, run_mode, image, drawables, config, run_data):
        try:
            if run_mode == Gimp.RunMode.INTERACTIVE:
                Gimp.progress_init("Waiting...")
                previous_inputs, previous_inputs_path = GimpUtils.load_previous_inputs(last_inputs_file_path)
                try:
                    main_dict, ksampler_dict = get_main_dialog(procedure, config, previous_inputs)
                    if main_dict["lora_selection"]:
                        lora_dict = get_lora_dialog(procedure, config, main_dict["lora_selection"])
                    else:
                        lora_dict = None
                except Exception as e:
                    return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

                new_image = Gimp.Image.new(64, 64, Gimp.ImageBaseType.RGB)

                Gimp.Image.undo_group_start(new_image)
                Gimp.context_push()

                try:
                    if main_dict["seed"] == -1 or main_dict["seed"] == 0:
                        main_dict["seed"] = random.randint(1, 4294967295)

                    # Prepare Inputs
                    workflow_path = main_dict["workflow"]
                    if not workflow_path:
                        Gimp.message("No workflow selected. Please select a workflow from the dropdown.")
                        return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
                    
                    # Prepare Workflow
                    Gimp.progress_set_text("Preparing workflow...")
                    try:
                        workflow, text_inputs = ComfyUtils.prepare_workflow(workflow_path, main_dict, lora_dict, ksampler_dict)
                    except Exception as e:
                        Gimp.message(f"Error Preparing Workflow: {e}")
                        return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
                    
                    if text_inputs:
                        GimpUtils.update_json_file(text_inputs, previous_inputs_path)

                    # Write Workflow
                    GimpUtils.write_to_json_file(workflow, generated_workflow_file_path)
                    GimpUtils.write_to_json_file(workflow, generic_workflow_file_path)

                    # Prepare Outputs
                    outputs, display = ComfyUtils.generate(workflow, new_image, default_server_address)

                    # Insert Outputs
                    ComfyUtils.insert_outputs(outputs, new_image, default_server_address, main_dict["seed"], display)
                except Exception as e:
                    Gimp.message(f"Error: {e}")
                    return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
                finally:
                    Gimp.context_pop()
                    Gimp.Image.undo_group_end(new_image)
                    Gimp.displays_flush()
                
        except Exception as e:
            Gimp.message(f"Error Main: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())


        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

Gimp.main(GimpGenerate.__gtype__, sys.argv)