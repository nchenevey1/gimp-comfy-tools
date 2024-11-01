#!/usr/bin/env python

# ComfyUI functions with GIMP

from gimpfu import *
import websocket
import uuid
import json
import urllib2
import io
import random
import base64
import os

############################################################################################################
# ComfyUI Workflow
def set_workflow(workflow, image_dict, ckpt_name, input_height, input_width, Lora_list, lora_dict, posprompt, negprompt, seed, steps, CFG, sampler, scheduler, denoise):
    for node in workflow.values():
        class_type = node.get("class_type").lower()
        inputs = node.get("inputs", {})
        meta = node.get("_meta", {})
        
        # Find default checkpoint node
        if class_type == "checkpointloadersimple":
            inputs["ckpt_name"] = ckpt_name
        
        # Find default CLIPTextEncode node
        if class_type == "cliptextencode":
            if 'pos' in meta.get("title", "").lower():
                inputs["text"] = posprompt
            if 'neg' in meta.get("title", "").lower():
                inputs["text"] = negprompt

        # Find EmptyLatentImage node
        if class_type == "emptylatentimage":
            inputs["width"] = input_width
            inputs["height"] = input_height

        # Find default KSampler node
        if class_type == "ksampler":
            inputs.update({"seed": seed,})
            if steps>0: inputs.update({"steps": steps})
            if CFG>0: inputs.update({"cfg": CFG})
            if sampler != len(SamplerOptions)-1: inputs.update({"sampler_name": SamplerOptions[sampler]})
            if scheduler != len(SchedulerOptions)-1: inputs.update({"scheduler": SchedulerOptions[scheduler]})
            if denoise>0: inputs.update({"denoise": denoise})

        elif class_type == "power lora loader (rgthree)":
            for input_key in inputs:
                if not Lora_list:
                    break
                if 'lora' in input_key:
                    lora_name = Lora_list.pop(0)
                    if lora_name:
                        inputs[input_key]['lora'] = lora_name
                        inputs[input_key]['strength'] = lora_dict[lora_name][0]
                        inputs[input_key]['on'] = True
                        
        # Find load image nodes
        if class_type == "nc_loadimagegimp":
            if '1' in meta.get("title", "").lower():
                inputs["image"] = image_dict["layer_1"]["b64"]
                inputs["height"] = image_dict["layer_1"]["height"]
                inputs["width"] = image_dict["layer_1"]["width"]
            if '2' in meta.get("title", "").lower():
                inputs["image"] = image_dict["layer_2"]["b64"]
                inputs["height"] = image_dict["layer_2"]["height"]
                inputs["width"] = image_dict["layer_2"]["width"]
            if '3' in meta.get("title", "").lower():
                inputs["image"] = image_dict["layer_3"]["b64"]
                inputs["height"] = image_dict["layer_3"]["height"]
                inputs["width"] = image_dict["layer_3"]["width"]
    return workflow

############################################################################################################
# Functions
def byte_data_to_image(byte_data, width_value, height_value, name="New Layer"):
    """
    Args:
        byte_data (str): The base64 encoded RGBA byte data of the image.
        width_value (int): The width of the image.
        height_value (int): The height of the image.

    Returns:
        tuple: A tuple containing the created GIMP image and the new layer, or (None, None) if an error occurs.
    """
    if byte_data == "":
        gimp.message("No data received. \nIdentical image may have been cached.")
        return None
    else:
        rgba_data = base64.b64decode(byte_data)
        image = pdb.gimp_image_new(width_value, height_value, 0)
        new_layer = insert_new_layer_with_alpha(image, width_value, height_value, name)
        pixel_region = new_layer.get_pixel_rgn(0, 0, new_layer.width, new_layer.height)
        try:
            pixel_region[:,:] = rgba_data
        except:
            gimp.message("Size mismatch. \nConsider using 'Send Image with Dimensions GIMP' node.")
            gimp.pdb.gimp_image_delete(image)
            return None, None
    return image, new_layer

def get_color_mask_region(mask_layer, color):
    mask_image = pdb.gimp_item_get_image(mask_layer)
    pdb.gimp_context_set_sample_threshold(0.5)
    pdb.gimp_image_select_color(mask_image, 0, mask_layer, color)
    mask_region = get_selection_mask_region(mask_image, False)
    pdb.gimp_selection_none(mask_image)
    return mask_region

def get_encoded_region(pixel_region):
    pixChars = pixel_region[:,:]
    return base64.b64encode(pixChars)

def get_layer_region(input_layer):
    input_layer.add_alpha()
    pixel_region = input_layer.get_pixel_rgn(0, 0, input_layer.width, input_layer.height)
    return pixel_region

def get_selection_mask_region(image, fill_white=True):
    image_mask = image.selection
    # If no selection, fill mask with white
    if pdb.gimp_selection_is_empty(image):
        if fill_white:
            pdb.gimp_drawable_fill(image_mask, 2)
    mask_layer = pdb.gimp_layer_new_from_drawable(image_mask, image)
    mask_layer.add_alpha()
    mask_region = mask_layer.get_pixel_rgn(0, 0, image.width, image.height)
    return mask_region

def handle_received_data(data_receive):
    """
    Handles the received data and processes it based on its type.

    Parameters:
    data_receive (str): The data received, which can be either a JSON string or binary data.

    Returns:
    tuple: A tuple containing:
        - str: The type of the processed data ("success", "error", or "image").
        - str: A message or the image data.
        - int or None: The width of the image if applicable, otherwise None.
        - int or None: The height of the image if applicable, otherwise None.
    """
    if is_jsonable(data_receive):
        message_json = json.loads(data_receive)
        if message_json["type"] == "execution_success":
            return "success", "Execution success received", None, None
        elif "exception_message" in message_json["data"]:
            error_message = ("Error: " + message_json["data"]["exception_message"])
            return "error", error_message, None, None
    else:
        int_value = (ord(data_receive[0]) << 24) + (ord(data_receive[1]) << 16) + (ord(data_receive[2]) << 8) + ord(data_receive[3])
        # Check if received message starts with 14 (image with dimensions) or 12 (just image)
        if int_value == 14:
            width_value = (ord(data_receive[4]) << 24) + (ord(data_receive[5]) << 16) + (ord(data_receive[6]) << 8) + ord(data_receive[7])
            height_value = (ord(data_receive[8]) << 24) + (ord(data_receive[9]) << 16) + (ord(data_receive[10]) << 8) + ord(data_receive[11])
            if width_value == 0 or height_value == 0:
                return "error", "Width or Height is 0", None, None
            image_data = data_receive[12:]
            return "image", image_data, width_value, height_value
        elif int_value == 12:
            image_data = data_receive[4:]
            return "image", image_data, None, None
        else:
            gimp.message("Received data is not JSON or expected image data.\nReceived start value is {}".format(str(int_value)))
    return None, "", None, None

def insert_new_layer_with_alpha(image, width, height, name="New Layer"):
    """
    Args:
        image (gimp.Image): The image to which the new layer will be added.
        width (int): The width of the new layer.
        height (int): The height of the new layer.

    Returns:
        gimp.Layer: The newly created layer with an alpha channel.
    """
    new_layer = pdb.gimp_layer_new(image, width, height, 0, name, 100, 28)
    new_layer.add_alpha()
    pdb.gimp_image_insert_layer(image, new_layer, None, 0)
    return new_layer

def is_jsonable(x):
    try:
        json.loads(x)
        return True
    except (TypeError, OverflowError, ValueError):
        return False

def queue_prompt(prompt, server_address, client_id):
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req = urllib2.Request("http://{}/prompt".format(server_address), data=data)
    return json.loads(urllib2.urlopen(req).read())

def queue_to_comfy(workflow, server_address, client_id):
    """
    Establishes a WebSocket connection to a server and queues a prompt.

    Args:
        workflow (str): The workflow to be queued.
        server_address (str): The address of the server to connect to.
        client_id (str): The client ID to use for the connection.

    Returns:
        websocket.WebSocket: The WebSocket connection object.
    """
    ws = websocket.WebSocket()
    ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id))
    queue_prompt(workflow, server_address, client_id)['prompt_id']
    return ws

def receive_image_from_comfy(ws):
    """
    This function continuously listens for data from the provided WebSocket
    connection until it successfully receives image data or encounters an error.

    Args:
        ws: The WebSocket connection object to receive data from.

    Returns:
        tuple: A tuple containing the status, received data, width, and height.
            - status (str): The status of the received data, which can be "success", "error", or "image".
            - received_data: The image data or message received from the WebSocket.
            - width_value (int): The width of the received image, or None.
            - height_value (int): The height of the received image, or None.
    """
    received_data, width_value, height_value = None, None, None
    while True:
        data_receive = ws.recv()
        status, temp_data, temp_width, temp_height = handle_received_data(data_receive)
        if status == "success":
            break
        elif status == "error":
            return status, temp_data, temp_width, temp_height
        elif status == "image":
            received_data, width_value, height_value = temp_data, temp_width, temp_height
    return status, received_data, width_value, height_value

############################################################################################################
# Create Sampler and Scheduler options
SamplerOptions = ["euler", "euler_cfg_pp", "euler_ancestral", "euler_ancestral_cfg_pp", "heun", "heunpp2", "dpm_2", "dpm_2_ancestral", "lsm", "dpm_fast", "dpm_adaptive",
                    "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_sde_gpu", "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_2m_sde_gpu", "dpmpp_3m_sde", "dpmpp_3m_sde_gpu", "ddpm", "lcm", "ipndm", 
                    "ipndm_v", "deis", "ddim", "uni_pc", "uni_pc_bh2", "None"]

SchedulerOptions = ["normal", "karras", "exponential", "sgm_uniform", "simple", "ddim_uniform", "beta", "None"]

############################################################################################################
                                        #### MAIN FUNCTION ####
############################################################################################################
def Face_Adapter(workflow_path, checkpoint, input_height, input_width, posprompt, negprompt, seed, steps, CFG, sampler, scheduler, denoise, lora1, strength1, lora2, strength2, lora3, strength3, lora4, strength4, L1, L2, L3) :

    # Define the server and client
    server_address = "127.0.0.1:8188"
    client_id = str(uuid.uuid4())

    # Use a random seed if the provided seed is 0 or empty
    if not seed:
        seed = random.randint(1, 1000000000) 

    ######### IMAGES #########
    image_dict = {"layer_1":   {"b64": get_encoded_region(get_layer_region(L1)), "height": L1.height, "width": L1.width}, 
                  "layer_2": {"b64": get_encoded_region(get_layer_region(L2)), "height": L2.height, "width": L2.width}, 
                  "layer_3":  {"b64": get_encoded_region(get_layer_region(L3)), "height": L3.height, "width": L3.width}}

    ######### WORKFLOW #########
    # Load workflow from file
    with io.open(workflow_path, "r", encoding="utf-8") as f:
        workflow_data = f.read()
    workflow = json.loads(workflow_data)

    # Set sampler, scheduler, checkpoint, IPA model, and CLIP model
    ckpt_name = os.path.basename(checkpoint)

    # Prepare Lora names and strengths
    lora_files = [lora1, lora2, lora3, lora4]
    lora_strengths = [strength1, strength2, strength3, strength4]

    Lora_list = [os.path.basename(lora) for lora in lora_files]
    lora_dict = {lora: [strength] for lora, strength in zip(Lora_list, lora_strengths)}

    # Set workflow
    workflow = set_workflow(workflow, image_dict, ckpt_name, input_height, input_width, Lora_list, lora_dict, posprompt, negprompt, seed, steps, CFG, sampler, scheduler, denoise)

    ######### Connect to ComfyUI #########
    ws = queue_to_comfy(workflow, server_address, client_id)

    # Wait for generated image (blocking)
    status, received_data, received_width, received_height = receive_image_from_comfy(ws)

    # Check if received data is an error (not success)
    if status != "success":
        gimp.message("Error:\n" + received_data)
        return
    elif received_data == "Execution success received":
        gimp.message("Execution success received, but no image data.")
        return
    # Check if received image dimensions are provided
    elif received_width == None or received_height == None:
        received_width = input_width
        received_height = input_height
    
    try:
        image, image_layer = byte_data_to_image(received_data, received_width, received_height, str(seed))
    except:
        gimp.message("Error: Image creation failed. \nIdentical image may have been cached.")
        return
    
    # Create a new image window
    gimp.Display(image)
    # Show the new image window
    gimp.displays_flush()

register(
    "python_fu_comfy_face_adapter",                                 # Function Name
    "Uses three faces to compose a new one",                        # Description
    "Input is three layers containing different photos of the same subject",      # Help
    "Nicholas Chenevey",                # Author
    "Nicholas Chenevey",                # 
    "10/09/2024",                       # Date Created
    "Face Adapter...",                  # Menu label
    "",                                 # Image types
    [
        (PF_FILE, "file", "Workflow",         None),
        (PF_FILE, "file", "Checkpoint",       None),

        (PF_INT, "int", "Input Height",            1024),
        (PF_INT, "int", "Input Width",             768),

        (PF_STRING, "string", "Positive Prompt",     ''),
        (PF_STRING, "string", "Negative Prompt",     ''),

        (PF_INT, "int", "Seed",                     0),
        (PF_INT, "int", "Steps",                    40),
        (PF_FLOAT, "float", "CFG",                  5.0),

        (PF_OPTION, "option_var", "Sampler", 24, SamplerOptions),
        (PF_OPTION, "option_var", "Scheduler", 5, SchedulerOptions),

        (PF_FLOAT, "float", "Denoise",              1.0),
        
        (PF_FILE, "file", "Lora1",       None),
        (PF_FLOAT, "float", "Strength1",             1.0),

        (PF_FILE, "file", "Lora2",       None),
        (PF_FLOAT, "float", "Strength2",             1.0),

        (PF_FILE, "file", "Lora3",       None),
        (PF_FLOAT, "float", "Strength3",             1.0),

        (PF_FILE, "file", "Lora4",       None),
        (PF_FLOAT, "float", "Strength4",             1.0),

        (PF_LAYER, 'layer', 'Input layer 1',       None),
        (PF_LAYER, 'layer', 'Input layer 2',     None),
        (PF_LAYER, 'layer', 'Input layer 3',      None)
    ],
    [],
    Face_Adapter, menu="<Image>/Comfy Tools")

main()