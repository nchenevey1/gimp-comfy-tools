#!/usr/bin/env python

# ComfyUI functions with GIMP

from gimpfu import *
import websocket
import uuid
import json
import urllib2
import io
import base64
import os
from collections import namedtuple

############################################################################################################
# ComfyUI functions
def queue_prompt(prompt):
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req =  urllib2.Request("http://{}/prompt".format(server_address), data=data)
    return json.loads(urllib2.urlopen(req).read())

def set_workflow(workflow, base64_utf8_str, item, confidence, iou):
    for node in workflow:
            # Find comfyui-tooling load image node
            if workflow[node]["class_type"] == "ETN_LoadImageBase64":
                workflow[node]["inputs"]["image"] = str(base64_utf8_str)

            # Find yoloworld node
            if workflow[node]["class_type"] == "Yoloworld_ESAM_Zho":
                workflow[node]["inputs"]["confidence_threshold"] = confidence
                workflow[node]["inputs"]["iou_threshold"] = iou
                workflow[node]["inputs"]["categories"] = item

    return workflow

# Define the server and client
server_address = "127.0.0.1:8188"
client_id = str(uuid.uuid4())

############################################################################################################
#### MAIN FUNCTION ####
def image_to_select(workflow_path, item, confidence, iou, image, tempDirectory) :

    ###################################### pdb.gimp_image_select_item(image, operation, item)
    ######### IMAGE #########
    
    # Create a temporary png file to save the image
    new_layer = pdb.gimp_layer_new_from_visible(image,image, "Visible Layer")
    fileName = 'temp_pic_for_deletion.png'
    outputName = os.path.join(tempDirectory,fileName)
    pdb.gimp_file_save(image,new_layer,outputName,outputName,run_mode=1)

    # Convert png image to base64
    binary_fc = open(outputName, 'rb').read()
    base64_utf8_str = base64.b64encode(binary_fc).decode('utf-8')

    ######### WORKFLOW #########
    # Load workflow from file
    with io.open(workflow_path, "r", encoding="utf-8") as f:
        workflow_data = f.read()
    workflow = json.loads(workflow_data)

    # Set workflow
    workflow = set_workflow(workflow, base64_utf8_str, item, confidence, iou)

    # Connect to ComfyUI
    ws = websocket.WebSocket()
    ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id))
    queue_prompt(workflow)['prompt_id']

    # Wait for generated image (blocking)
    while True:
        png_binary = ws.recv()
        # Check if received message is large
        if len(png_binary) > 5000:
            #  Ignore first two 32 bit numbers
            png_binary = png_binary[8:]
            break

    # Try to overwrite temp image with generated data
    try:
        open(outputName, 'wb').write(png_binary)
    except OSError as e: # this would be "except OSError, e:" before Python 2.6
        if e.errno != errno.ENOENT: # errno.ENOENT = no such file or directory
            raise # re-raise exception if a different error occurred

    # Load generated image from temporary png
    generated_selection = pdb.gimp_file_load_layer(image, outputName)
    pdb.gimp_layer_set_name(generated_selection, str("Convert to Selection"))
    image.add_layer(generated_selection, 0)
    pdb.gimp_image_select_color(image, 0, generated_selection, gimpcolor.RGB(255, 255, 255))
    # pdb.gimp_image_select_item(image, 0, generated_selection)
    pdb.gimp_image_remove_layer(image, generated_selection)

    # Delete temporary png
    try:
        os.remove(outputName)
    except OSError as e: # this would be "except OSError, e:" before Python 2.6
        if e.errno != errno.ENOENT: # errno.ENOENT = no such file or directory
            raise # re-raise exception if a different error occurred

register(
    "python_fu_comfy_auto_select",                # Function Name
    "Auto segmentation with ComfyUI",     # Description
    "Auto segmentation with prompt",      # Help
    "Nicholas Chenevey",        # Author
    "Nicholas Chenevey",        # 
    "09/05/2024",               # Date Created
    "Auto select...",           # Menu label
    "",                         # Image types
    [
        (PF_FILE, "file", "Workflow",        None),

        (PF_STRING, "string", "Item",        ''),

        (PF_FLOAT, "float", "Confidence",    0),
        (PF_FLOAT, "float", "IOU",           0),

        (PF_IMAGE,  'image',  'Input image',                None),
        (PF_DIRNAME,    'directory',    'Temp Directory',   '.'),
    ],
    [],
    image_to_select, menu="<Image>/Comfy Tools")

main()