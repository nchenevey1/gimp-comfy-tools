# GIMP Plugins with ComfyUI

GIMP plugins that communicate with ComfyUI.

* <a href="#plugins">GIMP Plugins Basic Instructions</a>
* <a href="#websocket">GIMP and Websocket
* <a href="#info">General Information</a>

## <a id="plugins" href="#toc">GIMP Plugins Basic Instructions</a>
* Go to Edit>Preferences
* Click the + sign next to Folders
* Click Plug-ins
* Add the directory containing the plugin .py files

## <a id="websocket" href="#toc">GIMP and Websocket</a>
* I got get-pip.py from https://bootstrap.pypa.io/pip/2.7/get-pip.py

* Add get-pip.py to GIMP folder: C:\Program Files\GIMP 2\bin 

* From a Windows Command Prompt Window cd to the GIMP Python folder (type cmd into the file explorer address bar):  
`cd C:\Program Files\GIMP-2\bin`

* Run the get-pip.py script using the GIMP version of Python:  
`.\python.exe get-pip.py`

* You now have pip installed in the GIMP version of Python

* Now you can run the command to download and install:  
`.\python.exe -m pip install websocket-client`

## <a id="info" href="#toc">General Information</a>
* Must have https://github.com/Acly/comfyui-tooling-nodes for sending and receiving websocket png data

* Uses a temporary png file saved in specified directory
This is because the comfyui-tooling-nodes "Load Mask (Base64)", "Load Image (Base64)", and "Send Image (WebSocket)"
all use Base64 encoded binary data from PNG

* Currently uses specific nodes
(Default EmptyLatentImage node, CheckPointLoderSimple node, CLIPTextEncode node, and KSampler node)

* Searches for prompt text nodes by searching CLIPTextEncode nodes for 'pos' and 'neg' in title
(Positive prompt node must have 'pos' somewhere in title, negative prompt node must have 'neg')

* Currently uses Lora Loader Stack (rgthree)

* Lora count limited by options in GIMP ui

* Image to image uses GIMP selection tool. Entire image is used if no selection is present

* Seed is random if set to 0

* Make sure to select the current GIMP image in the "input image" ui option when using image to image
(Saving pngs causes spam in image selection options)