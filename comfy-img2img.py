#!/usr/bin/env python

from gimpfu import *
import os
import requests
import json
import random
import uuid
import websocket
from io import BytesIO
import shutil
import hashlib

# ****************************************
#           User defaults
# ****************************************

default_server_address = "127.0.0.1:7860"

favourites = [
  {
    "path": "d:\\art\\sd\\comfy-workflows\\gimp\\favourites\\gimp-flux-fill.json",
    "title": "FLux Fill",
  },
  {
    "path": "d:\\art\\sd\\comfy-workflows\\gimp\\favourites\\gimp-flux-dev.json",
    "title": "FLux Dev",
  },
]

select_all_if_empty = True

# ****************************************

comfy_dir_name = "comfy"
last_inputs_file_name = "last_inputs.json"

def enum(*sequential, **named):
  enums = dict(zip(sequential, range(len(sequential))), **named)
  return type('Enum', (), enums)
  
Repeat = enum("IfNotChanged", "Yes", "No")
areas = ["drawable", "image"]
exts = ["jpg", "png"]

def prepare_input(type, image, drawable, server_address, area, repeat, ext):
  gimp_dir = gimp.directory
  comfy_dir = os.path.join(gimp_dir, comfy_dir_name)
  temp_file_name = "temp.{0}".format(ext)
  temp_file_path = os.path.join(comfy_dir, temp_file_name)
  last_inputs_file = os.path.join(comfy_dir, last_inputs_file_name)
  last_inputs_data = {}
  comfy_name = None
  if os.path.exists(last_inputs_file):
    with open(last_inputs_file, "r") as file:
      last_inputs_data = json.load(file)
    if last_inputs_data.get(type):
      comfy_name = last_inputs_data[type]["comfy_name"]
  if repeat == Repeat.Yes:
    if comfy_name:
      return comfy_name
  layer = drawable
  if type == "mask":
    mask_layer = None
    if select_all_if_empty and pdb.gimp_selection_is_empty(image):
      mask_layer = pdb.gimp_layer_new_from_drawable(image.selection, image)
      pdb.gimp_drawable_fill(mask_layer, 2)
    if area == "drawable":
      width = pdb.gimp_drawable_width(drawable)
      height = pdb.gimp_drawable_height(drawable)
      offx, offy = pdb.gimp_drawable_offsets(drawable)
      if (
        width != image.width or
        height != image.height or
        offx != 0 or
        offy != 0
      ):
        mask_layer = mask_layer or pdb.gimp_layer_new_from_drawable(image.selection, image)
        layer = pdb.gimp_layer_new(image, width, height, mask_layer.type, "mask", 100, mask_layer.mode)
        selection_region = mask_layer.get_pixel_rgn(offx, offy, width, height)
        layer_region = layer.get_pixel_rgn(0, 0, width, height)
        layer_region[ : , : ] = selection_region[ : , : ]
      else:
        layer = mask_layer or image.selection
    else:
      layer = mask_layer or image.selection
  else:
    if area == "image":
      layer = pdb.gimp_layer_new_from_visible(image, image, "Visible")
  pixel_region = layer.get_pixel_rgn(0, 0, layer.width, layer.height)
  pixel_data = pixel_region[:, :]
  hash = hashlib.sha256(pixel_data).hexdigest()
  if repeat == Repeat.IfNotChanged:
    if comfy_name:
      last_ext = last_inputs_data[type]["ext"]
      last_hash = last_inputs_data[type]["hash"]
      if ext == last_ext and hash == last_hash:
        return comfy_name
  pdb.gimp_progress_set_text("Exporting...")
  pdb.gimp_file_save(image, layer, temp_file_path, temp_file_path)
  # shutil.copy(temp_file_path, os.path.join(comfy_dir, "mask.png"))
  project_path = pdb.gimp_image_get_filename(image) or ""
  project_name = os.path.splitext(os.path.basename(project_path))[0]
  current_number = 1
  if last_inputs_data.get(type):
    last_project_name = last_inputs_data[type]["project_name"]
    last_number = last_inputs_data[type]["number"]
    if last_project_name == project_name and last_number:
      current_number = last_number + 1
  url = "http://{0}/api/upload/image".format(server_address)
  number_str = "{0:05d}".format(current_number)
  upload_name = "gimp_{0}_{1}_{2}.{3}".format(project_name, type, number_str, ext)
  content_type = "image/jpeg"
  if ext == "png":
    content_type = "image/png"
  form_data_files = { "image": (upload_name, open(temp_file_path, "rb"), content_type) }
  pdb.gimp_progress_set_text("Uploading...")
  r = requests.post(url, files=form_data_files)
  comfy_name = r.json()["name"]
  last_inputs_data[type] = {
    "project_name": project_name,
    "number": current_number,
    "hash": hash,
    "comfy_name": comfy_name,
    "ext": ext,
  }
  with open(last_inputs_file, "w") as f:
    json.dump(last_inputs_data, f)
  return comfy_name

def prepare_input_image(image, drawable, server_address, area, repeat, ext):
  return prepare_input("image", image, drawable, server_address, area, repeat, ext)

def prepare_input_mask(image, drawable, server_address, area, repeat):
  # black and white png files are actually smaller than jpgs
  return prepare_input("mask", image, drawable, server_address, area, repeat, "png")

def prepare_workflow(image, drawable, server_address, workflow_path, positive, negative, denoise, seed, area, repeat, ext):
  with open(workflow_path, "r") as file:
    workflow_data = file.read()
  workflow = json.loads(workflow_data)
  nodes = workflow.values()

  if positive:
    for node in nodes:
      inputs = node.get("inputs", {})
      meta = node.get("_meta", {})
      title = meta.get("title", "").lower()
      if "text" in inputs and "pos" in title:
        inputs["text"] = positive

  if negative:
    for node in nodes:
      inputs = node.get("inputs", {})
      meta = node.get("_meta", {})
      title = meta.get("title", "").lower()
      if "text" in inputs and "neg" in title:
        inputs["text"] = negative

  if denoise:
    for node in nodes:
      inputs = node.get("inputs", {})
      if "denoise" in inputs:
        inputs["denoise"] = denoise

  if seed:
    for node in nodes:
      inputs = node.get("inputs", {})
      if "seed" in inputs:
        inputs["seed"] = seed

  load_image_node = None
  load_image_key = None

  for key, node in workflow.iteritems():
    if node.get("class_type") == "LoadImage":
      load_image_node = node
      load_image_key = key
      break
  
  if load_image_node:
    input_image_name = prepare_input_image(image, drawable, server_address, area, repeat, ext)
    inputs = load_image_node.get("inputs", {})
    inputs["image"] = input_image_name
    linked_mask_nodes = []
    for node in nodes:
      inputs = node.get("inputs", {})
      if (
          "mask" in inputs and
          inputs["mask"][0] == load_image_key and
          inputs["mask"][1] == 1
        ):
        linked_mask_nodes.append(node)

    if len(linked_mask_nodes):
      input_mask_name = prepare_input_mask(image, drawable, server_address, area, repeat)
      last_key_number = max(map(int, workflow.keys()))
      load_mask_key = str(last_key_number + 1)
      workflow[load_mask_key] = {
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
        linked_mask_node["inputs"]["mask"] = [
          load_mask_key,
          0
        ]

  return workflow

def is_jsonable(x):
  try:
    json.loads(x)
    return True
  except (TypeError, OverflowError, ValueError):
    return False

def insert_preview_layer(image, preview_data, prev_layer):
  preview_layer = prev_layer
  message_handler = pdb.gimp_message_get_handler()
  gimp_dir = gimp.directory
  comfy_dir = os.path.join(gimp_dir, comfy_dir_name)
  pdb.gimp_message_set_handler(CONSOLE) # Warning: Premature end of JPEG file

  try:
    temp_file_path = os.path.join(comfy_dir, "temp.jpg")
    jfif = BytesIO(preview_data)

    with open(temp_file_path, "wb") as temp_file:
      # gimp.message(temp_file_path)
      temp_file.write(jfif.read())
      preview_layer = pdb.gimp_file_load_layer(image, temp_file_path, run_mode=RUN_NONINTERACTIVE)

    if prev_layer:
      pdb.gimp_item_set_name(prev_layer, "prev")
    pdb.gimp_item_set_name(preview_layer, "preview")
    pdb.gimp_image_insert_layer(image, preview_layer, None, 0)
    if prev_layer:
      pdb.gimp_image_remove_layer(image, prev_layer)

    pdb.gimp_progress_set_text("Generating...")
    gimp.displays_flush()
  except Exception as e:
      print(e)

  pdb.gimp_message_set_handler(message_handler)
  return preview_layer

def generate(workflow, image, server_address):
  client_id = str(uuid.uuid4())
  ws = websocket.WebSocket()
  pdb.gimp_progress_set_text("Generating...")
  ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id))
  payload = {"prompt": workflow, "client_id": client_id}
  url = "http://{0}/api/prompt".format(server_address)
  r = requests.post(url, json=payload)

  preview_layer = None
  outputs = []

  while True:
    data_receive = ws.recv()

    if is_jsonable(data_receive):
      message_json = json.loads(data_receive)
      # gimp.message(str(message_json))
      if message_json["type"] == "executed":
        if "output" in message_json["data"]:
          if "images" in message_json["data"]["output"]:
            outputs = message_json["data"]["output"]["images"]
      elif message_json["type"] == "execution_success":
        break
      elif "exception_message" in message_json["data"]:
        error_message = ("Error: " + message_json["data"]["exception_message"])
        gimp.message("Error:\n" + error_message)
        break
      elif message_json["type"] == "progress":
        step = message_json["data"]["value"]
        max_steps = message_json["data"]["max"]
        fraction = float(step) / max_steps
        # gimp.message(str(message_json["data"]) + str(step) + str(max_steps) + str(fraction))
        gimp.progress_update(fraction)
    else:
      int_value = (ord(data_receive[0]) << 24) + (ord(data_receive[1]) << 16) + (ord(data_receive[2]) << 8) + ord(data_receive[3])
      if int_value == 1:
        preview_data = data_receive[8:]
        preview_layer = insert_preview_layer(image, preview_data, preview_layer)
      else:
        gimp.message("Received data is not JSON or preview.\nReceived start value is {}".format(str(int_value)))

  if preview_layer:
    pdb.gimp_image_remove_layer(image, preview_layer)

  return outputs

def insert_outputs(outputs, image, server_address, seed, offsets):
  for output in outputs:
    if not "filename" in output:
      continue
    output_file_name = output["filename"]
    pdb.gimp_progress_set_text("Downloading...")
    pdb.gimp_progress_pulse()
    gimp_dir = gimp.directory
    comfy_dir = os.path.join(gimp_dir, comfy_dir_name)
    output_file_path = os.path.join(comfy_dir, output_file_name)
    url = "http://{0}/api/view".format(server_address)
    with requests.get(url, params=output, stream=True) as r:
      with open(output_file_path, 'wb') as f:
        shutil.copyfileobj(r.raw, f)

    ext = output_file_name.split(".")[-1]
    temp_file_name = "temp.{0}".format(ext)
    temp_file_path = os.path.join(comfy_dir, temp_file_name)
    shutil.move(output_file_path, temp_file_path)
    output_layer = pdb.gimp_file_load_layer(image, temp_file_path, run_mode=RUN_NONINTERACTIVE)
    pdb.gimp_item_set_name(output_layer, str(seed))
    pdb.gimp_image_insert_layer(image, output_layer, None, 0)
    if offsets:
      pdb.gimp_layer_set_offsets(output_layer, *offsets)

def test1(image, drawable, server_address, workflow_path, favourite_index, positive, negative, denoise, seed, areaIndex, repeat, extIndex):
  pdb.gimp_progress_init("Waiting...", None)
  initial_layer = pdb.gimp_image_get_active_layer(image)
  pdb.gimp_image_undo_group_start(image)
  pdb.gimp_context_push()

  gimp_dir = gimp.directory
  comfy_dir = os.path.join(gimp_dir, comfy_dir_name)
  if not os.path.exists(comfy_dir):
    os.makedirs(comfy_dir)

  if not workflow_path:
    workflow_path = favourites[favourite_index]["path"]

  if seed:
    if seed == -1:
      seed = random.randint(1, 4294967295)
  area = areas[ areaIndex ]
  ext = exts[ extIndex ]
  offsets = []
  if area == "drawable":
    offsets = pdb.gimp_drawable_offsets(drawable)

  workflow = prepare_workflow(image, drawable, server_address, workflow_path, positive, negative, denoise, seed, area, repeat, ext)
  outputs = generate(workflow, image, server_address)
  insert_outputs(outputs, image, server_address, seed, offsets)

  pdb.gimp_context_pop()
  pdb.gimp_image_undo_group_end(image)
  pdb.gimp_image_set_active_layer(image, initial_layer)
  pdb.gimp_displays_flush()

register(
  "test1",        # Function Name
  "test1",        # Description
  "test1",        # Help
  "morozig",      # Author
  "morozig",      # 
  "12/01/2025",   # Date Created
  "Test1",        # Menu label
  "",             # Image types
  [
    (PF_IMAGE, "image", "Input image", None),
    (PF_DRAWABLE, "drawable", "Active Layer", None),
    (PF_STRING, "server_address", "Address", default_server_address),
    (PF_FILE, "workflow_path", "Workflow", None),
    (PF_OPTION, "favourite_index", "Favourite", 0,
      map(lambda x: x["title"], favourites)
    ),
    (PF_TEXT, "positive", "Positive", ""),
    (PF_TEXT, "negative", "Negative", ""),
    (PF_FLOAT, "denoise", "Denoise", 0.0),
    (PF_INT, "seed", "Seed", -1),
    (PF_OPTION, "areaIndex", "Area", 0, [
      "Active layer",
      "Visible image"
    ]),
    (PF_OPTION, "repeat", "Repeat", Repeat.IfNotChanged, [
      "If not changed",
      "Always",
      "Never",
    ]),
    (PF_OPTION, "extIndex", "Export as", 0, [ "jpg (faster)", "png" ]),
  ],
  [],
  test1, menu="<Image>/Test1",
)

main()
