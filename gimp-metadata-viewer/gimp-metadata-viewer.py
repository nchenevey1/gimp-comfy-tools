#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import json
from typing import Dict, Any

# Dependency Bootstrapping
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.abspath(os.path.join(PLUGIN_DIR, '..', 'modules'))

if MODULES_DIR not in sys.path:
    sys.path.append(MODULES_DIR)

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, GimpUi, GLib, Gtk

# -------------------------------------------------------------------
#                           UI Dialog
# -------------------------------------------------------------------

class MetadataDialog(GimpUi.Dialog):
    """
    Displays ComfyUI generation metadata
    """

    def __init__(self, layer_name: str, metadata: Dict[str, Any]):
        super().__init__(title=f"Metadata: {layer_name}")
        self.metadata = metadata
        
        # Window Setup
        self.set_default_size(500, 750)
        self.set_border_width(10)
        
        self._init_ui()
        self.add_button("_Close", Gtk.ResponseType.CLOSE)
        self.show_all()

    def _init_ui(self):
        content = self.get_content_area()
        content.set_spacing(15)

        # Scrolled container to handle long lists/prompts
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(400)
        scroller.set_propagate_natural_height(True)
        
        # Main Vertical Container
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_margin_top(10)
        vbox.set_margin_bottom(10)
        vbox.set_margin_start(15)
        vbox.set_margin_end(15)
        
        scroller.add(vbox)
        content.pack_start(scroller, True, True, 0)

        # Workflow
        wf_name = os.path.basename(self.metadata.get("active_workflow", "Unknown"))
        self._add_kv_row(vbox, "Workflow", wf_name)

        # Parameters Grid (Seed, Steps, etc.)
        self._add_parameter_grid(vbox)

        # Checkpoint
        ckpt = self.metadata.get("checkpoint_selection", "None")
        self._add_kv_row(vbox, "Checkpoint", ckpt)

        # LoRAs (Unshortened List)
        self._add_lora_list(vbox)

        # Positive Prompt
        self._add_prompt_box(vbox, "Positive Prompt", 
                             self.metadata.get("positive_generate_prompt", ""), 
                             "#2e8b57") # SeaGreen

        # Negative Prompt
        self._add_prompt_box(vbox, "Negative Prompt", 
                             self.metadata.get("negative_generate_prompt", ""), 
                             "#c0392b") # DarkRed

    # --- UI Helpers ---

    def _add_kv_row(self, container: Gtk.Box, label: str, value: str):
        """Adds a simple 'Label: Value' row."""
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        
        lbl_k = Gtk.Label(label=f"<b>{label}:</b>")
        lbl_k.set_use_markup(True)
        lbl_k.set_halign(Gtk.Align.START)
        lbl_k.set_width_chars(12) # Align labels nicely
        lbl_k.set_xalign(0)

        lbl_v = Gtk.Label(label=str(value))
        lbl_v.set_selectable(True)
        lbl_v.set_halign(Gtk.Align.START)
        lbl_v.set_line_wrap(True)
        lbl_v.set_max_width_chars(50)
        
        hbox.pack_start(lbl_k, False, False, 0)
        hbox.pack_start(lbl_v, True, True, 0)
        container.pack_start(hbox, False, False, 0)

    def _add_parameter_grid(self, container: Gtk.Box):
        """Creates a compact grid for numeric parameters"""
        grid = Gtk.Grid()
        grid.set_column_spacing(20)
        grid.set_row_spacing(5)
        
        # Helper to add grid items
        def add_item(row, col, label, key):
            val = str(self.metadata.get(key, "-"))
            l = Gtk.Label(label=f"<b>{label}:</b> {val}")
            l.set_use_markup(True)
            l.set_halign(Gtk.Align.START)
            l.set_selectable(True)
            grid.attach(l, col, row, 1, 1)

        # Row 1
        add_item(0, 0, "Seed", "seed")
        add_item(0, 1, "Steps", "steps")
        
        # Row 2
        add_item(1, 0, "CFG", "cfg")
        add_item(1, 1, "Denoise", "denoise_strength")

        # Row 3
        add_item(2, 0, "Sampler", "sampler")
        add_item(2, 1, "Scheduler", "scheduler")

        container.pack_start(grid, False, False, 5)

    def _add_lora_list(self, container: Gtk.Box):
        """Displays LoRAs as a list of full filenames"""
        loras = self.metadata.get("loras", [])
        
        # Label
        lbl = Gtk.Label(label="<b>LoRAs:</b>")
        lbl.set_use_markup(True)
        lbl.set_halign(Gtk.Align.START)
        container.pack_start(lbl, False, False, 0)

        if not loras:
            none_lbl = Gtk.Label(label="None")
            none_lbl.set_halign(Gtk.Align.START)
            none_lbl.set_margin_start(15)
            none_lbl.get_style_context().add_class("dim-label")
            container.pack_start(none_lbl, False, False, 0)
            return

        # Handle both list-of-dicts and dict-of-strengths formats
        items = []
        if isinstance(loras, dict):
            items = [{"file": k, "strength": v} for k, v in loras.items()]
        elif isinstance(loras, list):
            items = loras

        # List Display
        for item in items:
            fname = item.get("file", "Unknown")
            strength = item.get("strength", 1.0)
            
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
            row.set_margin_start(15) # Indent list
            
            # Bullet point
            bullet = Gtk.Label(label="•")
            
            # Text
            txt = Gtk.Label(label=f"{fname} ({strength})")
            txt.set_selectable(True)
            txt.set_line_wrap(True)
            txt.set_max_width_chars(55)
            txt.set_halign(Gtk.Align.START)

            row.pack_start(bullet, False, False, 0)
            row.pack_start(txt, True, True, 0)
            container.pack_start(row, False, False, 0)

    def _add_prompt_box(self, container: Gtk.Box, label: str, text: str, color: str):
        """Adds a colored label and a read-only text view for prompts"""
        # Colored Header
        lbl = Gtk.Label(label=f"<span foreground='{color}' weight='bold'>{label}:</span>")
        lbl.set_use_markup(True)
        lbl.set_halign(Gtk.Align.START)
        lbl.set_margin_top(5)
        
        # Text Area
        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text_view.set_left_margin(8)
        text_view.set_right_margin(8)
        text_view.set_top_margin(8)
        text_view.set_bottom_margin(8)
        text_view.get_buffer().set_text(text)
        
        # Inner Scroller
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(100)
        scroller.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        scroller.add(text_view)
        
        container.pack_start(lbl, False, False, 0)
        container.pack_start(scroller, False, False, 0)

# -------------------------------------------------------------------
#                           Main Plugin
# -------------------------------------------------------------------

class ComfyMetadataViewer(Gimp.PlugIn):
    """
    GIMP 3 Plugin entry point
    """
    PROCEDURE_NAME = "nc-show-comfy-metadata"
    PARASITE_KEY = "comfy-data-v1"

    def do_query_procedures(self):
        return [self.PROCEDURE_NAME]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name,
            Gimp.PDBProcType.PLUGIN,
            self.run, None
        )
        
        procedure.set_menu_label("View ComfyUI Metadata")
        procedure.set_documentation(
            "View generation data attached to layer",
            "Displays JSON metadata stored in the 'comfy-data-v1' parasite.",
            self.PROCEDURE_NAME
        )
        procedure.set_attribution("Nicholas Chenevey", "Nicholas Chenevey", "2026")
        procedure.add_menu_path('<Image>/Generate Panel')
        
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error("Metadata Viewer only runs in Interactive mode.")
            )

        GimpUi.init(self.PROCEDURE_NAME)
        
        if not drawables:
            Gimp.message("No layer selected.")
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())

        layer = drawables[0]
        parasite = layer.get_parasite(self.PARASITE_KEY)
        
        if not parasite:
            Gimp.message("No ComfyUI metadata found on this layer.")
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

        try:
            # Handle GIMP 3 API variations (Bytes vs List of Ints)
            data_raw = parasite.get_data()
            if isinstance(data_raw, list):
                data_raw = bytes(data_raw)
            
            json_str = data_raw.decode('utf-8')
            metadata = json.loads(json_str)
            
            dialog = MetadataDialog(layer.get_name(), metadata)
            dialog.run()
            dialog.destroy()
            
        except Exception as e:
            Gimp.message(f"Error reading metadata: {str(e)}")

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


if __name__ == "__main__":
    Gimp.main(ComfyMetadataViewer.__gtype__, sys.argv)