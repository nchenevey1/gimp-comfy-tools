#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# This module provides utility functions for integrating GIMP with ComfyUI
# It handles workflow preparation, communication with the server via HTTP and WebSocket, preview layer insertion,
# and output image handling within GIMP.
# Functions:
#     prepare_workflow(workflow_path, main_dict, lora_dict, ksampler_dict):
#         Prepares and updates a workflow JSON file with user-specified parameters such as prompts, seed, checkpoint,
#         LoRA settings, and image dimensions.
#     insert_preview_layer(image, preview_data, prev_layer):
#         Inserts a preview layer into the specified GIMP image using temporary image data, replacing any previous preview layer.
#     open_websocket(server_address, client_id):
#         Opens a WebSocket connection to the specified server address using the provided client ID.
#     generate(workflow, image, server_address):
#         Sends a workflow to the ComfyUI server for image generation, handles progress updates and preview images,
#         and returns the generated outputs and display.
#     insert_outputs(outputs, image, server_address, seed, display):
#         Downloads generated output images from the server, inserts them as layers into the GIMP image, and manages display creation.
# Constants:
#     comfy_dir_name: Name of the directory for ComfyUI-related files within the GIMP user directory.
#     gimp_dir: Path to the GIMP user directory.
#     comfy_dir: Path to the ComfyUI directory within the GIMP user directory.
#     temp_images_dir: Path to the temporary images directory for storing intermediate files.
#     timeout_duration: Timeout duration (in seconds) for network operations.
# Dependencies:
#     - requests, websocket-client

# Python imports
import os
import json
import uuid
import requests
import websocket
import shutil
from io import BytesIO
import importlib.util

# GIMP imports
import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
from gi.repository import Gio

gimp_utils_import_path = os.path.join(os.path.dirname(__file__), "gimp_utils.py")
gimp_utils_spec = importlib.util.spec_from_file_location("gimp_utils", gimp_utils_import_path)
GimpUtils = importlib.util.module_from_spec(gimp_utils_spec)
gimp_utils_spec.loader.exec_module(GimpUtils)

comfy_dir_name = "comfy"
gimp_dir = Gimp.directory()
comfy_dir = os.path.join(gimp_dir, comfy_dir_name)
os.makedirs(comfy_dir, exist_ok=True)

# Create a temporary images directory
temp_images_dir = os.path.join(comfy_dir, "temporary_images")
os.makedirs(temp_images_dir, exist_ok=True)

timeout_duration = 60  # Timeout duration in seconds

def prepare_workflow(workflow_path, main_dict, lora_dict, ksampler_dict):
    """Prepare the workflow by updating it with the provided parameters."""
    save_inputs = {}
    with open(workflow_path, "r") as file:
        workflow_data = file.read()
    
    workflow = json.loads(workflow_data)
    
    if "nodes" in workflow:
        raise Exception('Export workflow in API format!')
    nodes = workflow.values()

    if ksampler_dict:
        for node in nodes:
            inputs = node.get("inputs", {})
            if "steps" in inputs:
                inputs["steps"] = ksampler_dict["steps"]
            if "cfg" in inputs:
                inputs["cfg"] = ksampler_dict["cfg"]
            if "sampler_name" in inputs:
                inputs["sampler_name"] = ksampler_dict["sampler"]
            if "scheduler" in inputs:
                inputs["scheduler"] = ksampler_dict["scheduler"]
    
    if main_dict["positive_prompt"]: 
        for node in nodes:
            inputs = node.get("inputs", {})
            meta = node.get("_meta", {})
            title = meta.get("title").lower()
            if "text" in inputs and "pos" in title:
                inputs["text"] = main_dict["positive_prompt"]
                save_inputs["positive_generate_prompt"] = main_dict["positive_prompt"]

    if main_dict["negative_prompt"]: 
        for node in nodes:
            inputs = node.get("inputs", {})
            meta = node.get("_meta", {})
            title = meta.get("title").lower()
            if "text" in inputs and "neg" in title:
                inputs["text"] = main_dict["negative_prompt"]
                save_inputs["negative_generate_prompt"] = main_dict["negative_prompt"]
    
    if main_dict["seed"]: 
        for node in nodes:
            inputs = node.get("inputs", {})
            if "seed" in inputs:
                inputs["seed"] = main_dict["seed"]

    if main_dict["checkpoint_selection"]: 
        for node in nodes:
            inputs = node.get("inputs", {})
            if "ckpt_name" in inputs:
                inputs["ckpt_name"] = main_dict["checkpoint_selection"]

    if lora_dict:
        for node in nodes:
            inputs = node.get("inputs", {})
            meta = node.get("_meta", {})
            title = meta.get("title").lower()
            if "power lora loader" in title:
                lora_index = 1
                for key, value in lora_dict.items():
                    inputs[f"lora_{lora_index}"] = {
                        "on": True,
                        "lora": key,
                        "strength": value
                    }
                    lora_index += 1

    if main_dict["image_height"] or main_dict["image_width"]:
        for node in nodes:
            inputs = node.get("inputs", {})
            if "height" in inputs and "width" in inputs:
                inputs["height"] = main_dict["image_height"]
                inputs["width"] = main_dict["image_width"]

    return workflow, save_inputs
    
def insert_preview_layer(image, preview_data, prev_layer):
    """Insert a preview layer from specified temporary image data into the GIMP image."""
    preview_layer = prev_layer

    temp_file_path = os.path.join(temp_images_dir, "temp.jpg")
    jfif = BytesIO(preview_data)
    
    with open(temp_file_path, "wb") as temp_file:
        temp_file.write(jfif.read())
    
    preview_layer = Gimp.file_load_layer(1, image, Gio.File.new_for_path(temp_file_path))

    if prev_layer:
        prev_layer.set_name("prev")
    preview_layer.set_name("preview")

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
    """Open a WebSocket connection to the specified server address."""
    try:
        ws = websocket.WebSocket()
        ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id), timeout=timeout_duration)
    except Exception as e:
        Gimp.message("Error Websocket: " + str(e))
        return []
    return ws


def generate(workflow, image, server_address):
    """Generate an image using the provided workflow and server address."""
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
    
    Gimp.progress_set_text("Receiving...")
    preview_layer = None
    new_display = None
    outputs = []

    while True:
        data_receive = ws.recv()

        if GimpUtils.is_jsonable(data_receive):
            message_json = json.loads(data_receive)
            if message_json["type"] == "executed":
                if "output" in message_json["data"]:
                    if "images" in message_json["data"]["output"]:
                        outputs = message_json["data"]["output"]["images"]
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
                    preview_layer = insert_preview_layer(image, preview_data, preview_layer)
                    if not new_display:
                        new_display = Gimp.Display.new(image)
                except:
                    continue
            else:
                Gimp.message("Received data is not JSON or preview.\nReceived start value is {}".format(str(int_value)))

    if preview_layer:
        Gimp.Image.remove_layer(image, preview_layer)
    
    ws.close()
  
    return outputs, new_display

def insert_outputs(outputs, image, server_address, seed, display):
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
        temp_file_path = os.path.join(temp_images_dir, temp_file_name)
        shutil.move(output_file_path, temp_file_path)
        output_layer = Gimp.file_load_layer(1, image, Gio.File.new_for_path(temp_file_path))
        output_layer.set_name(str(seed))

        output_layer_height = output_layer.get_height()
        output_layer_width = output_layer.get_width()
        image.resize(output_layer_width, output_layer_height, 0, 0)

        image.insert_layer(output_layer, None, 0)

        if not display:
            display = Gimp.Display.new(image)