# GIMP Plugins with ComfyUI

GIMP plugins that communicate with ComfyUI.

* <a href="#plugins">GIMP Plugins Basic Instructions</a>
* <a href="#websocket">GIMP and Websocket
* <a href="#YOLO">Yolo Instructions
* <a href="#info">General Information
* <a href="#demo">Demonstration</a>

## <a id="plugins" href="#toc">GIMP Plugins Basic Instructions</a>
* Go to Edit>Preferences
* Click the + sign next to Folders
* Click Plug-ins
* Add the directory containing the plugin .py files

## <a id="websocket" href="#toc">GIMP and Websocket</a>
* Pip is required:
  - I got get-pip.py from https://bootstrap.pypa.io/pip/2.7/get-pip.py

* Add get-pip.py to GIMP folder: C:\Program Files\GIMP 2\bin 

* From a Windows Command Prompt Window, cd to the GIMP Python folder (or just type cmd into the file explorer address bar):  
`cd C:\Program Files\GIMP-2\bin`

* Run the get-pip.py script using the GIMP version of Python:  
`.\python.exe get-pip.py`

* You now have pip installed in the GIMP version of Python

* Now you can run the command to download and install:  
`.\python.exe -m pip install websocket-client`

## <a id="YOLO" href="#toc">Yolo Instructions</a>
Download the models and follow the instructions outlined in this video:

https://www.youtube.com/watch?v=wEd1wPlCBaQ

Thank you to ControlAltAI

## <a id="info" href="#toc">General Information</a>
* ComfyUI must be running with all of the required nodes for the specified workflow installed

* Must have https://github.com/nchenevey1/comfyui-gimp-nodes for sending and receiving websocket RGBA data

* Currently uses specific nodes
  - (Default EmptyLatentImage node, CheckPointLoderSimple node, CLIPTextEncode node, and KSampler node)

* Searches for prompt text nodes by searching CLIPTextEncode nodes for 'pos' and 'neg' in title
  - (Positive prompt node must have 'pos' somewhere in title, negative prompt node must have 'neg')

* Currently uses Power Lora Loader (rgthree)

* Lora count limited by options in GIMP ui

* Image to image uses GIMP selection tool. Entire image is used if no selection is present

* Seed is random if set to 0

* Make sure to select the current GIMP image in the "input image" ui option when using image to image

## <a id="demo" href="#toc">Demonstration</a>

https://github.com/user-attachments/assets/1254844a-43f3-40df-9914-cb07b1fe0448


https://github.com/user-attachments/assets/42957904-34af-44ff-955b-3c17483737b6


https://github.com/user-attachments/assets/d235e270-8573-4b78-bfb2-46957608299b


https://github.com/user-attachments/assets/d7d0ac48-5587-482b-ae0e-2f1a79d082c4