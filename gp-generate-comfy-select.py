#!/usr/bin/env python

# ComfyUI functions with GIMP

from gimpfu import *
import websocket
import uuid
import json
import urllib2
import io
import base64

############################################################################################################
# ComfyUI functions
def set_workflow(workflow, base64_utf8_str, item, confidence, iou, height, width):
    for node in workflow.values():
        class_type = node.get("class_type").lower()
        inputs = node.get("inputs", {})

        # Find load image node
        if class_type == "nc_loadimagegimp":
            inputs["image"] = base64_utf8_str
            inputs["height"] = height
            inputs["width"] = width

        # Find yoloworld node
        if class_type == "yoloworld_esam_zho":
            inputs["confidence_threshold"] = confidence
            inputs["iou_threshold"] = iou
            inputs["categories"] = item

    return workflow

def byte_data_mask_to_selection(image, input_layer, received_data, select_init):
    """
    Converts byte data mask (black and white) to a selection in a GIMP image.
    Args:
        image (gimp.Image): The GIMP image to work on.
        input_layer (gimp.Layer): The layer to apply the mask to.
        received_data (str): Base64 encoded RGBA data for the mask.
        select_init (bool): Flag to determine if there was an initial selection.
    Notes:
        - If `select_init` is True, the initial selection is inverted and cleared.
        - The function attempts to convert the mask to a selection and remove the input layer.
    """
    if received_data == "":
        gimp.message("No data received. \nIdentical image may have been cached.")
        return
    else:
        rgba_data = base64.b64decode(received_data)
        pixel_region = get_layer_region(input_layer)
        try:
            pixel_region[:,:] = rgba_data
        except:
            gimp.message("Size mismatch. \nConsider using 'Send Image with Dimensions GIMP' node.")
            return
        # Convert Mask to layer, layer to selection
        if select_init:
            pdb.gimp_selection_invert(image)
            pdb.gimp_drawable_edit_clear(input_layer)
        pdb.gimp_selection_none(image)
        pdb.gimp_image_select_color(image, 0, input_layer, gimpcolor.RGB(255, 255, 255))
        pdb.gimp_image_remove_layer(image, input_layer)
        if pdb.gimp_selection_is_empty(image):
            if select_init:
                pdb.gimp_message("No items detected.\nTry adjusting confidence or IOU.")
            else:
                gimp.message("No items detected.\nTry adjusting confidence, IOU, or adding a selection region.")
            return
    return

def get_encoded_region(pixel_region):
    pixChars = pixel_region[:,:]
    return base64.b64encode(pixChars)

def get_layer_region(input_layer):
    input_layer.add_alpha()
    pixel_region = input_layer.get_pixel_rgn(0, 0, input_layer.width, input_layer.height)
    return pixel_region

def get_visible_region(image):
    new_layer = pdb.gimp_layer_new_from_visible(image,image, "Visible")
    new_layer.add_alpha()
    pixel_region = new_layer.get_pixel_rgn(0, 0, new_layer.width, new_layer.height)
    return pixel_region, new_layer.width, new_layer.height

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

def insert_visible_layer_with_alpha(image, name="Visible"):
    """
    Args:
        image (gimp.Image): The image to which the new layer will be added.
    Returns:
        gimp.Layer: The new from visible layer with an alpha channel.
    """
    new_layer = pdb.gimp_layer_new_from_visible(image,image, name)
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
                                        #### MAIN FUNCTION ####
############################################################################################################
def image_to_select(workflow_path, item, confidence, iou, image) :

    # Define the server and client
    server_address = "127.0.0.1:8188"
    client_id = str(uuid.uuid4())

    # Create one layer from all visible layers
    visible_layer = insert_visible_layer_with_alpha(image, "Convert to Selection")
    
    # If no selection, select entire image
    select_init = False
    if pdb.gimp_selection_is_empty(image):
        pdb.gimp_selection_all(image)
    else:
        select_init = True
        # Resize layer to selection
        x0,y0 = pdb.gimp_drawable_offsets(visible_layer)
        non_empty, x1, y1, x2, y2 = pdb.gimp_selection_bounds(image)
        pdb.gimp_layer_resize(visible_layer,x2-x1,y2-y1,x0-x1,y0-y1)

    # Get pixel region
    pixel_region = get_layer_region(visible_layer)
    base64_utf8_str = get_encoded_region(pixel_region)

    # Load workflow from file
    with io.open(workflow_path, "r", encoding="utf-8") as f:
        workflow_data = f.read()
    workflow = json.loads(workflow_data)

    # Set workflow
    workflow = set_workflow(workflow, base64_utf8_str, item, confidence, iou, visible_layer.height, visible_layer.width)

    ######### Connect to ComfyUI #########
    ws = queue_to_comfy(workflow, server_address, client_id)

    # Wait for generated image (blocking)
    status, received_data, received_width, received_height = receive_image_from_comfy(ws)

    # Check if received data is an error
    if status != "success":
        gimp.message("Error:\n" + received_data)
        return
    
    # Check if received image dimensions are provided
    elif received_width == None or received_height == None:
        received_width = visible_layer.width
        received_height = visible_layer.height

    
    try:
        byte_data_mask_to_selection(image, visible_layer, received_data, select_init)
    except:
        gimp.message("Error: Selection failed. \nIdentical process may have been cached.")
        return

register(
    "python_fu_comfy_auto_select",        # Function Name
    "Auto segmentation with ComfyUI",     # Description
    "Auto segmentation with prompt",      # Help
    "Nicholas Chenevey",        # Author
    "Nicholas Chenevey",        # 
    "10/07/2024",               # Date Created
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