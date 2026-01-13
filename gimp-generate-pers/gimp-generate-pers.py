#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import traceback

# Dependencies
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.abspath(os.path.join(PLUGIN_DIR, '..', 'modules'))

if MODULES_DIR not in sys.path:
    sys.path.append(MODULES_DIR)

# Imports
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
from gi.repository import Gimp, GimpUi, GLib

import config
import gimp_utils as GimpUtils
import gimp_generate_dialog as GenerateDialog


class ComfyGenerationPlugin(Gimp.PlugIn):
    """
    Main entry point for the plugin
    Registers the GIMP procedure and initializes the UI dialog
    """

    # Plugin Configuration
    PROCEDURE_NAME = "nc-gimp-generate-pers"
    MENU_LABEL = "ComfyUI Studio"
    MENU_PATH = "<Image>/Generate Panel"
    DOC_SHORT = "Launch the ComfyUI Generation Studio"
    DOC_LONG = "Provides an interactive interface to configure and generate images via a ComfyUI instance."

    def do_query_procedures(self):
        return [self.PROCEDURE_NAME]

    def do_create_procedure(self, name):
        """Registers the procedure with GIMP's PDB"""
        procedure = Gimp.ImageProcedure.new(
            self, name,
            Gimp.PDBProcType.PLUGIN,
            self.run, None
        )

        # Metadata & Documentation
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.ALWAYS)
        procedure.set_image_types("*")
        procedure.set_menu_label(self.MENU_LABEL)
        procedure.set_documentation(self.DOC_SHORT, self.DOC_LONG, name)
        procedure.set_attribution("Nicholas Chenevey", "Nicholas Chenevey", "2026")
        procedure.add_menu_path(self.MENU_PATH)
        
        return procedure

    def run(self, procedure, run_mode, image, drawables, config_args, run_data):
        """
        Executes the plugin
        Loads dependencies, restores settings, and opens the main dialog
        """
        # Relies on a GUI, must run interactively
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error("ComfyUI Studio only supports Interactive mode.")
            )

        GimpUi.init(self.PROCEDURE_NAME)

        try:
            # Load persistent user settings
            previous_inputs = GimpUtils.load_json(config.settings.last_inputs_path)

            # Initialize and run the Dialog
            dialog = GenerateDialog.ComfyGeneratorDialog(
                procedure, 
                image, 
                config_args, 
                previous_inputs
            )
            dialog.run()
            dialog.destroy()

            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

        except Exception as e:
            # Log full trace to stderr (console)
            traceback.print_exc()
            Gimp.message(f"ComfyUI Studio crashed:\n{str(e)}")
            
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, 
                GLib.Error(str(e))
            )


if __name__ == "__main__":
    Gimp.main(ComfyGenerationPlugin.__gtype__, sys.argv)