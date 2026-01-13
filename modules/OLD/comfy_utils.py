#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import uuid
import requests
import websocket
import shutil
from io import BytesIO

# GIMP imports
import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
from gi.repository import Gio

# Local imports
import config
import gimp_utils as GimpUtils

def prepare_workflow(workflow_path, main_dict, lora_dict, ksampler_dict):
    """
    Prepares the workflow by updating it with the provided parameters.
    """
    save_inputs = {}
    
    if not os.path.exists(workflow_path):
        raise FileNotFoundError(f"Workflow file not found: {workflow_path}")
        
    with open(workflow_path, "r", encoding="utf-8") as file:
        workflow = json.load(file)

    if "nodes" in workflow:
        raise Exception('Workflow is in UI format! Please export in API format.')

    for node_id, node in workflow.items():
        inputs = node.get("inputs", {})
        meta = node.get("_meta", {})
        title = meta.get("title", "").lower()
        
        # 1. KSampler Settings
        if ksampler_dict:
            if "steps" in inputs and "cfg" in inputs and "sampler_name" in inputs:
                inputs["steps"] = ksampler_dict["steps"]
                inputs["cfg"] = ksampler_dict["cfg"]
                inputs["sampler_name"] = ksampler_dict["sampler"]
                inputs["scheduler"] = ksampler_dict["scheduler"]

        # 2. Prompts
        if "text" in inputs:
            if "pos" in title and main_dict.get("positive_prompt"):
                inputs["text"] = main_dict["positive_prompt"]
                save_inputs["positive_generate_prompt"] = main_dict["positive_prompt"]
            elif "neg" in title and main_dict.get("negative_prompt"):
                inputs["text"] = main_dict["negative_prompt"]
                save_inputs["negative_generate_prompt"] = main_dict["negative_prompt"]

        # 3. Seed
        if "seed" in inputs and main_dict.get("seed"):
            inputs["seed"] = main_dict["seed"]

        # 4. Dimensions
        if "width" in inputs and "height" in inputs:
            if main_dict.get("image_width") and main_dict.get("image_height"):
                inputs["width"] = main_dict["image_width"]
                inputs["height"] = main_dict["image_height"]

        # 5. Checkpoint
        if "ckpt_name" in inputs and main_dict.get("checkpoint_selection"):
            inputs["ckpt_name"] = main_dict["checkpoint_selection"]

        # 6. LoRAs
        if lora_dict and "lora" in title:
            lora_index = 1
            for lora_name, strength in lora_dict.items():
                key_on = f"lora_{lora_index}"
                inputs[key_on] = {
                    "on": True,
                    "lora": lora_name,
                    "strength": strength
                }
                lora_index += 1

    return workflow, save_inputs

def insert_preview_layer(image, preview_data, prev_layer):
    """
    Insert a preview layer from raw bytes.
    """
    temp_file_path = os.path.join(config.settings.temp_images_dir, "preview_temp.jpg")
    
    with open(temp_file_path, "wb") as temp_file:
        temp_file.write(preview_data)
    
    new_layer = Gimp.file_load_layer(1, image, Gio.File.new_for_path(temp_file_path))
    new_layer.set_name("preview")

    # Resize canvas if needed
    if new_layer.get_width() != image.get_width() or new_layer.get_height() != image.get_height():
        image.resize(new_layer.get_width(), new_layer.get_height(), 0, 0)

    image.insert_layer(new_layer, None, 0)
    
    # Remove previous preview layer to prevent stacking previews
    if prev_layer and prev_layer.is_valid():
        image.remove_layer(prev_layer)

    Gimp.displays_flush()
    return new_layer

def open_websocket(server_address, client_id):
    try:
        ws = websocket.WebSocket()
        ws.connect(f"ws://{server_address}/ws?clientId={client_id}", timeout=config.settings.timeout_duration)
        return ws
    except Exception as e:
        Gimp.message(f"WebSocket Connection Error: {e}")
        return None

def generate(workflow, image, server_address):
    """
    Sends workflow to ComfyUI. 
    """
    client_id = str(uuid.uuid4())
    ws = open_websocket(server_address, client_id)
    
    if not ws:
        return [], None

    try:
        payload = {"prompt": workflow, "client_id": client_id}
        url = f"http://{server_address}/api/prompt"
        req = requests.post(url, json=payload)
        req.raise_for_status()
    except Exception as e:
        Gimp.message(f"Error sending prompt: {e}")
        ws.close()
        return [], None

    Gimp.progress_set_text("Waiting for generation...")
    
    preview_layer = None
    new_display = None
    outputs = []
    
    while True:
        try:
            out = ws.recv()
            
            # Binary Message = Preview Image
            if isinstance(out, bytes):
                event_type = int.from_bytes(out[0:4], "big") 
                if event_type == 1:
                    image_data = out[8:]
                    preview_layer = insert_preview_layer(image, image_data, preview_layer)
                    
                    # Fix: Handle display creation if none exists
                    if not new_display:
                        # Gimp 3.0: We check if the image is attached to any display
                        # If not, create one.
                        # Note: We can't easily check "get_display_count" anymore.
                        # A safe bet for a new image created in run_generate is to create it once.
                        # We will handle this in the main loop or here if critical.
                        # For now, we attempt to create it if we haven't tracked it yet.
                        try:
                            new_display = Gimp.Display.new(image)
                        except:
                            pass # Display likely already exists or handled by GIMP
                continue

            # Text Message = JSON Status
            else:
                message = json.loads(out)
                msg_type = message["type"]
                msg_data = message["data"]
                
                if msg_type == "progress":
                    step = msg_data["value"]
                    max_steps = msg_data["max"]
                    Gimp.progress_update(step / max_steps)
                    Gimp.progress_set_text(f"Step {step}/{max_steps}")
                    
                elif msg_type == "executing":
                    if msg_data["node"] is None:
                        break # Finished

                elif msg_type == "executed":
                    if "output" in msg_data and "images" in msg_data["output"]:
                        outputs += msg_data["output"]["images"]
                            
                elif msg_type == "execution_error":
                     Gimp.message(f"ComfyUI Error: {msg_data.get('exception_message', 'Unknown error')}")
                     break

        except websocket.WebSocketException:
            break
        except Exception as e:
            Gimp.message(f"Error loop: {e}")
            break
        
    ws.close()
    return outputs, new_display

def insert_outputs(outputs, image, server_address, seed, display):
    """
    Downloads final images. If outputs exist, removes the preview layer first.
    """
    if not outputs:
        # If no outputs, we assume preview is the result.
        return

    # --- FIX: Use get_layers() for GIMP 3.0 ---
    layers = image.get_layers()
    if layers:
        for layer in layers:
            if layer.get_name() == "preview":
                image.remove_layer(layer)
                break

    Gimp.progress_set_text("Downloading Results...")

    for output in outputs:
        filename = output.get("filename")
        if not filename:
            continue

        url = f"http://{server_address}/api/view"
        ext = filename.split(".")[-1]
        safe_name = f"result_{seed}.{ext}"
        temp_path = os.path.join(config.settings.temp_images_dir, safe_name)
        
        try:
            with requests.get(url, params=output, stream=True) as r:
                r.raise_for_status()
                with open(temp_path, 'wb') as f:
                    shutil.copyfileobj(r.raw, f)
            
            final_layer = Gimp.file_load_layer(1, image, Gio.File.new_for_path(temp_path))
            final_layer.set_name(f"Seed: {seed}")
            
            if final_layer.get_width() != image.get_width() or final_layer.get_height() != image.get_height():
                image.resize(final_layer.get_width(), final_layer.get_height(), 0, 0)
                
            image.insert_layer(final_layer, None, 0)
            
        except Exception as e:
            Gimp.message(f"Failed to load output {filename}: {e}")

    # Final Display Check
    if not display:
        try:
             display = Gimp.Display.new(image)
        except:
             pass
        
    Gimp.displays_flush()