#!/usr/bin/env python

from gimpfu import *
import os
import requests
import json
import random
import uuid
import websocket

comfy_dir_name = "comfy"
# temp_file_name = "temp.jpg"
temp_file_name = "temp.png"
upload_image_name = "gimp1.jpg"
# upload_image_name = "gimp1.png"
# content_type = "image/jpeg"
content_type = "image/png"
# temp_png_name = "temp.jpg"
server_address = "127.0.0.1:7860"
workflow_path = "d:\\art\\sd\\comfy-workflows\\gimp\\test1\\gimp-test1-load-mask.json"

# def upload_image(image, drawable, str1):
#     pdb.gimp_progress_init("Waiting...", None)
#     gimp_dir = gimp.directory
#     comfy_dir = os.path.join(gimp_dir, comfy_dir_name)
#     if not os.path.exists(comfy_dir):
#         os.makedirs(comfy_dir)
#     temp_file = os.path.join(comfy_dir, temp_file_name)

#     gimp.message(str(drawable.offsets))
#     gimp.message(temp_file)
#     pdb.gimp_progress_set_text("Exporting...")
#     pdb.gimp_file_save(image, drawable, temp_file, temp_file)

#     url = "http://{0}/api/upload/image".format(address)
#     form_data_files = { "image": (upload_image_name, open(temp_file, "rb"), content_type) }
#     gimp.message(url)

#     pdb.gimp_progress_set_text("Uploading...")
#     r = requests.post(url, files=form_data_files)
#     gimp.message(str(r.json()))


def prepare_workflow(seed):
  with open(workflow_path, 'r') as file:
    workflow_data = file.read()
  workflow = json.loads(workflow_data)
  nodes = workflow.values()

  if seed:
    for node in nodes:
      inputs = node.get("inputs", {})
      if "seed" in inputs:
        inputs["seed"] = seed

  return workflow

def generate(workflow):
  client_id = str(uuid.uuid4())
  ws = websocket.WebSocket()
  pdb.gimp_progress_set_text("Generating...")
  ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id))
  payload = {"prompt": workflow, "client_id": client_id}
  data = json.dumps(payload).encode('utf-8')
  



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

  workflow = prepare_workflow(seed)


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
