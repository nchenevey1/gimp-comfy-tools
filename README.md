# GIMP Plugins with ComfyUI

GIMP plugins that communicate with ComfyUI.
TODO: Tutorial on how to add websocket to GIMP 3, new videos to demonstrate the GIMP 3 plugins.

* <a href="#plugins">GIMP Plugins Basic Instructions</a>
* <a href="#info">General Information</a>
* <a href="#demo">Demonstration</a>
* <a href="#websocket2">Gimp 2: GIMP and Websocket</a>
* <a href="#YOLO2">Gimp 2: Yolo Instructions</a>
* <a href="#demo2">Gimp 2: Demonstration</a>

## <a id="plugins" href="#toc">GIMP Plugins Basic Instructions</a>
* Go to Edit>Preferences
* Click the + sign next to Folders
* Click Plug-ins
* Add the directory containing the plugin .py files

## <a id="info" href="#toc">General Information</a>
* ComfyUI must be running with all of the required nodes for the specified workflow installed

* Searches for prompt text nodes by searching CLIPTextEncode nodes for 'pos' and 'neg' in title
  - (Positive prompt node must have 'pos' somewhere in title, negative prompt node must have 'neg')

* Currently uses Power Lora Loader (rgthree)

* Image to image uses GIMP selection tool. Entire image is used if no selection is present

* Seed is random if set to -1

## <a id="demo" href="#toc">Demonstration</a>

https://github.com/user-attachments/assets/e7b488c6-6351-436f-8135-cea50003e778

## <a id="websocket2" href="#toc">Gimp 2: GIMP and Websocket</a>
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

## <a id="YOLO2" href="#toc">Gimp 2: Yolo Instructions</a>
Download the models and follow the instructions outlined in this video:

https://www.youtube.com/watch?v=wEd1wPlCBaQ

Thank you to ControlAltAI

## <a id="demo2" href="#toc">Gimp 2: Demonstration</a>

https://github.com/user-attachments/assets/1254844a-43f3-40df-9914-cb07b1fe0448


https://github.com/user-attachments/assets/42957904-34af-44ff-955b-3c17483737b6


https://github.com/user-attachments/assets/d235e270-8573-4b78-bfb2-46957608299b


https://github.com/user-attachments/assets/d7d0ac48-5587-482b-ae0e-2f1a79d082c4