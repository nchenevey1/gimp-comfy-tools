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

comfy_dir_name = "comfy"
# temp_file_name = "temp.jpg"
temp_file_name = "temp.png"
temp_preview_file_name = "temp.jpg"
upload_image_name = "gimp1.jpg"
# upload_image_name = "gimp1.png"
# content_type = "image/jpeg"
content_type = "image/png"
# temp_png_name = "temp.jpg"
server_address = "127.0.0.1:7860"
workflow_path = "d:\\art\\sd\\comfy-workflows\\gimp\\test1\\gimp-test1-maskleft.json"

def upload_image(image, drawable, str1):
    pdb.gimp_progress_init("Waiting...", None)
    gimp_dir = gimp.directory
    comfy_dir = os.path.join(gimp_dir, comfy_dir_name)
    if not os.path.exists(comfy_dir):
        os.makedirs(comfy_dir)
    temp_file = os.path.join(comfy_dir, temp_file_name)

    gimp.message(str(drawable.offsets))
    gimp.message(temp_file)
    pdb.gimp_progress_set_text("Exporting...")
    pdb.gimp_file_save(image, drawable, temp_file, temp_file)

    url = "http://{0}/api/upload/image".format(address)
    form_data_files = { "image": (upload_image_name, open(temp_file, "rb"), content_type) }
    gimp.message(url)

    pdb.gimp_progress_set_text("Uploading...")
    r = requests.post(url, files=form_data_files)
    gimp.message(str(r.json()))

def prepare_input_image(image, drawable):
  gimp_dir = gimp.directory
  comfy_dir = os.path.join(gimp_dir, comfy_dir_name)
  temp_file_path = os.path.join(comfy_dir, "temp.jpg")
  pdb.gimp_progress_set_text("Exporting...")
  pdb.gimp_file_save(image, drawable, temp_file_path, temp_file_path)
  url = "http://{0}/api/upload/image".format(server_address)
  upload_image_name = "gimp_image.jpg"
  form_data_files = { "image": (upload_image_name, open(temp_file_path, "rb"), content_type) }
  pdb.gimp_progress_set_text("Uploading...")
  r = requests.post(url, files=form_data_files)
  input_image_name = r.json()["name"]
  return input_image_name

def prepare_input_mask(image):
  gimp_dir = gimp.directory
  comfy_dir = os.path.join(gimp_dir, comfy_dir_name)
  temp_file_path = os.path.join(comfy_dir, "temp.png")
  pdb.gimp_progress_set_text("Exporting...")
  pdb.gimp_file_save(image, image.selection, temp_file_path, temp_file_path)
  url = "http://{0}/api/upload/image".format(server_address)
  upload_image_name = "gimp_mask.png"
  form_data_files = { "image": (upload_image_name, open(temp_file_path, "rb"), content_type) }
  pdb.gimp_progress_set_text("Uploading...")
  r = requests.post(url, files=form_data_files)
  input_mask_name = r.json()["name"]
  return input_mask_name

def prepare_workflow(seed, image, drawable):
  with open(workflow_path, 'r') as file:
    workflow_data = file.read()
  workflow = json.loads(workflow_data)
  nodes = workflow.values()

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
    input_image_name = prepare_input_image(image, drawable)
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
      input_mask_name = prepare_input_mask(image)
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
    temp_file_path = os.path.join(comfy_dir, temp_preview_file_name)
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

def generate(workflow, image):
  client_id = str(uuid.uuid4())
  ws = websocket.WebSocket()
  pdb.gimp_progress_set_text("Generating...")
  ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id))
  payload = {"prompt": workflow, "client_id": client_id}
  url = "http://{0}/api/prompt".format(server_address)
  r = requests.post(url, json=payload)

  preview_layer = None
  output = {}

  while True:
    data_receive = ws.recv()

    if is_jsonable(data_receive):
      message_json = json.loads(data_receive)
      # gimp.message(str(message_json))
      if message_json["type"] == "executed":
        if "output" in message_json["data"]:
          if "images" in message_json["data"]["output"]:
            output = message_json["data"]["output"]["images"][0]
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

  return output

def insert_output(output, image, seed):
  if not "filename" in output:
    return
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

# def test1(image, drawable, str1):
#     pdb.gimp_progress_init("Waiting...", None)
#     gimp_dir = gimp.directory
#     comfy_dir = os.path.join(gimp_dir, comfy_dir_name)
#     if not os.path.exists(comfy_dir):
#         os.makedirs(comfy_dir)
#     temp_file = os.path.join(comfy_dir, temp_file_name)

#     image_mask = image.selection

#     pdb.gimp_file_save(image, image_mask, temp_file, temp_file)
#     gimp.message(temp_file)

def test1(image, drawable, seed):
  pdb.gimp_progress_init("Waiting...", None)

  gimp_dir = gimp.directory
  comfy_dir = os.path.join(gimp_dir, comfy_dir_name)
  if not os.path.exists(comfy_dir):
    os.makedirs(comfy_dir)

  if seed:
    if seed == -1:
      seed = random.randint(1, 4294967295)

  workflow = prepare_workflow(seed, image, drawable)
  output = generate(workflow, image)
  insert_output(output, image, seed)


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
    (PF_INT, "seed", "seed", -1),
  ],
  [],
  test1, menu="<Image>/Test1",
)

main()
