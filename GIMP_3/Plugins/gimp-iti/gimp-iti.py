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

favorites = [
  {
    "path": "C:\\Path\\To\\Workflow_1.json",
    "title": "Unique Title 1",
  },
  {
    "path": "C:\\Path\\To\\Workflow_2.json",
    "title": "Unique Title 2",
  },
  {
    "path": "C:\\Path\\To\\Workflow_3.json",
    "title": "Unique Title 3",
  },
  {
    "path": "C:\\Path\\To\\Workflow_4.json",
    "title": "Unique Title 4",
  }
]

lora_file_path = "C:\\Path\\To\\lora_folder"
lora_icon_path = "C:\\Path\\To\\lora_icon_folder"

checkpoints_file_path = "C:\\Path\\To\\checkpoints_folder"
checkpoints_icon_path = "C:\\Path\\To\\checkpoints_icon_folder"

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
        os.makedirs(comfy_dir)
    return comfy_dir

def get_model_files_with_icons(model_file_path, model_icon_path):
    model_files = [f for f in os.listdir(model_file_path) if f.endswith(".safetensors")]
    model_data = []

    for model_file in model_files:
        file_name, file_ext = os.path.splitext(model_file)
        icon_file = None
        for ext in [".png", ".jpg"]:
            potential_icon = os.path.join(model_icon_path, file_name + ext)
            if os.path.exists(potential_icon):
                icon_file = potential_icon
                break
        model_data.append({
            "file": os.path.join(model_file_path, model_file),
            "icon": icon_file
        })

    return model_data

lora_data = get_model_files_with_icons(lora_file_path, lora_icon_path)
checkpoint_data = get_model_files_with_icons(checkpoints_file_path, checkpoints_icon_path)

############################################################################################################
# Create Sampler and Scheduler options
SamplerOptions = ["euler", "euler_cfg_pp", "euler_ancestral", "euler_ancestral_cfg_pp", "heun", "heunpp2", "dpm_2", "dpm_2_ancestral", "lsm", "dpm_fast", "dpm_adaptive",
                    "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_sde_gpu", "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_2m_sde_gpu", "dpmpp_3m_sde", "dpmpp_3m_sde_gpu", "ddpm", "lcm", "ipndm", 
                    "ipndm_v", "deis", "ddim", "uni_pc", "uni_pc_bh2", "None"]

SchedulerOptions = ["normal", "karras", "exponential", "sgm_uniform", "simple", "ddim_uniform", "beta", "None"]

# ***********************************************
#           Image to Image Generation Functions
# ***********************************************
def prepare_input(img_type, image, drawable, server_address, area, ext, comfy_dir):
    try:
        
        temp_file_name = "temp.{0}".format(ext)
        temp_file_path = os.path.join(comfy_dir, temp_file_name)
        temp_file_path_gio = Gio.File.new_for_path(temp_file_path)
        last_image_inputs_file = os.path.join(comfy_dir, last_inputs_file_name)
        last_image_inputs_data = {}
        comfy_name = None
        try:
            if os.path.exists(last_image_inputs_file):
                with open(last_image_inputs_file, "r") as file:
                    last_image_inputs_data = json.load(file)
                    if last_image_inputs_data.get(img_type):
                        comfy_name = last_image_inputs_data[img_type]["comfy_name"]
        except Exception as e:
            Gimp.message(f"Error Preparing path for {img_type}: {e}")
            quit()

        try:
            if img_type == "mask":
                mask_layer = None
                width, height = image.get_width(), image.get_height()
                temp_image = image.duplicate()
                mask_layer = Gimp.Layer.new(temp_image, "Selection Mask", width, height, 0, 100, Gimp.LayerMode.NORMAL)
                temp_image.insert_layer(mask_layer, None, 0)
                if not Gimp.Selection.is_empty(image):
                    Gimp.context_set_foreground(Gegl.Color.new("0.0, 0.0, 0.0, 1.0"))
                    mask_layer.edit_fill(3)
                else:
                    mask_layer.fill(3)
            elif img_type == "image":
                temp_image = image
        except Exception as e:
            Gimp.message(f"Error Preparing image layer for {img_type}: {e}")
            quit()
        
        Gimp.progress_set_text("Exporting...")
        Gimp.file_save(1, temp_image, temp_file_path_gio, None)

        shutil.copy(temp_file_path, os.path.join(comfy_dir, "mask.png"))

        project_name = Gimp.Image.get_name(image)
        project_name = project_name.replace(" ", "_")
        project_name = project_name.replace("[", "")
        project_name = project_name.replace("]", "")
        current_number = 1

        if last_image_inputs_data.get(img_type):
            last_project_name = last_image_inputs_data[img_type]["project_name"]
            last_number = last_image_inputs_data[img_type]["number"]
            if last_project_name == project_name and last_number:
                current_number = last_number + 1

        url = "http://{0}/api/upload/image".format(server_address)
        number_str = "{0:05d}".format(current_number)
        upload_name = "gimp_{0}_{1}_{2}.{3}".format(project_name, img_type, number_str, ext)
        content_type = "image/jpeg"

        if ext == "png":
            content_type = "image/png"

        form_data_files = { "image": (upload_name, open(temp_file_path, "rb"), content_type) }
        Gimp.progress_set_text("Uploading...")
        
        try:
            r = requests.post(url, files=form_data_files)
            comfy_name = r.json()["name"]
        except Exception as e:
            raise e

        last_image_inputs_data[img_type] = {
            "project_name": project_name,
            "number": current_number,
            "comfy_name": comfy_name,
            "ext": ext
        }

        update_json_file(last_image_inputs_data, last_image_inputs_file)

    except Exception as e:
        Gimp.message(f"Error Preparing Input {img_type}: {e}")
        quit()

    return comfy_name

def prepare_workflow(workflow_path, main_dict, lora_dict, ksampler_dict, input_image, input_mask):
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
                save_inputs["positive_ITI_prompt"] = main_dict["positive_prompt"]

    if main_dict["negative_prompt"]: 
        for node in nodes:
            inputs = node.get("inputs", {})
            meta = node.get("_meta", {})
            title = meta.get("title").lower()
            if "text" in inputs and "neg" in title:
                inputs["text"] = main_dict["negative_prompt"]
                save_inputs["negative_ITI_prompt"] = main_dict["negative_prompt"]
    
    if main_dict["denoise"]: 
        for node in nodes:
            inputs = node.get("inputs", {})
            if "denoise" in inputs:
                inputs["denoise"] = main_dict["denoise"]
    
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

    load_image_node = None
    load_image_key = None

    for key, node in workflow.items():
        if node.get("class_type") == "LoadImage":
            load_image_node = node
            load_image_key = key
            break
    
    if load_image_node:
        input_image_name = input_image
        inputs = load_image_node.get("inputs", {})
        inputs["image"] = input_image_name
        linked_mask_nodes = []
        for node in nodes:
            inputs = node.get("inputs", {})
            if "mask" in inputs and inputs["mask"][0] == load_image_key and inputs["mask"][1] == 1:
                linked_mask_nodes.append(node)
        
        # Create mask node for mask inputs
        if len(linked_mask_nodes):
            input_mask_name = input_mask
            last_key_number = max(map(int, workflow.keys()))
            load_mask_node_key = str(last_key_number + 1)
            workflow[load_mask_node_key] = {
                "inputs": {
                    "image": input_mask_name,
                    "channel": "green",
                    "upload": "image"
                },
                "class_type": "LoadImageMask",
                "_meta": {
                    "title": "Load Image (as Mask)"
                }
            }
            for linked_mask_node in linked_mask_nodes:
                linked_mask_node["inputs"]["mask"] = [load_mask_node_key, 0]
        
    return workflow, save_inputs
    
def insert_preview_layer(image, preview_data, prev_layer, comfy_dir):
    preview_layer = prev_layer

    temp_file_path = os.path.join(comfy_dir, "temp.jpg")
    jfif = BytesIO(preview_data)
    
    with open(temp_file_path, "wb") as temp_file:
        temp_file.write(jfif.read())
        
    preview_layer = Gimp.file_load_layer(1, image, Gio.File.new_for_path(temp_file_path))

    if prev_layer:
        prev_layer.set_name("prev")
    preview_layer.set_name("preview")
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

def write_to_json_file(data, file_path):
    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)

def update_json_file(data, file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            existing_data = json.load(file)
    else:
        existing_data = {}
    existing_data.update(data)
    write_to_json_file(existing_data, file_path)

def load_previous_inputs(comfy_dir):
    previous_inputs_path = os.path.join(comfy_dir, last_inputs_file_name)
    previous_inputs = {}
    if os.path.exists(previous_inputs_path):
        with open(previous_inputs_path, "r") as text_inputs_file:
            previous_inputs = json.load(text_inputs_file)
    return previous_inputs, previous_inputs_path

def generate(workflow, image, server_address, comfy_dir):
    Gimp.progress_set_text("Generating...")

    client_id = str(uuid.uuid4())
    ws = open_websocket(server_address, client_id)
    payload = {"prompt": workflow, "client_id": client_id}
    url = "http://{0}/api/prompt".format(server_address)
    r = requests.post(url, json=payload)
    
    preview_layer = None
    outputs = []

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
                    preview_layer = insert_preview_layer(image, preview_data, preview_layer, comfy_dir)
                except:
                    continue
            else:
                Gimp.message("Received data is not JSON or preview.\nReceived start value is {}".format(str(int_value)))

    if preview_layer:
        Gimp.Image.remove_layer(image, preview_layer)

    ws.close()
  
    return outputs

def insert_outputs(outputs, image, server_address, seed, offsets, comfy_dir):
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
        image.insert_layer(output_layer, None, 0)

def get_workflow_path(workflow_name):
    for favorite in favorites:
        if favorite["title"] == workflow_name:
            return favorite["path"]
    return None

# ***********************************************
#           GIMP Dialog and Procedure
# ***********************************************
class MainProcedureDialog(GimpUi.ProcedureDialog):
    def __init__(self, procedure, config, previous_inputs):
        super().__init__(procedure=procedure, config=config)
        self.set_default_size(700, 700)

        # Apply CSS
        self.apply_css()

        # Get the main content area of the ProcedureDialog
        content_area = self.get_content_area()
        content_area.get_style_context().add_class("content_area")

        # Create a scrolled window for the entire dialog
        scrolled_window = self.create_scrolled_window("content_scrolled_window", Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC, 400, 300)

        # Create a container (VBox) to hold all UI elements inside the scroll area
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content_box.set_border_width(10)
        content_box.get_style_context().add_class("content_box")

        # Positive Prompt
        self.positive_textview = self.add_labeled_textview(content_box, "Positive Prompt", previous_inputs.get("positive_ITI_prompt", ""))
        # Negative Prompt
        self.negative_textview = self.add_labeled_textview(content_box, "Negative Prompt", previous_inputs.get("negative_ITI_prompt", ""))

        # Populate GIMP's default argument UI elements
        self.fill(None)  # This adds the GIMP argument widgets to the content area

        child_list = content_area.get_children()
        ksampler_children = []
        for idx, child in enumerate(child_list):
            if idx == len(child_list) - 1 or idx == len(child_list) - 2: # Don't remove the last two children (buttons)
                continue
            content_area.remove(child) # Remove Children
            if idx < 4: # Skip adding the first 4 children (steps, cfg, sampler, scheduler)
                ksampler_children.append(child)
                continue
            content_box.pack_start(child, False, False, 5) # Repack Children

        # Add the KSampler children into an expandable section
        self.ksampler_section = self.add_expandable_section(content_box, "KSampler Settings", "ksampler", ksampler_children, None)

        # Expandable Icon Views
        self.checkpoints_view = self.add_expandable_section(content_box, "Checkpoints", "icon_view", checkpoint_data, Gtk.SelectionMode.SINGLE)
        self.loras_view = self.add_expandable_section(content_box, "Loras", "icon_view", lora_data, Gtk.SelectionMode.MULTIPLE)

        # Add the box inside the scrolled window
        scrolled_window.add(content_box)

        # Add the scrolled window into the GimpUi dialog
        content_area.pack_start(scrolled_window, True, True, 0)

        self.show_all()

    def apply_css(self):
        css = """
            .content_box {
                padding-left: 30px;
                padding-right: 30px;
            }
            textview {
                min-height: 100px;
            }
            .textview_box {
                margin-top: 1rem;
                min-height: 100px;
            }
            .textview_scrolled_window {
                min-height: 100px;
            }
            .expander {
                margin-bottom: 25px;
            }
            
        """
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(css.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def create_scrolled_window(self, item_class, horizontal_scroll, vertical_scroll, requested_width=400, requested_height=300):
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(horizontal_scroll, vertical_scroll)
        scrolled_window.set_size_request(requested_width, requested_height)
        scrolled_window.get_style_context().add_class(item_class)
        return scrolled_window

    def add_labeled_textview(self, parent, label_text, default_value=""):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            box.get_style_context().add_class("textview_box")

            label = Gtk.Label(label=label_text)

            scrolled_window = self.create_scrolled_window("textview_scrolled_window", Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC, 0, 0)

            textview = Gtk.TextView()
            textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)  # ensure horizontal wrapping
            textview.get_style_context().add_class("textview_text")

            # Set default text
            buffer = textview.get_buffer()
            buffer.set_text(default_value)

            scrolled_window.add(textview)

            box.pack_start(label, False, False, 0)
            box.pack_start(scrolled_window, False, False, 0)
            parent.pack_start(box, False, False, 0)

            return textview
    
    def create_icon_view(self, icon_data, selection_mode, item_class="icon_view"):
        # Pixbuf for icon, str for filename
        list_store = Gtk.ListStore(GdkPixbuf.Pixbuf, str)

        for item in icon_data:
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(item["icon"], 128, 128)  # Resize icons
            except Exception as e:
                print(f"Error loading {item['icon']}: {e}")
                pixbuf = None  # None if icon can't be loaded
            list_store.append([pixbuf, os.path.basename(item["file"]).replace(".safetensors", "")])

        # Create IconView
        icon_view = Gtk.IconView.new()
        icon_view.get_style_context().add_class(item_class)
        icon_view.set_model(list_store)
        icon_view.set_selection_mode(selection_mode)  # Allow multiple or single selection
        icon_view.set_pixbuf_column(0)  # Use first column for icons
        icon_view.set_text_column(1)    # Use second column for text
        icon_view.set_item_width(80)    # Adjust item width for better layout

        return icon_view

    def add_expandable_section(self, parent, title, sub_window, data, aux_data, width=400, height=300):
        expander = Gtk.Expander(label=title)
        expander.get_style_context().add_class("expander")

        if sub_window == "icon_view":
            window_content = self.create_icon_view(data, aux_data)
            scrolled_window = self.create_scrolled_window("expander_scrolled_window", Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC, width, height)
            scrolled_window.add(window_content)
            expander.add(scrolled_window)
        elif sub_window == "ksampler":
            window_content = self.create_ksampler_section(data)
            expander.add(window_content)
        
        parent.pack_start(expander, False, False, 0)

        return window_content
    
    def create_ksampler_section(self, data):
        ksampler_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        ksampler_box.get_style_context().add_class("ksampler_box")
        for ksampler_child in data:
            ksampler_box.pack_start(ksampler_child, False, False, 0)
        return ksampler_box
    
    def get_text_results(self):
        positive_buffer = self.positive_textview.get_buffer()
        negative_buffer = self.negative_textview.get_buffer()
        positive_text = positive_buffer.get_text(positive_buffer.get_start_iter(), positive_buffer.get_end_iter(), True)
        negative_text = negative_buffer.get_text(negative_buffer.get_start_iter(), negative_buffer.get_end_iter(), True)
        return positive_text, negative_text
    
    def get_selected_items(self, icon_view):
        return [str(item) for item in icon_view.get_selected_items()]

# ***********************************************
#           Lora Dialog and Procedure
# ***********************************************
class LoraDialog(GimpUi.ProcedureDialog):
    def __init__(self, procedure, config, lora_selection):
        super().__init__(procedure=procedure, config=config)
        self.set_default_size(700, 200)

        # Get the main content area of the ProcedureDialog
        content_area = self.get_content_area()
        content_area.get_style_context().add_class("content_area")

        # Create a scrolled window for the entire dialog
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_size_request(400, 300)  # Adjust dialog size

        # Create a container (VBox) to hold all UI elements inside the scroll area
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content_box.set_border_width(10)
        content_box.get_style_context().add_class("content_box")

        # Populate GIMP's default argument UI elements
        self.fill(None)

        for child in content_area.get_children():
            if child.get_name() == "GtkBox":
                continue
            content_area.remove(child)  # Remove them

        self.lora_box = self.create_lora_box(content_box, lora_selection)

        # Add the box inside the scrolled window
        scrolled_window.add(content_box)

        # Add the scrolled window into the GimpUi dialog
        content_area.pack_start(scrolled_window, True, True, 0)

        self.show_all()

    def create_lora_box(self, parent, lora_selection):
        lora_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        lora_box.get_style_context().add_class("lora_box")

        for lora in lora_selection:
            current_lora_data = lora_data[int(lora)]
            lora_file = current_lora_data["file"]
            lora_name = os.path.basename(lora_file).replace(".safetensors", "")

            lora_label = Gtk.Label(label=lora_name)

            # Create a double spinner for the Lora weight
            adjustment = Gtk.Adjustment(value=0, lower=-5, upper=5, step_increment=0.01, page_increment=0.1, page_size=0)
            lora_spinner = Gtk.SpinButton(adjustment=adjustment, climb_rate=0.01, digits=2)
            lora_spinner.set_numeric(True)

            lora_box.pack_start(lora_label, False, False, 0)
            lora_box.pack_start(lora_spinner, False, False, 0)
            parent.pack_start(lora_box, False, False, 0)
        return lora_box
    
    def get_lora_dict(self):
        lora_dict = {}
        children = self.lora_box.get_children()
        for i in range(0, len(children), 2):
            lora_name = children[i].get_text()
            lora_weight = children[i + 1].get_value()
            lora_dict[lora_name] = lora_weight
        return lora_dict

def get_main_dialog(procedure, config, previous_inputs):
    GimpUi.init('nc-gimpiti')
    Gegl.init(None)
    main_dict = {}
    dialog = MainProcedureDialog(procedure, config, previous_inputs)
    response = dialog.run()
    if response:
        main_dict["positive_prompt"], main_dict["negative_prompt"] = dialog.get_text_results()
        
        checkpoint_index = dialog.get_selected_items(dialog.checkpoints_view)
        if checkpoint_index:
            main_dict["checkpoint_selection"] = os.path.basename(checkpoint_data[int(checkpoint_index[0])]["file"])
        else:
            main_dict["checkpoint_selection"] = None

        main_dict["lora_selection"] = dialog.get_selected_items(dialog.loras_view)
    else:
        return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

    main_dict["denoise"] = config.get_property('denoise')
    main_dict["seed"] = config.get_property('seed')
    main_dict["workflow"] = config.get_property('workflow')
    main_dict["source_image"] = config.get_property('source')
    main_dict["export_format"] = config.get_property('format')
    ksampler_dict = {"steps": config.get_property('steps'), "cfg": config.get_property('cfg'), "sampler": config.get_property('sampler'), "scheduler": config.get_property('scheduler')}
    if ksampler_dict["steps"] == 0:
        ksampler_dict = None
    dialog.destroy()

    return main_dict, ksampler_dict

def get_lora_dialog(procedure, config, lora_selection):
    # Lora Dialog
    if lora_selection:
        lora_dialog = LoraDialog(procedure, config, lora_selection)
        lora_response = lora_dialog.run()
        if lora_response:
            lora_dict = lora_dialog.get_lora_dict()
            lora_dialog.destroy()
        else:
            raise RuntimeError("Lora dialog was canceled by the user.")
    else:
        lora_dict = None
    return lora_dict


# ***********************************************
#           GIMP Plugin
# ***********************************************
class GimpITI (Gimp.PlugIn):
    def do_query_procedures(self):
        return [ "nc-gimpiti" ]
    
    def do_set_i18n (self, name):
        return False
    
    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name, 
                                            Gimp.PDBProcType.PLUGIN, 
                                            self.run_iti, None)
        procedure.set_image_types("*")
        procedure.set_menu_label("Image-to-Image")
        procedure.add_menu_path('<Image>/Generate')
        procedure.set_documentation("ComfyUI ITI", 
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
        
        ## Main Settings ##
        # Denoise
        procedure.add_double_argument("denoise", "_Denoise", "Denoise", 0.0, 1.0, 1.0,
                                    GObject.ParamFlags.READWRITE)
        # Seed
        procedure.add_int_argument("seed", "_Seed", "Seed", -1, 2147483647, -1,
                                GObject.ParamFlags.READWRITE)
        # Workflow
        workflow_choice = Gimp.Choice.new()
        for idx, favorite in enumerate(favorites):
            workflow_choice.add(favorite["title"], idx, favorite["title"], favorite["title"])
        procedure.add_choice_argument("workflow", "_Workflow", 
                                    "Workflow", workflow_choice, favorites[0]["title"],
                                    GObject.ParamFlags.READWRITE)
        # Source Image
        source_image_choice = Gimp.Choice.new()
        source_image_choice.add("visible", 1, "Visible", "visible")
        source_image_choice.add("layer", 2, "Layer", "layer")
        procedure.add_choice_argument("source", "_Source", 
                                    "Source", source_image_choice, "visible",
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
                comfy_dir = create_comfy_dir()
                previous_inputs, previous_inputs_path = load_previous_inputs(comfy_dir)

                try:
                    main_dict, ksampler_dict = get_main_dialog(procedure, config, previous_inputs)
                    lora_dict = get_lora_dialog(procedure, config, main_dict["lora_selection"])
                except Exception as e:
                    return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

                Gimp.Image.undo_group_start(image)
                Gimp.context_push()

                try:
                    if main_dict["seed"] == -1:
                        main_dict["seed"] = random.randint(1, 4294967295)

                    # Prepare Inputs
                    workflow_path = get_workflow_path(main_dict["workflow"])
                    offsets = Gimp.Drawable.get_offsets(drawables[0])

                    Gimp.progress_set_text("Preparing inputs...")
                    try:
                        input_image_name = prepare_input("image", image, drawables[0], default_server_address, main_dict["source_image"], main_dict["export_format"], comfy_dir)
                        input_mask_name = prepare_input("mask", image, drawables[0], default_server_address, main_dict["source_image"], "PNG", comfy_dir)
                    except Exception as e:
                        Gimp.message(f"Error Preparing Inputs: {e}")
                        return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
                    
                    # Prepare Workflow
                    Gimp.progress_set_text("Preparing workflow...")
                    try:
                        workflow, text_inputs = prepare_workflow(workflow_path, main_dict, lora_dict, ksampler_dict, input_image_name, input_mask_name)
                    except Exception as e:
                        Gimp.message(f"Error Preparing Workflow: {e}")
                        return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

                    if text_inputs:
                        update_json_file(text_inputs, previous_inputs_path)

                    # Write Workflow
                    workflow_json_path = os.path.join(comfy_dir, generated_workflow_file_name)
                    write_to_json_file(workflow, workflow_json_path)

                    # Prepare Outputs
                    outputs = generate(workflow, image, default_server_address, comfy_dir)

                    # Insert Outputs
                    insert_outputs(outputs, image, default_server_address, main_dict["seed"], offsets, comfy_dir)
                except Exception as e:
                    Gimp.message(f"Error: {e}")
                    return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
                finally:
                    Gimp.context_pop()
                    Gimp.Image.undo_group_end(image)
                    Gimp.displays_flush()
                
        except Exception as e:
            Gimp.message(f"Error Main: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())


        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

Gimp.main(GimpITI.__gtype__, sys.argv)