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

def set_workflow(workflow, base64_utf8_str_mask, base64_utf8_str, ckpt_name, posprompt, negprompt, seed, steps, sampler, scheduler, denoise, Lora_list, lora_dict):
    for node in workflow:
            # Find default checkpoint node
            if workflow[node]["class_type"] == "CheckPointLoaderSimple":
                workflow[node]["inputs"]["ckpt_name"] = ckpt_name

            # Find default LoraLoader node
            # if workflow[node]["class_type"] == "LoraLoader":
            #     workflow[node]["inputs"]["lora_name"] = Lora_list.pop(0)
            #     workflow[node]["inputs"]["strength_model"] = lora_dict[workflow[node]["inputs"]["lora_name"]][0]
            #     workflow[node]["inputs"]["strength_clip"] = lora_dict[workflow[node]["inputs"]["lora_name"]][1]
            
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

            # Find comfyui-tooling load image node
            if workflow[node]["class_type"] == "ETN_LoadImageBase64":
                workflow[node]["inputs"]["image"] = str(base64_utf8_str)
            # Find comfyui-tooling load mask node
            if workflow[node]["class_type"] == "ETN_LoadMaskBase64":
                workflow[node]["inputs"]["mask"] = str(base64_utf8_str_mask)

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
def image_to_image(workflow_path, checkpoint, posprompt, negprompt, seed, steps, sampler, scheduler, denoise, lora1, strength1, lora2, strength2, lora3, strength3, lora4, strength4, image, tempDirectory) :

    # Set to random seed if seed is 0
    rand_seed = random.randint(1, 1000000000)
    if seed == 0:
        seed = rand_seed

    ######### IMAGE #########
    # Create one layer from all visible layers
    new_layer = pdb.gimp_layer_new_from_visible(image,image, str(seed))
    
    # Create a temporary png file to save the image
    fileName = 'temp_pic_for_deletion.png'
    outputName = os.path.join(tempDirectory,fileName)
    pdb.gimp_file_save(image,new_layer,outputName,outputName,run_mode=1)
    
    # Convert png image to base64
    binary_fc = open(outputName, 'rb').read()
    base64_utf8_str = base64.b64encode(binary_fc).decode('utf-8')

    ######### MASK #########
    # Get mask from selection
    image_mask = image.selection

    # If no selection, fill mask with white
    if pdb.gimp_selection_is_empty(image):
        pdb.gimp_drawable_fill(image_mask, 2)

    # Create new temporary mask layer
    mask_layer = pdb.gimp_layer_new_from_drawable(image_mask, image)

    # Modify the temporary png file to save the mask
    pdb.gimp_file_save(image,mask_layer,outputName,outputName,run_mode=1)

    # Convert mask to base64
    binary_mask = open(outputName, 'rb').read()
    base64_utf8_str_mask = base64.b64encode(binary_mask).decode('utf-8')

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
    workflow = set_workflow(workflow, base64_utf8_str_mask, base64_utf8_str, ckpt_name, posprompt, negprompt, seed, steps, sampler, scheduler, denoise, Lora_list, lora_dict)

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
    generated_layer = pdb.gimp_file_load_layer(image, outputName)
    pdb.gimp_layer_set_name(generated_layer, str(seed))
    image.add_layer(generated_layer, 0)
  
    # Delete temporary png
    try:
        os.remove(outputName)
    except OSError as e: # this would be "except OSError, e:" before Python 2.6
        if e.errno != errno.ENOENT: # errno.ENOENT = no such file or directory
            raise # re-raise exception if a different error occurred

register(
    "python_fu_comfy_image_to_image",             # Function Name
    "Image to image generation with ComfyUI",     # Description
    "Image to image generation with prompt",      # Help
    "Nicholas Chenevey",        # Author
    "Nicholas Chenevey",        # 
    "09/04/2024",               # Date Created
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
        (PF_DIRNAME,    'directory',    'Temp Directory',   '.'),
    ],
    [],
    image_to_image, menu="<Image>/Comfy Tools")

main()
