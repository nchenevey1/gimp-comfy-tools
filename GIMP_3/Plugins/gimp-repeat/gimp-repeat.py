#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys

# GIMP imports
import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
gi.require_version('GimpUi', '3.0')
from gi.repository import GimpUi
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gio
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Gtk
from gi.repository import Gegl

# Python imports
import os
import json
import random
import uuid
import requests
import websocket
from io import BytesIO
import shutil

# ****************************************
#           User defaults
# ****************************************

default_server_address = "127.0.0.1:8188"

comfy_dir_name = "comfy"

last_inputs_file_name = "last_inputs.json"

generated_workflow_file_name = "GIMP_workflow.json"

log_file_name = "data_receive_log.txt"

select_all_if_empty = True

timeout_duration = 60  # Timeout duration in seconds

def create_comfy_dir():
    gimp_dir = Gimp.directory()
    comfy_dir = os.path.join(gimp_dir, comfy_dir_name)
    if not os.path.exists(comfy_dir):
        raise Exception("Comfy directory does not exist.")
    return comfy_dir

# ***********************************************
#           Generation Functions
# ***********************************************
    
def insert_preview_layer(image, preview_data, prev_layer, display_exists, comfy_dir):
    preview_layer = prev_layer

    temp_file_path = os.path.join(comfy_dir, "temp.jpg")
    jfif = BytesIO(preview_data)
    
    with open(temp_file_path, "wb") as temp_file:
        temp_file.write(jfif.read())
        
    preview_layer = Gimp.file_load_layer(1, image, Gio.File.new_for_path(temp_file_path))

    if prev_layer:
        prev_layer.set_name("prev")
    preview_layer.set_name("preview")

    if not display_exists:
        preview_layer_height = preview_layer.get_height()
        preview_layer_width = preview_layer.get_width()
        image.resize(preview_layer_width, preview_layer_height, 0, 0)

    image.insert_layer(preview_layer, None, 0)

    if prev_layer:
        image.remove_layer(prev_layer)

    Gimp.progress_set_text("Generating...")
    Gimp.displays_flush()
    
    return preview_layer

def open_websocket(server_address, client_id):
    try:
        ws = websocket.WebSocket()
        ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id), timeout=timeout_duration)
    except Exception as e:
        Gimp.message("Error Websocket: " + str(e))
        return []
    return ws

def is_jsonable(x):
    try:
        json.loads(x)
        return True
    except (TypeError, OverflowError, ValueError):
        return False
    
def write_to_log_file(data, comfy_dir):
    log_file_path = os.path.join(comfy_dir, log_file_name)
    try:
        with open(log_file_path, "a") as log_file:
            log_file.write(data + "\n\n")
    except Exception as log_error:
        Gimp.message(f"Error writing to log file: {log_error}")

def generate(workflow, image, server_address, display_exists, comfy_dir):
    Gimp.progress_set_text("Generating...")
    try:
        client_id = str(uuid.uuid4())
        ws = open_websocket(server_address, client_id)
        payload = {"prompt": workflow, "client_id": client_id}
        url = "http://{0}/api/prompt".format(server_address)
        r = requests.post(url, json=payload)
    except Exception as e:
        Gimp.message("Error Posting: " + str(e))
        return []
    
    preview_layer = None
    new_display = None
    outputs = []

    try:
        while True:
            data_receive = ws.recv()

            # # Debugging
            # write_to_log_file(data_receive, comfy_dir)

            if is_jsonable(data_receive):
                message_json = json.loads(data_receive)
                if message_json["type"] == "executed":
                    if "output" in message_json["data"]:
                        if "images" in message_json["data"]["output"]:
                            outputs = message_json["data"]["output"]["images"]
                        elif not message_json["data"]["output"]:
                            Gimp.message("No outputs found.")
                            break
                elif message_json["type"] == "execution_success":
                    break
                elif "exception_message" in message_json["data"]:
                    error_message = ("Error: " + message_json["data"]["exception_message"])
                    Gimp.message("Error:\n" + error_message)
                    break
                elif message_json["type"] == "progress":
                    step = message_json["data"]["value"]
                    max_steps = message_json["data"]["max"]
                    fraction = float(step) / max_steps
                    Gimp.progress_update(fraction)
                elif message_json["type"] == "execution_interrupted":
                    Gimp.message("Execution interrupted.")
                    break
            else:
                int_value = data_receive[0] + data_receive[1] + data_receive[2] + data_receive[3]
                if int_value == 1:
                    preview_data = data_receive[8:]
                    try:
                        preview_layer = insert_preview_layer(image, preview_data, preview_layer, display_exists, comfy_dir)
                        if not new_display and not display_exists:
                            new_display = Gimp.Display.new(image)
                    except:
                        continue
                else:
                    Gimp.message("Received data is not JSON or preview.\nReceived start value is {}".format(str(int_value)))
    except Exception as e:
        Gimp.message(f"Error Generate Loop: {e}")

    if preview_layer:
        Gimp.Image.remove_layer(image, preview_layer)
  
    return outputs, new_display

def insert_outputs(outputs, image, server_address, seed, display, display_exists, comfy_dir):
    for output in outputs:
        if not "filename" in output:
            continue
        output_file_name = output["filename"]
        Gimp.progress_set_text("Downloading...")
        Gimp.progress_pulse()
        output_file_path = os.path.join(comfy_dir, output_file_name)
        url = "http://{0}/api/view".format(server_address)
        with requests.get(url, params=output, stream=True) as r:
            with open(output_file_path, 'wb') as f:
                shutil.copyfileobj(r.raw, f)

        ext = output_file_name.split(".")[-1]
        temp_file_name = "temp.{0}".format(ext)
        temp_file_path = os.path.join(comfy_dir, temp_file_name)
        shutil.move(output_file_path, temp_file_path)
        output_layer = Gimp.file_load_layer(1, image, Gio.File.new_for_path(temp_file_path))
        output_layer.set_name(str(seed))

        output_layer_height = output_layer.get_height()
        output_layer_width = output_layer.get_width()
        image.resize(output_layer_width, output_layer_height, 0, 0)

        image.insert_layer(output_layer, None, 0)
        if not display and not display_exists:
            display = Gimp.Display.new(image)

def insert_seed_into_workflow(workflow, seed):
    nodes = workflow.values()
    for node in nodes:
            inputs = node.get("inputs", {})
            if "seed" in inputs:
                inputs["seed"] = seed
    return workflow

# ***********************************************
#           GIMP Plugin
# ***********************************************
class GimpRepeat (Gimp.PlugIn):
    def do_query_procedures(self):
        return [ "nc-gimprepeat" ]
    
    def do_set_i18n (self, name):
        return False
    
    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name, 
                                            Gimp.PDBProcType.PLUGIN, 
                                            self.run_repeat, None)
        procedure.set_sensitivity_mask (Gimp.ProcedureSensitivityMask.ALWAYS)

        procedure.set_menu_label("Repeat Generation")
        procedure.add_menu_path('<Image>/Generate')
        procedure.set_documentation("ComfyUI Repeat", 
                                    "Repeat a generation with ComfyUI", 
                                    name)
        procedure.set_attribution("Nicholas Chenevey", 
                                "Nicholas Chenevey", 
                                "2025")
        return procedure
    
    def run_repeat(self, procedure, run_mode, image, drawables, config, run_data):
        try:
            display_exists = True
            if not image:
                display_exists = False
                image = Gimp.Image.new(64, 64, Gimp.ImageBaseType.RGB)

            comfy_dir = create_comfy_dir()
            workflow_json_path = os.path.join(comfy_dir, generated_workflow_file_name)

            if not os.path.exists(workflow_json_path):
                Gimp.message(f"Workflow JSON file not found at {workflow_json_path}")
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
            
            # Load Workflow JSON
            with open(workflow_json_path, "r") as file:
                workflow_data = file.read()
            workflow = json.loads(workflow_data)

            seed = random.randint(1, 4294967295)

            # Insert Seed into Workflow
            workflow = insert_seed_into_workflow(workflow, seed)

            # Prepare Outputs
            outputs, display = generate(workflow, image, default_server_address, display_exists, comfy_dir)

            # Insert Outputs
            insert_outputs(outputs, image, default_server_address, seed, display, display_exists, comfy_dir)
        except Exception as e:
            Gimp.message(f"Error Main: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

Gimp.main(GimpRepeat.__gtype__, sys.argv)