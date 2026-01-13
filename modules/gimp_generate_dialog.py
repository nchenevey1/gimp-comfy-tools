#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import threading
import uuid
import random
from typing import Dict, Any

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
gi.require_version('GimpUi', '3.0')
from gi.repository import GimpUi
from gi.repository import GLib, Gtk, Gio

# Local imports
from gimp_workflow_ui import WorkflowManager, WorkflowDialog
from gimp_ui_generate import (
    KSamplerWidget, ResourceGalleryWidget, LoraManagerWidget, 
    StyleBrowserWidget, PromptWidget
)
import config
import gimp_utils as GimpUtils
from comfy_client import ComfyClient

class ComfyGeneratorDialog(GimpUi.Dialog):
    """
    Main Interface for the ComfyUI GIMP Plugin
    Handles UI orchestration, state management, and the generation lifecycle
    """

    def __init__(self, procedure, image, config_args, previous_inputs):
        super().__init__(title="ComfyUI Studio", flags=0)
        
        # Core Dependencies
        self.procedure = procedure
        self.config_args = config_args
        self.active_image = image
        self.previous_inputs = previous_inputs
        self.client = ComfyClient(server_address=config.settings.default_server_address)
        self.workflow_manager = WorkflowManager()
        
        # State
        self.is_generating = False
        self.preview_layer = None
        self.current_settings = {} # Stores settings during generation for metadata
        self.selected_checkpoint = previous_inputs.get("checkpoint_selection", None)

        # UI Setup
        self.set_default_size(900, 950)
        self._init_layout()
        self.connect("destroy", self.on_close)
        
        # Initial Data Load
        self._populate_workflows()
        self._restore_selection_state()

    # -------------------------------------------------------------------------
    #                               UI INITIALIZATION
    # -------------------------------------------------------------------------

    def _init_layout(self):
        """Constructs the main two-pane layout"""
        content = self.get_content_area()

        if not self.client.is_reachable():
            info_bar = Gtk.InfoBar()
            info_bar.set_message_type(Gtk.MessageType.ERROR)
            
            box = info_bar.get_content_area()
            msg = f"<b>Connection Failed:</b> Could not reach ComfyUI at {self.client.server_address}.\nEnsure the server is running and try closing/reopening this dialog."
            label = Gtk.Label(label=msg)
            label.set_use_markup(True)
            label.set_xalign(0)
            
            box.add(label)
            info_bar.show_all()
        
            content.pack_start(info_bar, False, False, 0)
        
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(450)
        content.pack_start(paned, True, True, 0)

        # --- Left Pane (Configuration) ---
        left_scroll = Gtk.ScrolledWindow()
        left_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.left_box.set_margin_top(10)
        self.left_box.set_margin_start(50)
        self.left_box.set_margin_end(50)
        
        left_scroll.add(self.left_box)
        paned.pack1(left_scroll, True, False)

        self._build_target_image_selector()

        # --- Right Pane (Assets/Styles) ---
        self.right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.right_box.set_margin_top(10)
        self.right_box.set_margin_end(10)
        self.right_box.set_margin_start(5)
        
        self.style_browser = StyleBrowserWidget(self)
        self.right_box.pack_start(self.style_browser, True, True, 0)
        paned.pack2(self.right_box, True, False)

        # --- Components Construction ---
        self._build_workflow_selector()
        self._build_settings_stack()
        self._build_footer(content)
        self._build_action_area()

        self.show_all()

    def _build_target_image_selector(self):
        """Creates a dropdown to select the target GIMP image"""
        frame = Gtk.Frame(label="Target Image")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        box.set_margin_top(5)
        box.set_margin_bottom(5)
        box.set_margin_start(5)
        box.set_margin_end(5)

        # Dropdown
        self.image_combo = Gtk.ComboBoxText()
        self.image_combo.set_hexpand(True)
        self.image_combo.set_tooltip_text("Select the image to generate into")
        
        # Refresh Button
        btn_refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        btn_refresh.set_tooltip_text("Refresh list of open images")
        btn_refresh.connect("clicked", lambda b: self._refresh_image_list())

        box.pack_start(self.image_combo, True, True, 0)
        box.pack_start(btn_refresh, False, False, 0)
        frame.add(box)
        
        self.left_box.pack_start(frame, False, False, 0)
        
        # Populate initially
        self._refresh_image_list()

    def _refresh_image_list(self):
        """Populates the combo box with currently open GIMP images"""
        self.image_combo.remove_all()
        
        # Fetch current open images from GIMP
        images = Gimp.get_images()
        
        if not images:
            self.image_combo.append("none", "No Images Open")
            self.image_combo.set_active_id("none")
            self.active_image = None
            return

        # Populate Dropdown
        active_id = None
        
        target_img = self.active_image if (self.active_image and self.active_image.is_valid()) else None
        
        for img in images:
            # Create a unique ID string
            img_id = str(img.get_id())
            name = img.get_name()
            
            # Label format: "Filename (ID)"
            label = f"{name} ({img_id})"
            self.image_combo.append(img_id, label)
            
            if target_img and img.get_id() == target_img.get_id():
                active_id = img_id

        # Set Active Item
        if active_id:
            self.image_combo.set_active_id(active_id)
        else:
            # Fallback: Select the first one (usually most recently created)
            self.image_combo.set_active(0)
            
        self._on_image_selection_changed()
        
        if not self.image_combo.get_has_entry(): # Simple check to avoid double connection
             self.image_combo.connect("changed", lambda w: self._on_image_selection_changed())

    def _on_image_selection_changed(self):
        """Updates self.active_image based on dropdown selection"""
        selected_id_str = self.image_combo.get_active_id()
        if not selected_id_str or selected_id_str == "none":
            self.active_image = None
            return

        # Find the image object matching the ID
        try:
            target_id = int(selected_id_str)
            for img in Gimp.get_images():
                if img.get_id() == target_id:
                    self.active_image = img
                    return
        except ValueError:
            pass

    def _build_workflow_selector(self):
        """Creates the workflow dropdown and management button"""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        
        btn_manage = Gtk.Button(label="Workflows...")
        btn_manage.set_tooltip_text("Manage or Import JSON Workflows")
        btn_manage.connect("clicked", self.on_manage_workflows)
        
        self.wf_combo = Gtk.ComboBoxText()
        self.wf_combo.set_hexpand(True)
        
        box.pack_start(btn_manage, False, False, 0)
        box.pack_start(self.wf_combo, True, True, 0)
        self.left_box.pack_start(box, False, False, 0)

    def _build_settings_stack(self):
        """Constructs the expandable setting sections"""
        # KSampler
        self.ksampler = KSamplerWidget(self.previous_inputs)
        self._add_expander("Generation Settings", self.ksampler, expanded=True)

        # Checkpoints
        self.ckpt_gallery = ResourceGalleryWidget(
            "Checkpoints", Gtk.SelectionMode.SINGLE, self.client, self.on_ckpt_selected
        )
        self.ckpt_label = Gtk.Label(xalign=0)
        self.ckpt_label.get_style_context().add_class("dim-label")
        self._update_ckpt_label(self.selected_checkpoint)
        
        vbox_ckpt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        vbox_ckpt.pack_start(self.ckpt_gallery, True, True, 0)
        vbox_ckpt.pack_start(self.ckpt_label, False, False, 0)
        self._add_expander("Checkpoints", vbox_ckpt)

        # LoRAs
        self.lora_manager = LoraManagerWidget(self.previous_inputs, self.client)
        self._add_expander("LoRAs", self.lora_manager)

        # Save Style Button
        btn_save_style = Gtk.Button(label="Save Settings as Style")
        btn_save_style.connect("clicked", self.on_save_style)
        self.left_box.pack_start(btn_save_style, False, False, 10)

    def _add_expander(self, label, widget, expanded=False):
        exp = Gtk.Expander(label=label)
        exp.set_expanded(expanded)
        exp.add(widget)
        self.left_box.pack_start(exp, False, False, 0)

    def _build_footer(self, content_area):
        """Builds prompts and status bar"""
        footer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        footer_box.set_margin_start(10)
        footer_box.set_margin_end(10)
        footer_box.set_margin_bottom(10)

        self.prompts = PromptWidget(self.previous_inputs, self)
        footer_box.pack_start(self.prompts, False, False, 0)

        # Status Row
        self.status_label = Gtk.Label(label="Ready", xalign=0)
        self.progress_bar = Gtk.ProgressBar()
        
        footer_box.pack_start(self.status_label, False, False, 0)
        footer_box.pack_start(self.progress_bar, False, False, 0)
        
        content_area.pack_start(footer_box, False, False, 0)

    def _build_action_area(self):
        area = self.get_action_area()
        area.set_margin_top(10)
        area.set_margin_bottom(10)
        area.set_margin_end(10)

        self.btn_cancel = Gtk.Button(label="Cancel")
        self.btn_cancel.set_sensitive(False)
        self.btn_cancel.connect("clicked", self.on_cancel)
        area.pack_end(self.btn_cancel, False, False, 0)

        self.btn_generate = Gtk.Button(label="Generate")
        self.btn_generate.get_style_context().add_class("suggested-action")
        self.btn_generate.connect("clicked", self.on_generate)
        area.pack_end(self.btn_generate, False, False, 0)

    # -------------------------------------------------------------------------
    #                            STATE & SETTINGS
    # -------------------------------------------------------------------------

    def _restore_selection_state(self):
        """Restores complex selection states like the active checkpoint in the gallery"""
        if self.selected_checkpoint:
            GLib.timeout_add(500, lambda: self.ckpt_gallery.select_item_by_name(self.selected_checkpoint))

    def _gather_settings(self) -> Dict[str, Any]:
        """Collects current configuration from all widgets"""
        data = self.ksampler.get_settings()
        p_pos, p_neg = self.prompts.get_prompts()
        
        data.update({
            "positive_generate_prompt": p_pos,
            "negative_generate_prompt": p_neg,
            "checkpoint_selection": self.selected_checkpoint,
            "loras": self.lora_manager.get_loras(),
            "active_workflow": self.wf_combo.get_active_id()
        })

        if data["seed"] == -1:
             # placeholder
            pass 
            
        return data

    def _load_style(self, data: Dict[str, Any]):
        """Applies a style dictionary to the UI"""
        self.ksampler.set_settings(data)
        self.prompts.set_prompts(
            data.get("positive_generate_prompt", ""), 
            data.get("negative_generate_prompt", "")
        )
        
        if "checkpoint_selection" in data:
            self.selected_checkpoint = data["checkpoint_selection"]
            self._update_ckpt_label(self.selected_checkpoint)
            self.ckpt_gallery.select_item_by_name(self.selected_checkpoint)

        if "loras" in data:
            self.lora_manager.clear()
            saved = data["loras"]
            if isinstance(saved, dict):
                for f, s in saved.items(): self.lora_manager.add_lora(f, s)
            elif isinstance(saved, list):
                for item in saved: 
                    self.lora_manager.add_lora(item.get("file"), item.get("strength"))

    def _update_ckpt_label(self, filename):
        display = os.path.splitext(filename)[0] if filename else "None"
        self.ckpt_label.set_text(f"Active: {display}")

    # -------------------------------------------------------------------------
    #                            EVENT HANDLERS
    # -------------------------------------------------------------------------

    def on_ckpt_selected(self, icon_view):
        sel = icon_view.get_selected_items()
        if not sel: return
        model = icon_view.get_model()
        full_path = model.get_value(model.get_iter(sel[0]), 2)
        self.selected_checkpoint = os.path.basename(full_path)
        self._update_ckpt_label(self.selected_checkpoint)

    def on_manage_workflows(self, widget):
        """
        Opens the workflow manager
        Smartly handles re-selection if the current workflow is deleted
        """
        previous_id = self.wf_combo.get_active_id()
        
        dialog = WorkflowDialog(self, self.workflow_manager)
        
        while True:
            response = dialog.run()

            # File Chooser
            if response == Gtk.ResponseType.APPLY:
                dialog.run_file_chooser()
                continue
            
            # Select
            elif response == Gtk.ResponseType.OK:
                sel = dialog.get_selected_workflow()
                self._populate_workflows()
                if sel:
                    self.wf_combo.set_active_id(sel['path'])
                break
                
            # Closed/cancelled
            else:
                self._populate_workflows()
                # Check if previous selection is still valid
                if previous_id and self._workflow_exists(previous_id):
                    self.wf_combo.set_active_id(previous_id)
                elif self.wf_combo.get_model():
                     # Default to first if deleted
                    self.wf_combo.set_active(0)
                break
        
        dialog.destroy()

    def _workflow_exists(self, wf_id):
        model = self.wf_combo.get_model()
        for row in model:
            # row[0] is workflow name, wf_id is the entire path
            if row[0] == os.path.splitext(os.path.basename(wf_id))[0]: return True
        return False

    def _populate_workflows(self):
        self.wf_combo.remove_all()
        data = self.workflow_manager.load_workflows()
        for wf in data.get("workflows", []):
            self.wf_combo.append(wf['path'], wf['title'])
        
        # Select current if set, else first
        current = self.previous_inputs.get("active_workflow")
        if current and self._workflow_exists(current): 
            self.wf_combo.set_active_id(current)
        elif self.wf_combo.get_model():
             self.wf_combo.set_active(0)

    def on_save_style(self, widget):
        dialog = Gtk.MessageDialog(
            transient_for=self, flags=0, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL, text="Save Style"
        )
        dialog.format_secondary_text("Enter a name for this style preset:")
        
        entry = Gtk.Entry()
        entry.set_text("New Style")
        entry.set_activates_default(True)
        dialog.get_content_area().add(entry)
        dialog.show_all()

        if dialog.run() == Gtk.ResponseType.OK:
            name = entry.get_text().strip()
            if name:
                self._write_style_file(name, self._gather_settings())
        dialog.destroy()

    def _write_style_file(self, name, data):
        safe_name = GimpUtils.sanitize_filename(name) or "Untitled"
        filename = f"{safe_name}.json"
        path = os.path.join(config.settings.styles_dir, filename)
        
        # Collision avoidance
        if os.path.exists(path):
            path = os.path.join(config.settings.styles_dir, f"{safe_name}_{uuid.uuid4().hex[:4]}.json")

        if GimpUtils.save_json(data, path):
            self.style_browser.refresh()

    def on_close(self, widget):
        """Persist settings to disk on close"""
        GimpUtils.update_json(self._gather_settings(), config.settings.last_inputs_path)

    # -------------------------------------------------------------------------
    #                        GENERATION LOGIC
    # -------------------------------------------------------------------------

    def on_generate(self, widget):
        """
        Entry point for generation
        1. Validates state
        2. UI -> 'Generating' state
        3. Schedules the prep phase (Main Thread) to run after UI update
        """
        if self.is_generating: return

        settings = self._gather_settings()
        if not settings["active_workflow"]:
            Gimp.message("Please select a valid workflow.")
            return

        self.is_generating = True
        self._update_ui_state(generating=True)
        self.status_label.set_text("Initializing...")
        
        # Save prompts to history immediately
        self.prompts.save_history()
        
        # Store settings for metadata later
        self.current_settings = settings

        # Schedule next step to allow UI to redraw "Initializing"
        GLib.timeout_add(50, self._stage_1_main_thread_prep, settings)

    def _stage_1_main_thread_prep(self, settings):
        """
        Stage 1 (Main Thread):
        - Prepares GIMP resources
        - Safely handles image validation and 
        only saves input/mask if a valid image and selection exist
        """
        if not self.is_generating:
            return False

        try:
            # Image Validation
            has_image_ref = self.active_image is not None
            is_valid_image = has_image_ref and self.active_image.is_valid()

            if has_image_ref and not is_valid_image:
                Gimp.message("The selected image is no longer valid. Please refresh the image list.")
                self.is_generating = False
                self._update_ui_state(generating=False)
                self.status_label.set_text("Error: Invalid Image")
                return False

            # Prepare Local Paths
            local_paths = {
                "input_image": None,
                "mask_image": None
            }

            # Save Assets
            if is_valid_image and not Gimp.Selection.is_empty(self.active_image):
                self.status_label.set_text("Saving temporary assets...")
                
                # Save Main Image
                local_main = os.path.join(config.settings.temp_images_dir, "main_input.png")
                if GimpUtils.save_image_to_disk(self.active_image, local_main):
                    local_paths["input_image"] = local_main

                # Save Mask
                local_paths["mask_image"] = GimpUtils.create_mask_from_selection(self.active_image)

            # Offload to Worker Thread
            t = threading.Thread(
                target=self._stage_2_worker_thread,
                args=(settings, local_paths),
                daemon=True
            )
            t.start()

        except Exception as e:
            self._handle_error(f"GIMP Prep Error: {e}")

        return False  # Return False to stop the GLib timeout loop

    def _stage_2_worker_thread(self, settings, local_paths):
        """
        Stage 2 (Worker Thread):
        - Handles Network I/O (Uploads)
        - API calls (Workflow Prep)
        - Streaming
        - Prevents the UI from freezing
        """
        try:
            client_id = str(uuid.uuid4())
            
            # Handle Random Seed
            if int(settings["seed"]) == -1 or int(settings["seed"]) == 0:
                settings["seed"] = random.randint(1, 2**32)

            # Upload Images
            main_dict = self._upload_assets(local_paths)
            
            # Fill remaining main_dict params from settings
            main_dict.update({
                "positive_prompt": settings["positive_generate_prompt"],
                "negative_prompt": settings["negative_generate_prompt"],
                "seed": int(settings["seed"]),
                "denoise_strength": settings.get("denoise_strength", 1.0),
                "checkpoint_selection": settings["checkpoint_selection"],
                "image_width": int(settings.get("width", 512)),
                "image_height": int(settings.get("height", 512)),
            })

            # Prepare Workflow
            GLib.idle_add(self.status_label.set_text, "Preparing Workflow...")
            
            workflow, _ = self.client.prepare_workflow(
                settings["active_workflow"], 
                main_dict, 
                settings["loras"], 
                settings
            )
            
            # Debug: Save what we are sending
            GimpUtils.save_json(workflow, config.settings.temp_workflow_path)

            # Stream Execution
            GLib.idle_add(self.status_label.set_text, "Queued...")
            
            stream = self.client.stream_generation(
                workflow, client_id, timeout=config.settings.timeout_duration
            )

            for evt, data in stream:
                if not self.is_generating: break # User Cancelled

                if evt == "preview_bytes":
                    GLib.idle_add(self._update_preview_layer, data)
                elif evt == "progress":
                    GLib.idle_add(self._update_progress, data[0], data[1])
                elif evt == "finished_metadata":
                    GLib.idle_add(self.status_label.set_text, "Downloading Results...")
                    self._download_results(data)
                elif evt == "error":
                    GLib.idle_add(self._handle_error, str(data))
                    return

            GLib.idle_add(self._on_generation_finished)

        except Exception as e:
            GLib.idle_add(self._handle_error, f"Worker Error: {e}")

    def _upload_assets(self, local_paths) -> Dict[str, Any]:
        """Helper to upload local files to ComfyUI and return parameter dict"""
        main_dict = {
            "has_input_image": False, "input_image_name": "",
            "has_mask": False, "mask_name": ""
        }
        
        # Upload Main Image
        if local_paths["input_image"]:
            GLib.idle_add(self.status_label.set_text, "Uploading Image...")
            resp = self.client.upload_image(
                local_paths["input_image"], subfolder="gimp_uploads", overwrite=True
            )
            if resp:
                name = resp.get("name")
                if resp.get("subfolder"): name = f"{resp['subfolder']}/{name}"
                main_dict["input_image_name"] = name
                main_dict["has_input_image"] = True

        # Upload Mask
        if local_paths["mask_image"]:
            GLib.idle_add(self.status_label.set_text, "Uploading Mask...")
            resp = self.client.upload_image(
                local_paths["mask_image"], subfolder="gimp_uploads", overwrite=True
            )
            if resp:
                name = resp.get("name")
                if resp.get("subfolder"): name = f"{resp['subfolder']}/{name}"
                main_dict["mask_name"] = name
                main_dict["has_mask"] = True
                
        return main_dict

    def _download_results(self, outputs):
        """Downloads final images to temp folder, schedules GIMP insertion"""
        if not os.path.exists(config.settings.temp_images_dir):
            os.makedirs(config.settings.temp_images_dir, exist_ok=True)

        for idx, item in enumerate(outputs):
            fname = item.get("filename")
            ext = fname.split('.')[-1] if '.' in fname else "png"
            local_path = os.path.join(config.settings.temp_images_dir, f"final_output_{idx}.{ext}")
            
            success = self.client.download_image(
                fname, item.get("subfolder", ""), item.get("type", "output"), local_path
            )
            
            if success:
                GLib.idle_add(self._insert_result_into_gimp, local_path)

    # -------------------------------------------------------------------------
    #                    UI UPDATES (Main Thread)
    # -------------------------------------------------------------------------

    def _update_ui_state(self, generating):
        self.btn_generate.set_sensitive(not generating)
        self.btn_cancel.set_sensitive(generating)
        if not generating:
            self.progress_bar.set_fraction(0)

    def _update_progress(self, val, max_val):
        frac = val / max_val if max_val > 0 else 0
        self.progress_bar.set_fraction(frac)
        self.status_label.set_text(f"Processing: {val}/{max_val}")
        return False

    def _handle_error(self, msg):
        self.is_generating = False
        self._update_ui_state(False)
        self.status_label.set_text("Error")
        Gimp.message(msg)
        return False

    def _on_generation_finished(self):
        self.is_generating = False
        self._update_ui_state(False)
        self.status_label.set_text("Done")
        return False

    def _update_preview_layer(self, img_bytes):
        """Updates the transient preview layer in GIMP"""
        if not self.is_generating or not self.active_image or not self.active_image.is_valid():
            return False

        tmp_path = os.path.join(config.settings.temp_images_dir, "preview.png")
        try:
            self.active_image.undo_freeze()
            
            # Write raw bytes
            with open(tmp_path, "wb") as f: f.write(img_bytes)
            
            # Replace old preview
            if self.preview_layer and self.preview_layer.is_valid():
                self.active_image.remove_layer(self.preview_layer)
            
            self.preview_layer = GimpUtils.insert_image_layer(self.active_image, tmp_path, "Comfy Preview")
            Gimp.displays_flush()
            self.active_image.undo_thaw()
            
        except Exception as e:
            print(f"Preview Error: {e}")
            
        return False

    def _insert_result_into_gimp(self, path):
        """Finalizes the generation by adding the result as a layer with metadata"""
        
        if not self.active_image or not self.active_image.is_valid():
            # If original image closed, create new one
            try:
                g_file = Gio.File.new_for_path(path)
                self.active_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, g_file)
                self.active_image.undo_freeze()
                Gimp.Display.new(self.active_image)
                target = self.active_image.get_layers()[0]
                target.set_name("Comfy Result")
                self.active_image.undo_thaw()

            except Exception as e:
                Gimp.message(f"Error creating new image: {e}")
                return False
        else:
            # Clean up preview
            self.active_image.undo_freeze()
            if self.preview_layer and self.preview_layer.is_valid():
                self.active_image.remove_layer(self.preview_layer)
                self.preview_layer = None
            self.active_image.undo_thaw()
            target = GimpUtils.insert_image_layer(self.active_image, path, "Comfy Result")
            Gimp.displays_flush()

        # Attach Metadata
        self.active_image.undo_freeze()
        if target:
            self._attach_metadata(target)
        self.active_image.undo_thaw()
        
        return False

    def _attach_metadata(self, layer):
        """Attaches generation parameters to the layer as a parasite"""
        if not self.current_settings: return
        
        # Filter relevant keys
        keys = [
            "active_workflow", "positive_generate_prompt", "negative_generate_prompt", 
            "checkpoint_selection", "loras", "seed", 
            "denoise_strength", "steps", "cfg", "sampler", "scheduler"
        ]
        meta = {k: self.current_settings[k] for k in keys if k in self.current_settings}

        try:
            json_str = json.dumps(meta, indent=2)
            parasite = Gimp.Parasite.new("comfy-data-v1", 1, json_str.encode('utf-8'))
            layer.attach_parasite(parasite)
        except Exception as e:
            print(f"Failed to attach metadata: {e}")

    def on_cancel(self, widget):
        self.status_label.set_text("Cancelling...")
        self.is_generating = False
        
        # Launch interrupt in background
        threading.Thread(target=self.client.interrupt).start()
        
        # Clean up preview immediately
        if self.active_image and self.active_image.is_valid():
            if self.preview_layer and self.preview_layer.is_valid():
                self.active_image.undo_freeze()
                self.active_image.remove_layer(self.preview_layer)
                Gimp.displays_flush()
                self.active_image.undo_thaw()
        
        self.preview_layer = None