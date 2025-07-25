#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys

# GIMP imports
import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
from gi.repository import GLib

# Python imports
import uuid
import requests
import websocket

# ****************************************
#           User defaults
# ****************************************

default_server_address = "127.0.0.1:8188"

timeout_duration = 60  # Timeout duration in seconds

def open_websocket(server_address, client_id):
    try:
        ws = websocket.WebSocket()
        ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id), timeout=timeout_duration)
    except Exception as e:
        Gimp.message("Error Websocket: " + str(e))
        return []
    return ws

def interrupt_queue(server_address):
    try:
        client_id = str(uuid.uuid4())
        ws = open_websocket(server_address, client_id)
        url = "http://{0}/interrupt".format(server_address)
        r = requests.post(url)
        ws.close()
    except Exception as e:
        Gimp.message("Error Posting: " + str(e))

# ***********************************************
#           GIMP Plugin
# ***********************************************
class GimpCancel (Gimp.PlugIn):
    def do_query_procedures(self):
        return [ "nc-gimpcancel" ]
    
    def do_set_i18n (self, name):
        return False
    
    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name, 
                                            Gimp.PDBProcType.PLUGIN, 
                                            self.run_cancel, None)
        procedure.set_sensitivity_mask (Gimp.ProcedureSensitivityMask.ALWAYS)

        procedure.set_menu_label("Cancel Generation")
        procedure.add_menu_path('<Image>/Generate')
        procedure.set_documentation("ComfyUI Cancel", 
                                    "Cancel an image with ComfyUI", 
                                    name)
        procedure.set_attribution("Nicholas Chenevey", 
                                "Nicholas Chenevey", 
                                "2025")
        return procedure
    
    def run_cancel(self, procedure, run_mode, image, drawables, config, run_data):
        try:
            interrupt_queue(default_server_address)
        except Exception as e:
            Gimp.message(f"Error Main: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())


        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

Gimp.main(GimpCancel.__gtype__, sys.argv)