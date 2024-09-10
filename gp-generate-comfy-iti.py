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
from collections import namedtuple

############################################################################################################
# ComfyUI functions
def queue_prompt(prompt):
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req =  urllib2.Request("http://{}/prompt".format(server_address), data=data)
    return json.loads(urllib2.urlopen(req).read())

def set_workflow(workflow, base64_utf8_str_mask, base64_utf8_str, height, width, ckpt_name, posprompt, negprompt, seed, steps, sampler, scheduler, denoise, Lora_list, lora_dict):
    for node in workflow:
            # Find default checkpoint node
            if workflow[node]["class_type"] == "CheckPointLoaderSimple":
                workflow[node]["inputs"]["ckpt_name"] = ckpt_name
            
            # Find Lora Loader Stack (rgthree) node
            if workflow[node]["class_type"] == "Lora Loader Stack (rgthree)":
                for input_value in workflow[node]["inputs"]:
                    if Lora_list == []:
                            break
                    if 'lora' in input_value:
                        lora_name = Lora_list.pop(0)
                        if lora_name == '':
                            pass
                        else:
                            workflow[node]["inputs"][input_value] = lora_name
                            workflow[node]["inputs"][input_value.replace('lora', 'strength')] = lora_dict[workflow[node]["inputs"][input_value]][0]

            # Find default CLIPTextEncode node
            if workflow[node]["class_type"] == "CLIPTextEncode":
                if 'pos' in workflow[node]["_meta"]["title"].lower():
                    workflow[node]["inputs"]["text"] = posprompt
                if 'neg' in workflow[node]["_meta"]["title"].lower():
                    workflow[node]["inputs"]["text"] = negprompt

            # Find default KSampler node
            if workflow[node]["class_type"] == "KSampler":
                workflow[node]["inputs"]["seed"] = seed
                workflow[node]["inputs"]["steps"] = steps
                workflow[node]["inputs"]["sampler_name"] = sampler
                workflow[node]["inputs"]["scheduler"] = scheduler
                workflow[node]["inputs"]["denoise"] = denoise

            # Find load image node
            if workflow[node]["class_type"] == "NC_LoadImageGIMP":
                workflow[node]["inputs"]["image"] = base64_utf8_str
                workflow[node]["inputs"]["height"] = height
                workflow[node]["inputs"]["width"] = width
            # Find load mask node
            if workflow[node]["class_type"] == "NC_LoadMaskGIMP":
                workflow[node]["inputs"]["mask"] = base64_utf8_str_mask
                workflow[node]["inputs"]["height"] = height
                workflow[node]["inputs"]["width"] = width

    return workflow

############################################################################################################
# GIMP functions
def createOptions(name,pairs): # by Ofnuts on gimp-forum.net
    # namedtuple('FooType',['OPTION1',...,'OPTIONn','labels','labelTuples']
    optsclass=namedtuple(name+'Type',[symbol for symbol,label in pairs]+['labels','labelTuples'])
    # FooType(0,..,n-1,['Option 1',...,'Option N'],[('Option 1',0),...,('Option N',n-1)])
    opts=optsclass(*(
                    range(len(pairs))
                    +[[label for symbol,label in pairs]]
                    +[[(label,i) for i,(symbol,label) in enumerate(pairs)]]
                    ))
    return opts

def get_image_encoded(pixel_region):
    pixChars = pixel_region[:,:]
    base64_utf8_str = base64.b64encode(pixChars)
    return base64_utf8_str

def get_selection_mask_encoded(image, height, width):
    # Get mask from selection
    image_mask = image.selection

    # If no selection, fill mask with white
    if pdb.gimp_selection_is_empty(image):
        pdb.gimp_drawable_fill(image_mask, 2)

    # Create new temporary mask layer
    mask_layer = pdb.gimp_layer_new_from_drawable(image_mask, image)
    mask_layer.add_alpha()
    mask_region = mask_layer.get_pixel_rgn(0, 0, width, height)
    maskChars = mask_region[:,:]
    base64_utf8_str_mask = base64.b64encode(maskChars)
    return base64_utf8_str_mask

def is_jsonable(x):
    try:
        json.loads(x)
        return True
    except (TypeError, OverflowError, ValueError):
        return False

# Create Sampler and Scheduler options
SamplerOptions = createOptions("Sampler", [("euler","euler"), ("euler_cfg_pp","euler_cfg_pp"), ("euler_ancestral","euler_ancestral"), ("euler_ancestral_cfg_pp","euler_ancestral_cfg_pp"), 
         ("heun","heun"), ("heunpp2","heunpp2"), ("dpm_2","dpm_2"), ("dpm_2_ancestral","dpm_2_ancestral"), ("lsm","lsm"), ("dpm_fast","dpm_fast"), ("dpm_adaptive","dpm_adaptive"), 
         ("dpmpp_2s_ancestral","dpmpp_2s_ancestral"), ("dpmpp_sde","dpmpp_sde"), ("dpmpp_sde_gpu","dpmpp_sde_gpu"), ("dpmpp_2m","dpmpp_2m"), ("dpmpp_2m_sde","dpmpp_2m_sde"), 
         ("dpmpp_2m_sde_gpu","dpmpp_2m_sde_gpu"), ("dpmpp_3m_sde","dpmpp_3m_sde"), ("dpmpp_3m_sde_gpu","dpmpp_3m_sde_gpu"), ("ddpm","ddpm"), ("lcm","lcm"), ("ipndm","ipndm"), 
         ("ipndm_v","ipndm_v"), ("deis","deis"), ("ddim","ddim"), ("uni_pc","uni_pc"), ("uni_pc_bh2","uni_pc_bh2")])

SchedulerOptions = createOptions("Scheduler", [("normal", "normal"), ("karras", "karras"), ("exponential", "exponential"), ("sgm_uniform", "sgm_uniform"), ("simple", "simple"), 
                                               ("ddim_uniform", "ddim_uniform"), ("beta", "beta")])

# Define the server and client
server_address = "127.0.0.1:8188"
client_id = str(uuid.uuid4())

############################################################################################################
#### MAIN FUNCTION ####
def image_to_image(workflow_path, checkpoint, posprompt, negprompt, seed, steps, sampler, scheduler, denoise, lora1, strength1, lora2, strength2, lora3, strength3, lora4, strength4, image) :

    if workflow_path.isspace() or checkpoint.isspace() or steps.isspace() or sampler.isspace() or scheduler.isspace() or denoise.isspace():
        gimp.message("Please fill in all fields.")
        return

    # Set to random seed if seed is 0
    rand_seed = random.randint(1, 1000000000)
    if seed == 0 or seed.isspace():
        seed = rand_seed

    ######### IMAGE #########
    # Create one layer from all visible layers
    new_layer = pdb.gimp_layer_new_from_visible(image,image, str(seed))
    layer_height = new_layer.height
    layer_width = new_layer.width
    pixel_region = new_layer.get_pixel_rgn(0, 0, layer_width, layer_height)
    
    # Get base64 encoded image
    base64_utf8_str = get_image_encoded(pixel_region)

    # Get base64 encoded mask
    base64_utf8_str_mask = get_selection_mask_encoded(image, layer_height, layer_width)

    ######### WORKFLOW #########
    # Load workflow from file
    with io.open(workflow_path, "r", encoding="utf-8") as f:
        workflow_data = f.read()
    workflow = json.loads(workflow_data)

    # Set sampler, scheduler, checkpoint
    sampler = SamplerOptions.labelTuples[sampler][0]
    scheduler = SchedulerOptions.labelTuples[scheduler][0]
    ckpt_name = os.path.basename(checkpoint)

    # Get Lora names and strengths
    lora1 = os.path.basename(lora1)
    lora2 = os.path.basename(lora2)
    lora3 = os.path.basename(lora3)
    lora4 = os.path.basename(lora4)
    Lora_list = [lora1, lora2, lora3, lora4]
    # lora_dict = {lora1: [strength1, clip1], lora2: [strength2, clip2], lora3: [strength3, clip3], lora4: [strength4, clip4]}
    lora_dict = {lora1: [strength1], lora2: [strength2], lora3: [strength3], lora4: [strength4]}
    
    # Set workflow
    workflow = set_workflow(workflow, base64_utf8_str_mask, base64_utf8_str, layer_height, layer_width, ckpt_name, posprompt, negprompt, seed, steps, sampler, scheduler, denoise, Lora_list, lora_dict)

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

        # Check if received message is large
        if len(data_receive) > 10000:
            #  Ignore first 4 values
            byte_data = data_receive[4:]
    
    if byte_data == "":
        gimp.message("No data received. \nIdentical image may have been cached.")
    else:
        rgba_data = base64.b64decode(byte_data)
        pixel_region[:,:] = rgba_data
        pdb.gimp_image_insert_layer(image, new_layer, None, 0)
        gimp.displays_flush()

register(
    "python_fu_comfy_image_to_image",             # Function Name
    "Image to image generation with ComfyUI",     # Description
    "Image to image generation with prompt",      # Help
    "Nicholas Chenevey",        # Author
    "Nicholas Chenevey",        # 
    "09/10/2024",               # Date Created
    "Image-to-image...",        # Menu label
    "",                         # Image types
    [
        (PF_FILE, "file", "Workflow",       None),

        (PF_FILE, "file", "Checkpoint",       None),

        (PF_STRING, "string", "Positive Prompt",     ''),
        (PF_STRING, "string", "Negative Prompt",     ''),

        (PF_INT, "int", "Seed",                     0),
        (PF_INT, "int", "Steps",                    20),

        (PF_OPTION, "option_var", "Sampler", 14, SamplerOptions.labels, SamplerOptions.labels),
        (PF_OPTION, "option_var", "Scheduler", 1, SchedulerOptions.labels, SchedulerOptions.labels),

        (PF_FLOAT, "float", "Denoise",              1.0),

        (PF_FILE, "file", "Lora1",       None),
        (PF_FLOAT, "float", "Strength1",             1.0),

        (PF_FILE, "file", "Lora2",       None),
        (PF_FLOAT, "float", "Strength2",             1.0),

        (PF_FILE, "file", "Lora3",       None),
        (PF_FLOAT, "float", "Strength3",             1.0),

        (PF_FILE, "file", "Lora4",       None),
        (PF_FLOAT, "float", "Strength4",             1.0),

        (PF_IMAGE,  'image',  'Input image',        None),
    ],
    [],
    image_to_image, menu="<Image>/Comfy Tools")

main()