#!/usr/bin/env python

# ComfyUI functions with GIMP

from gimpfu import *
import websocket
import uuid
import json
import urllib2
import io
import base64
from collections import namedtuple

############################################################################################################
# ComfyUI functions
def queue_prompt(prompt):
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req =  urllib2.Request("http://{}/prompt".format(server_address), data=data)
    return json.loads(urllib2.urlopen(req).read())

def set_workflow(workflow, base64_utf8_str, item, confidence, iou, height, width):
    for node in workflow:
            # Find load image node
            if workflow[node]["class_type"] == "NC_LoadImageGIMP":
                workflow[node]["inputs"]["image"] = base64_utf8_str
                workflow[node]["inputs"]["height"] = height
                workflow[node]["inputs"]["width"] = width

            # Find yoloworld node
            if workflow[node]["class_type"] == "Yoloworld_ESAM_Zho":
                workflow[node]["inputs"]["confidence_threshold"] = confidence
                workflow[node]["inputs"]["iou_threshold"] = iou
                workflow[node]["inputs"]["categories"] = item

    return workflow

# GIMP functions
def get_image_encoded(pixel_region):
    pixChars = pixel_region[:,:]
    base64_utf8_str = base64.b64encode(pixChars)
    return base64_utf8_str

def is_jsonable(x):
    try:
        json.loads(x)
        return True
    except (TypeError, OverflowError, ValueError):
        return False

# Define the server and client
server_address = "127.0.0.1:8188"
client_id = str(uuid.uuid4())

############################################################################################################
#### MAIN FUNCTION ####
def image_to_select(workflow_path, item, confidence, iou, image) :

    if workflow_path.isspace() or item.isspace():
        gimp.message("Please fill in all fields.")
        return

    # Create one layer from all visible layers
    new_layer = pdb.gimp_layer_new_from_visible(image,image, "Visible Layer")
    pixel_region = new_layer.get_pixel_rgn(0, 0, new_layer.width, new_layer.height)
    
    # Get base64 encoded image
    base64_utf8_str = get_image_encoded(pixel_region)

    # Load workflow from file
    with io.open(workflow_path, "r", encoding="utf-8") as f:
        workflow_data = f.read()
    workflow = json.loads(workflow_data)

    # Set workflow
    workflow = set_workflow(workflow, base64_utf8_str, item, confidence, iou, new_layer.height, new_layer.width)

    # Connect to ComfyUI
    ws = websocket.WebSocket()
    ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id))
    queue_prompt(workflow)['prompt_id']

    # Wait for generated image (blocking)
    byte_data = ""
    while True:
        data_receive = ws.recv()

        # Check if received message is JSON
        if is_jsonable(data_receive):
            message_json = json.loads(data_receive)
            if message_json["type"] == "execution_success":
                break
            if "exception_message" in message_json["data"]:
                if message_json["data"]["exception_message"][:35] == "cannot reshape tensor of 0 elements":
                    gimp.message("No items detected.")
                    return
                else:
                    gimp.message("Error: " + message_json["data"]["exception_message"])
                return
            
        # Check if received message is large
        if len(data_receive) > 10000:
            #  Ignore first 4 values
            byte_data = data_receive[4:]


    if byte_data == "":
        gimp.message("No data received. \nIdentical query may have been cached.")
    else:
        rgba_data = base64.b64decode(byte_data)
        pixel_region[:,:] = rgba_data

    # Convert Mask to layer, layer to selection
    pdb.gimp_layer_set_name(new_layer, str("Convert to Selection"))
    pdb.gimp_image_insert_layer(image, new_layer, None, 0)
    pdb.gimp_image_select_color(image, 0, new_layer, gimpcolor.RGB(255, 255, 255))
    pdb.gimp_image_remove_layer(image, new_layer)


register(
    "python_fu_comfy_auto_select",                # Function Name
    "Auto segmentation with ComfyUI",     # Description
    "Auto segmentation with prompt",      # Help
    "Nicholas Chenevey",        # Author
    "Nicholas Chenevey",        # 
    "09/10/2024",               # Date Created
    "Auto select...",           # Menu label
    "",                         # Image types
    [
        (PF_FILE, "file", "Workflow",        None),

        (PF_STRING, "string", "Item",        ''),

        (PF_FLOAT, "float", "Confidence",    0.1),
        (PF_FLOAT, "float", "IOU",           0.1),

        (PF_IMAGE,  'image',  'Input image',                None),
    ],
    [],
    image_to_select, menu="<Image>/Comfy Tools")

main()