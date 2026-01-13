#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import threading
from time import time
import uuid
import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
gi.require_version('GimpUi', '3.0')
from gi.repository import GimpUi
from gi.repository import GLib, Gtk, GdkPixbuf

# Local imports
import random
import requests
import config
import comfy_utils_pers as ComfyUtils
import gimp_utils as GimpUtils

class ComfyGeneratorDialog(GimpUi.Dialog):
    def __init__(self, procedure, config_args, previous_inputs):
        super().__init__(title="ComfyUI Studio", flags=0)
        self.procedure = procedure
        self.set_default_size(900, 900)

        self.history_manager = HistoryManager()
        self.workflow_manager = WorkflowManager()
        
        # State
        self.is_generating = False
        self.preview_layer = None
        self.active_image = None
        self.previous_inputs = previous_inputs

        self.style_icon_size = 128
        self.style_item_width = 100
        
        # Setup UI
        self.setup_ui()

        self.connect("destroy", self.on_window_closed)
        
    def on_window_closed(self, widget):
        self.save_settings()

    def setup_ui(self):
        # Main Container Setup
        content_area = self.get_content_area()
        
        self.main_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.main_paned.set_position(350) # Approx 50/50 split
        self.main_paned.set_wide_handle(True)
        content_area.pack_start(self.main_paned, True, True, 0)

        # --- LEFT COLUMN SETUP (Settings) ---
        left_scrolled = Gtk.ScrolledWindow()
        left_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        left_scrolled.set_min_content_height(400) 
        
        self.left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.left_box.set_border_width(15)
        left_scrolled.add(self.left_box)
        self.main_paned.pack1(left_scrolled, True, False)

        # --- RIGHT COLUMN SETUP  ---
        right_scrolled = Gtk.ScrolledWindow()
        right_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        
        self.right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.right_box.set_border_width(15)
        right_scrolled.add(self.right_box)
        self.main_paned.pack2(right_scrolled, True, False)

        # ===============================================
        # LEFT COLUMN WIDGETS
        # ===============================================
        
        top_controls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        
        workflow_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        
        manage_workflows_btn = Gtk.Button(label="Manage Workflows")
        manage_workflows_btn.set_tooltip_text("Manage, add, or select workflow files.")
        manage_workflows_btn.connect("clicked", self.on_manage_workflows_clicked)
        
        self.workflow_combo = Gtk.ComboBoxText()

        workflow_hbox.pack_start(manage_workflows_btn, False, False, 0)
        workflow_hbox.pack_start(self.workflow_combo, False, False, 0)
        top_controls_box.pack_start(workflow_hbox, False, False, 5)
        
        self.populate_workflows_dropdown()
        self.workflow_combo.connect("changed", self.on_workflow_selected)
        
        saved_workflow = self.previous_inputs.get("active_workflow")
        if saved_workflow:
            self.set_active_workflow_by_path(saved_workflow)

        self.left_box.pack_start(top_controls_box, False, False, 10)

        # KSampler Settings
        settings_grid = Gtk.Grid()
        settings_grid.set_column_spacing(12)
        settings_grid.set_row_spacing(10)
        settings_grid.set_margin_top(10)
        settings_grid.set_margin_bottom(10)
        
        # STEPS
        saved_steps = self.previous_inputs.get("steps", 20)
        adj_steps = Gtk.Adjustment(value=saved_steps, lower=1, upper=100, step_increment=1, page_increment=10, page_size=0)
        self.steps_spin = Gtk.SpinButton(adjustment=adj_steps, climb_rate=1, digits=0)
        self.add_param_row(settings_grid, 0, "Steps", self.steps_spin)

        # CFG
        saved_cfg = self.previous_inputs.get("cfg", 8.0)
        adj_cfg = Gtk.Adjustment(value=saved_cfg, lower=1.0, upper=30.0, step_increment=0.5, page_increment=1, page_size=0)
        self.cfg_spin = Gtk.SpinButton(adjustment=adj_cfg, climb_rate=0.5, digits=1)
        self.add_param_row(settings_grid, 1, "CFG Scale", self.cfg_spin)

        # SAMPLER
        saved_sampler = self.previous_inputs.get("sampler", config.settings.SAMPLERS[0])
        self.sampler_combo = Gtk.ComboBoxText()
        for s in config.settings.SAMPLERS:
            self.sampler_combo.append_text(s)
        # Set active item
        if saved_sampler in config.settings.SAMPLERS:
            idx = config.settings.SAMPLERS.index(saved_sampler)
            self.sampler_combo.set_active(idx)
        else:
            self.sampler_combo.set_active(0)
        self.add_param_row(settings_grid, 2, "Sampler", self.sampler_combo)

        # SCHEDULER
        saved_scheduler = self.previous_inputs.get("scheduler", config.settings.SCHEDULERS[0])
        self.scheduler_combo = Gtk.ComboBoxText()
        for s in config.settings.SCHEDULERS:
            self.scheduler_combo.append_text(s)
        if saved_scheduler in config.settings.SCHEDULERS:
            idx = config.settings.SCHEDULERS.index(saved_scheduler)
            self.scheduler_combo.set_active(idx)
        else:
            self.scheduler_combo.set_active(0)
        self.add_param_row(settings_grid, 3, "Scheduler", self.scheduler_combo)

        # SEED
        saved_seed = self.previous_inputs.get("seed", -1)
        adj_seed = Gtk.Adjustment(value=saved_seed, lower=-1, upper=2**32, step_increment=1, page_increment=10, page_size=0)
        self.seed_spin = Gtk.SpinButton(adjustment=adj_seed, climb_rate=1, digits=0)
        self.add_param_row(settings_grid, 4, "Seed", self.seed_spin, "Set to -1 for random seed")

        # DIMENSIONS
        default_w, default_h = self.get_default_dimensions() 
        saved_w = self.previous_inputs.get("width", default_w)
        saved_h = self.previous_inputs.get("height", default_h)

        adj_w = Gtk.Adjustment(value=saved_w, lower=64, upper=8192, step_increment=64, page_increment=64, page_size=0)
        self.width_spin = Gtk.SpinButton(adjustment=adj_w, climb_rate=64, digits=0)
        self.add_param_row(settings_grid, 5, "Width", self.width_spin)

        adj_h = Gtk.Adjustment(value=saved_h, lower=64, upper=8192, step_increment=64, page_increment=64, page_size=0)
        self.height_spin = Gtk.SpinButton(adjustment=adj_h, climb_rate=64, digits=0)
        self.add_param_row(settings_grid, 6, "Height", self.height_spin)
        
        # KSampler Settings
        ksampler_widget = self.create_ksampler_section([settings_grid])
        self.add_expandable_section(self.left_box, "Generation Settings", ksampler_widget)

        # CHECKPOINTS
        self.selected_checkpoint = self.previous_inputs.get("checkpoint_selection", None)
        if self.selected_checkpoint:
            default_checkpoint_text = os.path.splitext(self.selected_checkpoint)[0]
        else:
            default_checkpoint_text = "None"

        ckpt_container, self.checkpoints_view = self.create_gallery_widget(
            "Checkpoints", 
            Gtk.SelectionMode.SINGLE
        )

        # Add the Expander
        self.add_expandable_section(self.left_box, "Checkpoints", ckpt_container)

        # This will be placed OUTSIDE the expander
        ckpt_status_label = Gtk.Label(label=f"Active: {default_checkpoint_text}")
        ckpt_status_label.set_halign(Gtk.Align.START)
        ckpt_status_label.set_xalign(0) # Ensure text starts at left
        ckpt_status_label.get_style_context().add_class("dim-label")

        # Connect the signal: When icon is clicked, update this external label
        self.checkpoints_view.connect("selection-changed", self.on_gallery_selection_changed, ckpt_status_label, "Checkpoints")
        label_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        label_box.set_margin_bottom(10)
        label_box.set_margin_start(5)
        label_box.pack_start(ckpt_status_label, True, True, 0)
        self.left_box.pack_start(label_box, False, False, 0)

        # LORAS
        self.active_loras = {} 

        # Create the Gallery
        lora_container, self.loras_view = self.create_gallery_widget(
            "Loras", 
            Gtk.SelectionMode.SINGLE
        )
        self.add_expandable_section(self.left_box, "Loras", lora_container)

        # Create the Container for the "Added" Loras
        self.active_loras_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.active_loras_box.set_margin_start(10)
        self.active_loras_box.set_margin_end(10)
        self.active_loras_box.set_margin_bottom(10)
        self.left_box.pack_start(self.active_loras_box, False, False, 0)

        self.loras_view.connect("selection-changed", self.on_lora_added_from_gallery)

        # Restore previous session Loras (if any)
        saved_loras = self.previous_inputs.get("loras", {})
        for filename, strength in saved_loras.items():
            self.add_lora_row(filename, strength)

        # Initialize Data
        try:
            self.initialize_icon_view_from_config("Checkpoints")
            if self.selected_checkpoint:
                self.select_icon_by_filename(self.checkpoints_view, self.selected_checkpoint)

            self.initialize_icon_view_from_config("Loras")
        except Exception as e:
            Gimp.message(f"Error initializing views: {e}")

        style_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        style_btn_box.set_margin_top(10)
        
        save_style_btn = Gtk.Button(label="Save as Style")
        save_style_btn.set_tooltip_text("Save current settings as a reusable style")
        save_style_btn.connect("clicked", self.on_save_style_clicked)
        
        # Make it wide
        save_style_btn.set_hexpand(True)
        
        style_btn_box.pack_start(save_style_btn, True, True, 0)
        self.left_box.pack_start(style_btn_box, False, False, 0)


        # --- RIGHT PANE: STYLES ---
        # Top Header (Label + Add Icon Button)
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        
        lbl = Gtk.Label(label="<b>Saved Styles</b>", use_markup=True)
        lbl.set_halign(Gtk.Align.START)
        
        # The "Add Icon" button
        add_icon_btn = Gtk.Button()
        # Use a standard 'image-x-generic' or 'list-add' icon
        icon_img = Gtk.Image.new_from_icon_name("image-x-generic", Gtk.IconSize.BUTTON)
        add_icon_btn.set_image(icon_img)
        add_icon_btn.set_tooltip_text("Set an icon for the selected style")
        add_icon_btn.connect("clicked", self.on_add_style_icon_clicked)
        
        # Pack header: Label on left, Button on right
        header_box.pack_start(lbl, True, True, 0) # Label expands to push button right
        header_box.pack_start(add_icon_btn, False, False, 0)
        
        self.right_box.pack_start(header_box, False, False, 0)

        # The Gallery (Scrolled Window)
        self.styles_store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str) 
        
        self.styles_view = Gtk.IconView.new_with_model(self.styles_store)
        self.styles_view.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.styles_view.set_pixbuf_column(0)
        self.styles_view.set_text_column(1)
        self.styles_view.set_item_width(self.style_item_width)
        self.styles_view.connect("item-activated", self.on_style_activated)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(200)
        scroller.set_vexpand(True) 
        scroller.add(self.styles_view)
        
        self.right_box.pack_start(scroller, True, True, 0)

        # 3. Bottom Footer (Delete Button)
        delete_btn = Gtk.Button(label="Delete Style")
        delete_btn.set_tooltip_text("Permanently remove the selected style")
        delete_btn.get_style_context().add_class("destructive-action")
        delete_btn.connect("clicked", self.on_delete_style_clicked)
        
        # Pack at the bottom
        self.right_box.pack_start(delete_btn, False, False, 0)
        
        # Initial Load
        self.refresh_styles_gallery()

        # ===============================================
        # BOTTOM AREA: PROMPTS & PROGRESS
        # ===============================================
        
        # We create a VBox below the main columns for the prompts and progress
        bottom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        bottom_box.set_border_width(10)
        content_area.pack_start(bottom_box, False, False, 0)

        # Prompts Container
        prompts_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        
        # Positive
        self.positive_textview = self.add_labeled_textview(
            prompts_container, 
            "Positive Prompt", 
            self.previous_inputs.get("positive_generate_prompt", "") # Loads correctly
        )
        # Negative
        self.negative_textview = self.add_labeled_textview(
            prompts_container, 
            "Negative Prompt", 
            self.previous_inputs.get("negative_generate_prompt", "")
        )
        
        bottom_box.pack_start(prompts_container, False, False, 5)

        # Status Label
        self.status_label = Gtk.Label(label="Ready")
        bottom_box.pack_start(self.status_label, False, False, 2)

        # Progress Bar
        self.progress_bar = Gtk.ProgressBar()
        bottom_box.pack_start(self.progress_bar, False, False, 2)


        # ===============================================
        # ACTION AREA (BUTTONS)
        # ===============================================
        
        action_area = self.get_action_area()
        action_area.set_layout(Gtk.ButtonBoxStyle.CENTER)
        
        # 1. Prompt History (Left / Secondary)
        self.history_button = Gtk.Button.new_with_label("Prompt History")
        self.history_button.connect("clicked", self.on_reveal_history_clicked)
        action_area.pack_start(self.history_button, False, False, 0)
        self.update_history_button_sensitivity()

        self.btn_cancel = Gtk.Button(label="Cancel")
        self.btn_cancel.set_sensitive(False)
        self.btn_cancel.connect("clicked", self.on_cancel_clicked)
        action_area.pack_end(self.btn_cancel, False, False, 0)

        self.btn_generate = Gtk.Button(label="Generate")
        self.btn_generate.get_style_context().add_class("suggested-action")
        self.btn_generate.connect("clicked", self.on_generate_clicked)
        action_area.pack_end(self.btn_generate, False, False, 0)
        
        self.show_all()

    def on_add_style_icon_clicked(self, widget):
        # 1. Get Selection
        selected_items = self.styles_view.get_selected_items()
        if not selected_items:
            Gimp.message("Please select a style first.")
            return

        model = self.styles_view.get_model()
        tree_iter = model.get_iter(selected_items[0])
        json_path = model.get_value(tree_iter, 2)
        
        # 2. Open File Chooser
        dialog = Gtk.FileChooserDialog(
            title="Select Icon Image",
            parent=None,
            action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)

        # Filter for images
        filter_img = Gtk.FileFilter()
        filter_img.set_name("Images")
        filter_img.add_mime_type("image/png")
        filter_img.add_mime_type("image/jpeg")
        filter_img.add_pattern("*.png")
        filter_img.add_pattern("*.jpg")
        filter_img.add_pattern("*.webp")
        dialog.add_filter(filter_img)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            source_file = dialog.get_filename()
            dialog.destroy()
            
            # Process and Save Image
            try:
                dest_path = os.path.splitext(json_path)[0] + ".png"
                
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(source_file, 128, 128, True)
                pixbuf.savev(dest_path, "png", [], [])
                
                self.refresh_styles_gallery()
                
            except Exception as e:
                Gimp.message(f"Failed to set icon: {e}")
        else:
            dialog.destroy()

    def on_delete_style_clicked(self, widget):
        selected_items = self.styles_view.get_selected_items()
        if not selected_items:
            return

        model = self.styles_view.get_model()
        tree_iter = model.get_iter(selected_items[0])
        name = model.get_value(tree_iter, 1)      # Column 1 is Name
        json_path = model.get_value(tree_iter, 2) # Column 2 is File Path

        # Confirmation Dialog
        dialog = Gtk.MessageDialog(
            transient_for=None,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f"Delete style '{name}'?"
        )
        dialog.format_secondary_text("This action cannot be undone.")
        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.OK:
            try:
                # 3. Delete JSON
                if os.path.exists(json_path):
                    os.remove(json_path)
                
                # Delete associated image (if exists)
                # Check common extensions
                base_path = os.path.splitext(json_path)[0]
                for ext in [".png", ".jpg", ".jpeg", ".webp"]:
                    img_path = base_path + ext
                    if os.path.exists(img_path):
                        os.remove(img_path)

                # Refresh
                self.refresh_styles_gallery()
                
            except Exception as e:
                Gimp.message(f"Error deleting style: {e}")

    def on_style_activated(self, icon_view, path):
        """Triggered on double-click or Enter on a style."""
        model = icon_view.get_model()
        tree_iter = model.get_iter(path)
        file_path = model.get_value(tree_iter, 2)
        
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            self.apply_style_settings(data)
        except Exception as e:
            Gimp.message(f"Error loading style: {e}")

    def apply_style_settings(self, data):
        """Updates all UI widgets to match the loaded dictionary."""
        
        # Simple Spinners & Combos
        if "steps" in data: self.steps_spin.set_value(data["steps"])
        if "cfg" in data: self.cfg_spin.set_value(data["cfg"])
        if "seed" in data: self.seed_spin.set_value(data["seed"])
        if "width" in data: self.width_spin.set_value(data["width"])
        if "height" in data: self.height_spin.set_value(data["height"])
        
        # Search for the text ID
        if "sampler" in data:
            # Set combo by text
            for row in self.sampler_combo.get_model():
                if row[0] == data["sampler"]:
                    self.sampler_combo.set_active_iter(row.iter)
                    break
        
        if "scheduler" in data:
            for row in self.scheduler_combo.get_model():
                if row[0] == data["scheduler"]:
                    self.scheduler_combo.set_active_iter(row.iter)
                    break

        # Prompts
        if "positive_generate_prompt" in data and hasattr(self, 'pos_buffer'):
            self.pos_buffer.set_text(data["positive_generate_prompt"])
            
        if "negative_generate_prompt" in data and hasattr(self, 'neg_buffer'):
            self.neg_buffer.set_text(data["negative_generate_prompt"])

        # Checkpoints
        if "checkpoint_selection" in data:
            ckpt_name = data["checkpoint_selection"]
            # Update internal state
            self.selected_checkpoint = ckpt_name
            # Update Label
            if hasattr(self, 'ckpt_status_label'):
                self.ckpt_status_label.set_text(f"Active: {ckpt_name}")
            # Visually select in gallery
            if hasattr(self, 'checkpoints_view'):
                self.select_icon_by_filename(self.checkpoints_view, ckpt_name)

        # Loras
        if "loras" in data:
            # Clear existing Loras
            current_loras = list(self.active_loras.keys())
            for name in current_loras:
                self.on_remove_lora_clicked(None, name)
            
            # Add New Loras
            new_loras = data["loras"]
            
            # Handle both formats (Dict, List)
            if isinstance(new_loras, dict):
                for name, strength in new_loras.items():
                    self.add_lora_row(name, strength)
            elif isinstance(new_loras, list):
                for item in new_loras:
                    if "file" in item:
                        self.add_lora_row(item["file"], item.get("strength", 1.0))

    def on_save_style_clicked(self, widget):
        # Create a simple dialog
        dialog = Gtk.Dialog(title="Save Style", transient_for=None, flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        
        box = dialog.get_content_area()
        box.set_spacing(10)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)

        label = Gtk.Label(label="Enter a name for this style:")
        entry = Gtk.Entry()
        entry.set_activates_default(True) # Allow pressing Enter
        
        box.pack_start(label, False, False, 0)
        box.pack_start(entry, False, False, 0)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()

        response = dialog.run()
        style_name = entry.get_text().strip()
        dialog.destroy()

        if response == Gtk.ResponseType.OK and style_name:
            self.perform_save_style(style_name)

    def perform_save_style(self, name):
        # Get Data
        data = self.get_current_ui_settings()
        
        # Ensure directory exists
        if not os.path.exists(config.settings.styles_dir):
            os.makedirs(config.settings.styles_dir)
            
        # Save File
        # Sanitize filename
        safe_name = "".join([c for c in name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
        file_path = os.path.join(config.settings.styles_dir, f"{safe_name}.json")
        
        try:
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=4)
            
            # Refresh Gallery
            self.refresh_styles_gallery()
            
        except Exception as e:
            Gimp.message(f"Failed to save style: {e}")

    def refresh_styles_gallery(self):
        """Scans styles_dir and populates the right pane with custom icons."""
        self.styles_store.clear()
        
        if not os.path.exists(config.settings.styles_dir):
            return

        # Prepare a default icon fallback
        icon_theme = Gtk.IconTheme.get_default()
        try:
            default_pixbuf = icon_theme.load_icon("preferences-desktop", self.style_icon_size, 0)
        except:
            default_pixbuf = None

        files = sorted(os.listdir(config.settings.styles_dir))
        for f in files:
            if f.endswith(".json"):
                name = os.path.splitext(f)[0]
                full_path = os.path.join(config.settings.styles_dir, f)
                
                # Check for a matching image file
                icon_path = None
                base_path_no_ext = os.path.splitext(full_path)[0]
                
                for ext in [".png", ".jpg", ".jpeg", ".webp"]:
                    if os.path.exists(base_path_no_ext + ext):
                        icon_path = base_path_no_ext + ext
                        break
                
                # Load the specific icon or use default
                pixbuf = default_pixbuf
                if icon_path:
                    try:
                        # Load at specific size for uniformity
                        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_path, self.style_icon_size, self.style_icon_size, True)
                    except:
                        pass # Fallback to default if corrupt
                
                self.styles_store.append([pixbuf, name, full_path])

    def on_lora_added_from_gallery(self, icon_view):
        """
        Triggered when a user clicks a Lora in the gallery.
        Adds it to the active list below.
        """
        selected_items = icon_view.get_selected_items()
        if not selected_items:
            return

        model = icon_view.get_model()
        path = selected_items[0]
        tree_iter = model.get_iter(path)
        full_path = model.get_value(tree_iter, 2)
        filename = os.path.basename(full_path)

        # 1. Check if already added
        if filename in self.active_loras:
            # Optional: Flash the existing row or just ignore
            pass
        else:
            # 2. Add the row
            self.add_lora_row(filename, 1.0)

        # 3. Deselect immediately so it doesn't look "stuck" selected
        icon_view.unselect_all()

    def add_lora_row(self, filename, strength_val):
        """
        Creates the UI row (X Button | Name | Spinner) and adds to data.
        """
        # Create the row container
        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        row_box.set_margin_bottom(2)

        # --- Delete Button (X) ---
        del_btn = Gtk.Button()
        icon = Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON)
        del_btn.set_image(icon)
        del_btn.set_relief(Gtk.ReliefStyle.NONE)
        del_btn.set_tooltip_text("Remove this Lora")
        del_btn.connect("clicked", self.on_remove_lora_clicked, filename)

        # --- Label ---
        # 1. Get the clean name
        full_name = os.path.splitext(filename)[0]
        display_name = full_name

        # 2. Manually truncate if too long (e.g., > 25 characters)
        max_len = 25
        if len(display_name) > max_len:
            # Keep first 22 chars and add "..."
            display_name = display_name[:max_len-3] + "..."

        label = Gtk.Label(label=display_name)
        label.set_halign(Gtk.Align.START)
        
        # 3. Set tooltip so user can hover to see the full name
        label.set_tooltip_text(full_name) 

        # --- Strength Spinner ---
        adj = Gtk.Adjustment(value=strength_val, lower=-2.0, upper=5.0, step_increment=0.01, page_increment=0.5, page_size=0)
        spinner = Gtk.SpinButton(adjustment=adj, climb_rate=0.1, digits=2)
        spinner.set_width_chars(5)
        spinner.connect("value-changed", self.on_lora_strength_changed, filename)

        # Pack widgets
        row_box.pack_start(del_btn, False, False, 0)
        
        # Pack Label with True/True to push the spinner to the right
        row_box.pack_start(label, True, True, 0) 
        
        row_box.pack_start(spinner, False, False, 0)

        # Show all and add to UI
        self.active_loras_box.pack_start(row_box, False, False, 0)
        row_box.show_all()

        # Update Data Dictionary
        self.active_loras[filename] = {
            "strength": strength_val,
            "widget": row_box
        }

    def on_remove_lora_clicked(self, button, filename):
        """Removes the Lora from data and UI."""
        if filename in self.active_loras:
            # 1. Destroy the widget
            widget = self.active_loras[filename]["widget"]
            self.active_loras_box.remove(widget) # Remove from parent
            widget.destroy() # Cleanup memory
            
            # 2. Remove from data
            del self.active_loras[filename]
            
            # Force UI redraw in some GTK versions if it lags
            self.active_loras_box.queue_draw()

    def on_lora_strength_changed(self, spinner, filename):
        """Updates the strength value in the data dict."""
        if filename in self.active_loras:
            self.active_loras[filename]["strength"] = spinner.get_value()

    def get_final_lora_list(self):
        """
        Returns a clean dictionary of loras for processing.
        Format: { 'name.safetensors': 0.8, 'other.safetensors': 1.0 }
        """
        result = {}
        for filename, data in self.active_loras.items():
            # Map filename directly to strength
            result[filename] = data["strength"]
            
        return result

    def add_param_row(self, parent, row, label_text, widget, tooltip=None):
            # Create Label (Right aligned looks best for forms)
            label = Gtk.Label(label=label_text)
            label.set_halign(Gtk.Align.END) 
            label.set_valign(Gtk.Align.CENTER)
            
            if tooltip:
                widget.set_tooltip_text(tooltip)
                label.set_tooltip_text(tooltip)

            # Attach to Grid: (child, left, top, width, height)
            parent.attach(label, 0, row, 1, 1)
            parent.attach(widget, 1, row, 1, 1)

    # --- Worker Logic ---
    def get_default_dimensions(self):
        """Safely gets dimensions from the active image or defaults to 512."""
        try:
            images = Gimp.get_images()
            if images:
                # Use the first open image found
                return images[0].get_width(), images[0].get_height()
        except Exception:
            pass
        return 512, 512 # Fallback defaults

    def get_current_ui_settings(self):
        """Extracts all values from the UI into a dictionary."""
        pos_prompt, neg_prompt = self.get_text_results()
        
        return {
            "checkpoint_selection": self.selected_checkpoint,
            "loras": self.get_final_lora_list(),
            "positive_generate_prompt": pos_prompt,
            "negative_generate_prompt": neg_prompt,
            "steps": self.steps_spin.get_value_as_int(),
            "cfg": self.cfg_spin.get_value(),
            "sampler": self.sampler_combo.get_active_text(),
            "scheduler": self.scheduler_combo.get_active_text(),
            "seed": int(self.seed_spin.get_value()),
            "width": self.width_spin.get_value_as_int(),
            "height": self.height_spin.get_value_as_int(),
            "active_workflow": self.workflow_combo.get_active_id() if hasattr(self, 'workflow_combo') else None
        }

    def save_settings(self):
        """Saves active values to the persistent last_inputs.json file."""
        settings = self.get_current_ui_settings()
        self.history_manager.add_entry(settings["positive_generate_prompt"], settings["negative_generate_prompt"])
        GimpUtils.update_json_file(settings, config.settings.last_inputs_path)

    def on_generate_clicked(self, widget):
        if self.is_generating: return

        self.save_settings()

        self.status_label.set_text(f"Generating...")
        Gimp.progress_set_text("Generating...")

        try:
            images = Gimp.get_images()
            if images:
                # Use the existing open image
                self.active_image = images[0]
            else:
                # No image open? Create a new one based on UI settings
                width = self.width_spin.get_value_as_int()
                height = self.height_spin.get_value_as_int()
                self.active_image = Gimp.Image.new(width, height, Gimp.ImageBaseType.RGB)
                Gimp.Display.new(self.active_image)
        except Exception as e:
            Gimp.message(f"Error accessing or creating image: {e}")
            import traceback
            Gimp.message(traceback.format_exc())
            return

        # --- GATHER INPUTS ---
        # 1. Text
        pos_prompt, neg_prompt = self.get_text_results()

        # 2. KSampler & Dimensions
        steps = self.steps_spin.get_value_as_int()
        cfg = self.cfg_spin.get_value()
        sampler = self.sampler_combo.get_active_text()
        scheduler = self.scheduler_combo.get_active_text()
        seed = int(self.seed_spin.get_value())
        width = self.width_spin.get_value_as_int()
        height = self.height_spin.get_value_as_int()

        # Handle Random Seed
        if seed == -1 or seed == 0:
            seed = random.randint(1, 2**32)

        # 3. Build Dictionaries
        try:
            main_dict = {
                "positive_prompt": pos_prompt,
                "negative_prompt": neg_prompt,
                "seed": seed,
                "checkpoint_selection": self.selected_checkpoint,
                "image_width": width,
                "image_height": height,
            }

            lora_dict = self.get_final_lora_list()

            ksampler_dict = {
                "steps": steps,
                "cfg": cfg,
                "sampler": sampler,
                "scheduler": scheduler
            }
        except Exception as e:
            Gimp.message(f"Error preparing input dictionaries: {e}")
            return
        
        workflow_path = self.workflow_combo.get_active_id()
        if not workflow_path: 
            Gimp.message("Please select a workflow from the dropdown.")
            return

        # 2. Prepare Workflow
        # We can do this on main thread as it's fast
        try:
            workflow, _ = ComfyUtils.prepare_workflow(workflow_path, main_dict, lora_dict, ksampler_dict)
        except Exception as e:
            Gimp.message(f"Workflow Error: {e}")
            return

        # 3. Lock UI
        self.set_generating_state(True)
        
        # 4. Spawn Thread
        try:
            thread = threading.Thread(
                target=self.worker_thread, 
                args=(workflow, config.settings.default_server_address)
            )
            thread.daemon = True
            thread.start()
        except Exception as e:
            Gimp.message(f"Error starting generation thread: {e}")
            self.set_generating_state(False)

    def worker_thread(self, workflow, server_address):
        """
        Runs in background. 
        NO GIMP CALLS ALLOWED HERE.
        """
        client_id = str(uuid.uuid4())
        
        # Call our new Generator
        stream = ComfyUtils.generate_stream(workflow, server_address, client_id)
        
        for event_type, data in stream:
            # STOP signal check
            if not self.is_generating: 
                break 

            if event_type == "preview_bytes":
                GLib.idle_add(self.update_preview, data)

            elif event_type == "progress":
                val, maximum = data
                GLib.idle_add(self.update_progress, val, maximum)

            elif event_type == "finished_metadata":
                # data is a list of output images dicts
                self.process_final_outputs(data, server_address)

            elif event_type == "error":
                GLib.idle_add(self.show_error, data)

        # Cleanup
        GLib.idle_add(self.set_generating_state, False)

    def process_final_outputs(self, outputs, server_address):
        """
        Downloads images using fixed indices to prevent temp folder spam.
        """
        # 1. Ensure Temp Directory Exists
        if not os.path.exists(config.settings.temp_images_dir):
            try:
                os.makedirs(config.settings.temp_images_dir, exist_ok=True)
            except Exception as e:
                Gimp.message(f"Error creating temp dir: {e}")
                return

        for idx, output in enumerate(outputs):
            try:
                filename = output.get("filename")
                subfolder = output.get("subfolder", "")
                type_str = output.get("type", "output")
                
                # Extract extension (png/jpg) from original filename
                ext = filename.split('.')[-1] if '.' in filename else "png"
                
                # 2. Use Fixed Filename based on Index (No UUID)
                # "final_output_0.png", "final_output_1.png", etc.
                fixed_name = f"final_output_{idx}.{ext}"
                save_path = os.path.join(config.settings.temp_images_dir, fixed_name)
                
                # 3. Download (Worker Thread)
                # This will simply overwrite the existing file from the last run
                success = ComfyUtils.download_image(server_address, filename, subfolder, type_str, save_path)
                
                if success:
                    # 4. Schedule Insertion (Main Thread)
                    GLib.idle_add(self.insert_final_image, save_path)
                else:
                    print(f"Failed to download {filename}")

            except Exception as e:
                print(f"Error processing output item: {e}")

    # --- UI Updaters (Run on Main Thread via idle_add) ---

    def update_preview(self, image_data):
        """
        Receives raw bytes, writes them to a single temp file, and updates the layer.
        """
        
        if not self.is_generating: return False

        # 2. Define Single File Path (No unique IDs = No Spam)
        temp_path = os.path.join(config.settings.temp_images_dir, "preview.png")

        try:
            # 3. Write File (Main Thread = No Race Condition)
            with open(temp_path, "wb") as f:
                f.write(image_data)
                f.flush() # Ensure data is physically on disk
                os.fsync(f.fileno()) 

            # 4. Remove Old Layer
            if self.preview_layer and self.preview_layer.is_valid():
                self.active_image.remove_layer(self.preview_layer)
                self.preview_layer = None

            # 5. Insert New Layer
            # We do NOT delete the file afterwards. We just overwrite it next time.
            self.preview_layer = ComfyUtils.insert_image_layer(self.active_image, temp_path, "Comfy Preview")
            
            Gimp.displays_flush()

        except Exception as e:
            Gimp.message(f"Preview Error: {e}")
        
        return False # Stop idle_add

    def cleanup_temp_files(self):
        """Call this when generation is finished or cancelled."""
        preview_path = os.path.join(config.settings.temp_images_dir, "preview.png")
        if os.path.exists(preview_path):
            try:
                os.remove(preview_path)
            except: pass

    def update_progress(self, value, maximum):
        fraction = value / maximum
        self.progress_bar.set_fraction(fraction)
        self.status_label.set_text(f"Step {value}/{maximum}")
        return False

    def insert_final_image(self, file_path):
        if not self.active_image or not self.active_image.is_valid():
            self.status_label.set_text("Target image was closed.")
            return False
    
        try:
            # Remove the Preview Layer
            if self.preview_layer and self.preview_layer.is_valid():
                self.active_image.remove_layer(self.preview_layer)
                self.preview_layer = None
            
            # Insert the Final Result
            ComfyUtils.insert_image_layer(self.active_image, file_path, "Comfy Result")
            
            
            self.status_label.set_text(f"Done")
            Gimp.progress_set_text("Generation Complete")

            Gimp.displays_flush()
            
        except Exception as e:
            Gimp.message(f"Error inserting image: {e}")
            
        return False # Stop idle_add

    def show_error(self, message):
        Gimp.message(message)
        return False

    def set_generating_state(self, is_active):
        self.is_generating = is_active
        self.btn_generate.set_sensitive(not is_active)
        self.btn_cancel.set_sensitive(is_active)
        if not is_active:
            self.progress_bar.set_text("Ready")
            self.progress_bar.set_fraction(0.0)
        return False

    def on_cancel_clicked(self, widget):
        # Immediate UI Feedback
        self.is_generating = False
        self.status_label.set_text(f"Cancelling...")
        self.btn_cancel.set_sensitive(False) # Prevent double clicks

        # Define the interrupt task
        def send_interrupt_signal():
            try:
                url = "http://{}/interrupt".format(config.settings.default_server_address)
                requests.post(url, timeout=2) 
                Gimp.message("Interrupt signal sent.")
            except Exception as e:
                GLib.idle_add(Gimp.message, "Failed to send interrupt: " + str(e))

        self.status_label.set_text(f"Done")
        Gimp.progress_set_text("Cancelled")

        # Run network request in a ephemeral thread
        t = threading.Thread(target=send_interrupt_signal)
        t.daemon = True
        t.start()

    def create_spin_row(self, label_text, value, lower, upper, step=1, digits=0):
        """Creates a row with a Label and a SpinButton for integers."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        label = Gtk.Label(label=label_text, xalign=0)
        
        # Page increment (step * 10) allows faster scrolling if holding shift/page-up
        adj = Gtk.Adjustment(value=value, lower=lower, upper=upper, step_increment=step, page_increment=step*10)
        
        spin = Gtk.SpinButton(adjustment=adj, climb_rate=step, digits=digits)
        spin.set_numeric(True) # Forces only numeric input
        spin.set_snap_to_ticks(False) # Allows typing 500 even if step is 64
        spin.set_hexpand(True)
        
        box.pack_start(label, False, False, 0)
        box.pack_end(spin, False, False, 0)
        return box, spin

    def create_combo_row(self, label_text, options, default_val):
        """Creates a row with a Label and a ComboBoxText."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        label = Gtk.Label(label=label_text, xalign=0)
        
        combo = Gtk.ComboBoxText()
        for opt in options:
            combo.append_text(opt)
            
        # Set default
        if default_val in options:
            combo.set_active(options.index(default_val))
        else:
            combo.set_active(0)
            
        box.pack_start(label, False, False, 0)
        box.pack_end(combo, False, False, 0) # Right align
        return box, combo
        
    def populate_workflows_dropdown(self):
        """Loads workflows and populates the workflow ComboBox."""
        workflows_data = self.workflow_manager.load_workflows()
        
        # Add each workflow from the JSON file
        for wf in workflows_data.get("workflows", []):
            # The ID is the path, the visible text is the title
            self.workflow_combo.append(wf['path'], wf['title'])
        
        if not workflows_data.get("workflows"):
            self.workflow_combo.append(None, "Select a Workflow...")

        self.workflow_combo.set_active(0)
        self.selected_workflow_path = self.workflow_combo.get_active_id()
    
    def on_workflow_selected(self, combo):
        """
        Handles the selection of a workflow from the dropdown.
        Stores the selected workflow's file path.
        """
        self.selected_workflow_path = combo.get_active_id()

    def on_manage_workflows_clicked(self, widget):
        # 1. Capture current selection before opening dialog
        current_path = self.workflow_combo.get_active_id()
        
        dialog = WorkflowDialog(self, self.workflow_manager)

        while True:
            response = dialog.run()
            
            if response == Gtk.ResponseType.APPLY:
                dialog.run_file_chooser()
                continue
                
            elif response == Gtk.ResponseType.OK:
                selected = dialog.get_selected_workflow()
                dialog.destroy()
                
                # Refresh list
                self.workflow_combo.remove_all()
                self.populate_workflows_dropdown()
                
                # Set to NEW selection
                if selected:
                    self.set_active_workflow_by_path(selected['path'])
                break
                
            else: # Close / Cancel
                dialog.destroy()
                
                # Refresh list (in case they deleted the active item)
                self.workflow_combo.remove_all()
                self.populate_workflows_dropdown()
                
                # Attempt to RESTORE previous selection
                # If the previous item was deleted, this will safely fail and stay at 0
                if current_path:
                    self.set_active_workflow_by_path(current_path)
                break

    def set_active_workflow_by_path(self, path):
        """Helper to select the combo item matching the path."""
        if path:
            self.workflow_combo.set_active_id(path)

    def on_reveal_history_clicked(self, widget):
        dialog = HistoryDialog(self, self.history_manager)
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            selected = dialog.get_selected_entry()
            if selected:
                self.positive_textview.get_buffer().set_text(selected.get("positive", ""))
                self.negative_textview.get_buffer().set_text(selected.get("negative", ""))
        
        dialog.destroy()
        # After closing, check if history is empty (e.g., if user deleted all entries)
        self.update_history_button_sensitivity()

    def update_history_button_sensitivity(self):
        """Enables or disables the history button based on whether history exists."""
        has_history = bool(self.history_manager.load_history())
        self.history_button.set_sensitive(has_history)
        
    def save_current_inputs_to_history(self):
        positive_buffer = self.positive_textview.get_buffer()
        negative_buffer = self.negative_textview.get_buffer()
        positive_text = positive_buffer.get_text(positive_buffer.get_start_iter(), positive_buffer.get_end_iter(), True)
        negative_text = negative_buffer.get_text(negative_buffer.get_start_iter(), negative_buffer.get_end_iter(), True)
        
        self.history_manager.add_entry(positive_text, negative_text)
        self.update_history_button_sensitivity()

    def add_labeled_textview(self, parent, label_text, default_value="", height=80, width=-1):
        """
        Adds a label and a scrolling textview.
        Args:
            height: Height in pixels (default 80)
            width: Width in pixels (default -1, which means auto/fill)
        """
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        box.get_style_context().add_class("textview_box")

        label = Gtk.Label(label=label_text)

        # Pass the width/height to your helper
        scrolled_window = self.create_scrolled_window(
            "textview_scrolled_window", 
            Gtk.PolicyType.NEVER, 
            Gtk.PolicyType.AUTOMATIC, 
            width, 
            height
        )

        textview = Gtk.TextView()
        textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        textview.get_style_context().add_class("textview_text")
        
        # Set margins to make text easier to read inside the box
        textview.set_left_margin(5)
        textview.set_right_margin(5)
        textview.set_top_margin(5)
        textview.set_bottom_margin(5)

        # Set default text
        buffer = textview.get_buffer()
        buffer.set_text(default_value)

        scrolled_window.add(textview)
        box.pack_start(label, False, False, 0)
        box.pack_start(scrolled_window, True, True, 0)
        
        parent.pack_start(box, False, False, 0)

        return textview

    def create_scrolled_window(self, item_class, horizontal_scroll, vertical_scroll, requested_width=400, requested_height=300):
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(horizontal_scroll, vertical_scroll)
        
        # This applies the specific dimensions requested
        scrolled_window.set_size_request(requested_width, requested_height)
        
        scrolled_window.get_style_context().add_class(item_class)
        return scrolled_window

    def add_expandable_section(self, parent_box, title, content_widget):
        """
        Wraps any widget in a Gtk.Expander and packs it into the parent box.
        """
        expander = Gtk.Expander(label=title)
        expander.get_style_context().add_class("expander")
        
        # Add the content
        expander.add(content_widget)
        
        # Pack the expander itself
        parent_box.pack_start(expander, False, False, 0)
        return expander

    def create_gallery_widget(self, section_title, selection_mode):
        """
        Creates the gallery content and a separate status label.
        Returns: (content_container, icon_view, status_label_widget)
        """
        # content_container: Holds Buttons + IconView (INSIDE the expander)
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        container.set_margin_top(5)
        container.set_margin_bottom(5)

        # --- Toolbar ---
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        btn_models = Gtk.Button(label="Set Models Folder")
        btn_icons = Gtk.Button(label="Set Icons Folder")
        btn_models.set_hexpand(True)
        btn_icons.set_hexpand(True)
        
        btn_models.connect("clicked", self.on_set_folder_clicked, section_title, "models")
        btn_icons.connect("clicked", self.on_set_folder_clicked, section_title, "icons")
        
        button_box.pack_start(btn_models, True, True, 0)
        button_box.pack_start(btn_icons, True, True, 0)
        container.pack_start(button_box, False, False, 0)

        # --- Icon View ---
        list_store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str)
        if not hasattr(self, 'icon_view_models'):
            self.icon_view_models = {}
        self.icon_view_models[section_title] = list_store

        icon_view = Gtk.IconView.new_with_model(list_store)
        icon_view.set_selection_mode(selection_mode)
        icon_view.set_pixbuf_column(0)
        icon_view.set_text_column(1)
        icon_view.set_item_width(85)
        icon_view.set_column_spacing(2)
        icon_view.set_row_spacing(2)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(250)
        scroller.add(icon_view)
        container.pack_start(scroller, True, True, 0)

        return container, icon_view
    
    def on_gallery_selection_changed(self, icon_view, label_widget, section_title):
        """
        Triggered when the user clicks an icon. 
        Updates the label and internal state immediately.
        """
        selected_items = icon_view.get_selected_items()
        model = icon_view.get_model()

        if not selected_items:
            label_widget.set_text("None")
            # Clear internal state if needed
            if section_title == "Checkpoints":
                self.selected_checkpoint = None
            return

        # Handle Single Selection (Checkpoints)
        if section_title == "Checkpoints":
            path = selected_items[0]
            tree_iter = model.get_iter(path)
            full_path = model.get_value(tree_iter, 2) # Column 2 is filepath
            filename = os.path.basename(full_path)
            
            # 1. Update UI Label
            label_widget.set_text(filename)
            
            # 2. Update Internal State (Clean Reference)
            self.selected_checkpoint = filename
            
        # Handle Multiple Selection (Loras) - Optional
        elif section_title == "Loras":
            count = len(selected_items)
            label_widget.set_text(f"{count} selected")
            # Logic to store lora list...

    def select_icon_by_filename(self, icon_view, target_filename):
        """
        Helper to find an icon by filename and programmatically select it.
        This fixes the issue of the gallery looking 'empty' on startup.
        """
        if not target_filename:
            return

        model = icon_view.get_model()
        
        # Iterate over the model to find the matching file
        for row in model:
            # row[2] is the full file path
            current_file = os.path.basename(row[2])
            if current_file == target_filename:
                # Found it! Get the path and select it
                path = row.path
                icon_view.select_path(path)
                icon_view.scroll_to_path(path, False, 0, 0)
                return

    def initialize_icon_view_from_config(self, section_title):
        """Checks the config file for paths and populates the IconView if found."""
        last_inputs = GimpUtils.load_json_file(config.settings.last_inputs_path)
        
        key_base = section_title.lower()
        model_key = f"{key_base}_models_folder"
        icon_key = f"{key_base}_icons_folder"

        model_dir = last_inputs.get(model_key)
        icon_dir = last_inputs.get(icon_key)

        if model_dir and os.path.isdir(model_dir):
            if not hasattr(self, 'custom_paths'):
                self.custom_paths = {}
            self.custom_paths[section_title] = {'models': model_dir, 'icons': icon_dir}
            
            # Scan the folders and update the UI
            self.rescan_and_update_icon_view(section_title)

    def on_set_folder_clicked(self, widget, section_title, folder_type):
        """Handles clicks for the 'Set Folder' buttons and saves the choice."""
        dialog = Gtk.FileChooserDialog(
            title=f"Select {folder_type.capitalize()} Folder for {section_title}",
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            folder_path = dialog.get_filename()
            
            if not hasattr(self, 'custom_paths'):
                self.custom_paths = {}
            if section_title not in self.custom_paths:
                self.custom_paths[section_title] = {'models': None, 'icons': None}
            
            self.custom_paths[section_title][folder_type] = folder_path
            
            key_base = section_title.lower()
            json_key = f"{key_base}_{folder_type}_folder"  # e.g., "checkpoints_models_folder"
            data_to_save = {json_key: folder_path}
            GimpUtils.update_json_file(data_to_save, config.settings.last_inputs_path)
            
            # Rescan and update of the corresponding icon view
            self.rescan_and_update_icon_view(section_title)

        dialog.destroy()

    def rescan_and_update_icon_view(self, section_title):
        """
        Non-blocking version: Scans directory and loads icons one by one
        using GLib.idle_add generator pattern.
        """
        # 1. Get paths and store
        paths = self.custom_paths.get(section_title, {})
        model_dir = paths.get('models')
        icon_dir = paths.get('icons')
        
        list_store = self.icon_view_models.get(section_title)
        if not list_store or not model_dir or not os.path.exists(model_dir):
            return

        # Clear existing items immediately so user sees something happened
        list_store.clear()

        # 2. Gather filenames (Fast enough to do synchronously usually)
        try:
            all_files = sorted(os.listdir(model_dir))
        except Exception as e:
            Gimp.message(f"Error reading folder: {e}")
            return

        supported_model_exts = {'.safetensors', '.ckpt', '.pt'}
        supported_icon_exts = ['.png', '.jpg', '.jpeg', '.webp']

        # Pre-filter for valid models only
        model_files = [f for f in all_files if os.path.splitext(f)[1].lower() in supported_model_exts]

        def icon_loader_generator():
            # Create a default fallback icon once
            default_pixbuf = None
            try:
                icon_theme = Gtk.IconTheme.get_default()
                default_pixbuf = icon_theme.load_icon("image-x-generic", 64, 0)
            except: 
                pass

            for filename in model_files:
                # -- SAFETY CHECK --
                if not hasattr(self, 'icon_view_models'):
                    yield False
                    return

                # Prepare data
                full_path = os.path.join(model_dir, filename)
                display_name = os.path.splitext(filename)[0]
                pixbuf = default_pixbuf

                # Try to find a custom icon
                if icon_dir and os.path.isdir(icon_dir):
                    for ext in supported_icon_exts:
                        possible_icon = os.path.join(icon_dir, display_name + ext)
                        if os.path.exists(possible_icon):
                            try:
                                # Loading images is the heavy part!
                                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(possible_icon, 100, 100, True)
                                break
                            except:
                                pass # Keep default if corrupt
                
                # Update UI (We are in the Main Thread, so this is safe)
                # Append: [Icon, Name, Full Path]
                try:
                    list_store.append([pixbuf, display_name, full_path])
                except Exception:
                    # If store was destroyed mid-loop
                    yield False
                    return

                # Yield True to tell GLib "Run me again next idle cycle"
                yield True

            # When loop finishes, yield False to stop the idle function
            yield False

        # 4. Start the Generator
        loader = icon_loader_generator()
        GLib.idle_add(lambda: next(loader, False))
    

    
    def create_ksampler_section(self, data):
        ksampler_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        ksampler_box.get_style_context().add_class("ksampler_box")
        for ksampler_child in data:
            ksampler_box.pack_start(ksampler_child, False, False, 0)
        return ksampler_box

    def get_text_results(self):
        positive_buffer = self.positive_textview.get_buffer()
        negative_buffer = self.negative_textview.get_buffer()
        positive_text = positive_buffer.get_text(positive_buffer.get_start_iter(), positive_buffer.get_end_iter(), True)
        negative_text = negative_buffer.get_text(negative_buffer.get_start_iter(), negative_buffer.get_end_iter(), True)
        return positive_text, negative_text
    
    def get_selected_items(self, icon_view):
        return [str(item) for item in icon_view.get_selected_items()]

    def get_selected_checkpoint(self, icon_view):
        model = icon_view.get_model()
        selected_items = icon_view.get_selected_items()

        # Check if anything is selected
        if not selected_items:
            return None

        # Since it is single selection, we just grab the first item
        tree_iter = model.get_iter(selected_items[0])
        file_path = model.get_value(tree_iter, 2)
        
        # Return the filename safely
        return os.path.basename(file_path)

    def get_selected_lora_data(self, icon_view):
        """
        Returns a dict of {filename: strength} for selected items.
        Default strength is set to 1.0.
        """
        lora_dict = {} # Initialize as Dictionary, not List
        model = icon_view.get_model()
        selected_items = icon_view.get_selected_items()

        for item_path in selected_items:
            tree_iter = model.get_iter(item_path)
            file_path = model.get_value(tree_iter, 2)
            file_name = os.path.basename(file_path)
            
            # Map filename to default strength 1.0
            lora_dict[file_name] = 1.0 
            
        return lora_dict
    
class WorkflowManager:
    """Manages adding, storing, and removing workflow files."""
    def __init__(self):
        pass

    def load_workflows(self):
        """Loads the workflows data from the JSON file."""
        if not os.path.exists(config.settings.workflows_json_path):
            return {"workflows": []}
        try:
            with open(config.settings.workflows_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "workflows" not in data or not isinstance(data.get("workflows"), list):
                    return {"workflows": []}
                return data
        except (json.JSONDecodeError, IOError):
            return {"workflows": []}

    def save_workflows(self, data):
        """Saves the workflow data to the JSON file."""
        try:
            with open(config.settings.workflows_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except IOError as e:
            print(f"Error saving workflows: {e}")

    def add_workflows(self, file_paths_to_add):
        """Adds a list of file paths, checking for JSON and duplicates."""
        data = self.load_workflows()
        existing_paths = {wf['path'] for wf in data.get("workflows", [])}
        added_count = 0

        for path in file_paths_to_add:
            if path.lower().endswith('.json') and path not in existing_paths:
                title = os.path.basename(path)[:-5] # Get filename without .json
                new_entry = {"path": path, "title": title}
                data["workflows"].append(new_entry)
                existing_paths.add(path)
                added_count += 1
        
        if added_count > 0:
            self.save_workflows(data)
        
        return added_count

    def delete_workflow(self, path_to_delete):
        """Deletes a specific workflow path from the list."""
        data = self.load_workflows()
        workflows = data.get("workflows", [])
        
        # Filter out the item with the matching path
        new_workflows = [wf for wf in workflows if wf['path'] != path_to_delete]
        
        if len(new_workflows) < len(workflows):
            data["workflows"] = new_workflows
            self.save_workflows(data)
            return True
        return False
    
class WorkflowDialog(Gtk.Dialog):
    def __init__(self, parent, workflow_manager):
        super().__init__(title="Manage Workflows", transient_for=parent, flags=0)
        self.workflow_manager = workflow_manager
        self.parent = parent
        
        self.set_default_size(600, 450)
        self.set_border_width(10)
        self.selected_workflow = None

        # --- Content Area ---
        content_area = self.get_content_area()
        
        # Description Label
        lbl = Gtk.Label(label="Manage your JSON workflows.")
        content_area.pack_start(lbl, False, False, 5)

        # Scrolled Window for List
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content_area.pack_start(scrolled_window, True, True, 5)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)

        scrolled_window.add(self.list_box)

        # Populate rows
        self.refresh_list()
        
        self.list_box.connect("row-activated", self.on_row_activated)

        # --- Action Area Buttons ---
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.new_workflow_button = self.add_button("Add New Workflow", Gtk.ResponseType.APPLY)
        self.new_workflow_button.get_style_context().add_class("suggested-action")

        self.show_all()

    def refresh_list(self):
        """Clears and re-populates the list box."""
        # Clear existing
        for child in self.list_box.get_children():
            self.list_box.remove(child)

        data = self.workflow_manager.load_workflows()
        workflows = data.get("workflows", [])
        
        if not workflows:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label="No workflows found.", xalign=0.5)
            label.set_sensitive(False)
            row.add(label)
            self.list_box.add(row)
        else:
            for wf in workflows:
                self.add_workflow_row(wf)
        
        self.list_box.show_all()

    def get_transparent_style(self):
        """Returns a CSS provider that forces transparency."""
        css_provider = Gtk.CssProvider()
        # We define a class '.transparent-bg' that forces the background to be empty
        css_provider.load_from_data(b"""
            .transparent-bg {
                background-color: transparent;
                background-image: none; 
            }
        """)
        return css_provider

    def make_transparent(self, widget):
        """Helper to apply the transparency class to a specific widget."""
        context = widget.get_style_context()
        context.add_class("transparent-bg")
        # Ensure the provider is attached with high priority
        context.add_provider(self.get_transparent_style(), Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def add_workflow_row(self, wf_entry):
        """Creates a row with Title/Path and a Delete button."""
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add(hbox)

        # Text Info
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.make_transparent(vbox)
        title = Gtk.Label(label=wf_entry.get('title', 'Unknown'), xalign=0)
        title.get_style_context().add_class("heading") # Make title bold
        
        path_lbl = Gtk.Label(label=wf_entry.get('path', ''), xalign=0)
        path_lbl.get_style_context().add_class("dim-label") # Make path subtler
        path_lbl.set_line_wrap(True)
        path_lbl.set_max_width_chars(60)

        vbox.pack_start(title, False, False, 0)
        vbox.pack_start(path_lbl, False, False, 0)
        
        hbox.pack_start(vbox, True, True, 5)

        # Delete Button
        delete_button = Gtk.Button.new_from_icon_name("edit-delete", Gtk.IconSize.BUTTON)
        delete_button.set_tooltip_text("Remove from workflows")
        delete_button.connect("clicked", self.on_delete_clicked, row)
        
        hbox.pack_start(delete_button, False, False, 5)

        row.wf_data = wf_entry
        self.list_box.add(row)

    def on_delete_clicked(self, widget, row):
        """Handles deletion of a workflow."""
        path = row.wf_data.get('path')
        
        dialog = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Remove '{row.wf_data.get('title')}'?"
        )
        dialog.format_secondary_text(f"Path: {path}")
        
        response = dialog.run()
        dialog.destroy()
        
        if response == Gtk.ResponseType.YES:
            if self.workflow_manager.delete_workflow(path):
                self.refresh_list()

    def on_row_activated(self, list_box, row):
        """Handle double clicks."""
        if hasattr(row, 'wf_data'):
            self.selected_workflow = row.wf_data
            self.response(Gtk.ResponseType.OK)

    def run_file_chooser(self):
        """Opens file browser to add new json files."""
        dialog = Gtk.FileChooserDialog(
            title="Select Workflow JSON",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK,
        )
        dialog.set_select_multiple(True)

        json_filter = Gtk.FileFilter()
        json_filter.set_name("JSON files (*.json)")
        json_filter.add_pattern("*.json")
        dialog.add_filter(json_filter)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            paths = dialog.get_filenames()
            count = self.workflow_manager.add_workflows(paths)
            if count > 0:
                self.refresh_list()
        
        dialog.destroy()

    def get_selected_workflow(self):
        if self.selected_workflow:
            return self.selected_workflow
        
        # If user clicked OK but didn't double click a row, get selected row
        row = self.list_box.get_selected_row()
        if row and hasattr(row, 'wf_data'):
            return row.wf_data
        return None

class HistoryManager:
    """Manages storing, retrieving, and deleting prompt history."""
    def __init__(self):
        self.history_path = os.path.join(config.settings.comfy_dir, 'History')
        self.history_file = os.path.join(self.history_path, 'prompt_history.json')
        
        if not os.path.exists(self.history_path):
            os.makedirs(self.history_path)

    def load_history(self):
        """Loads history from the JSON file."""
        if not os.path.exists(self.history_file):
            return []
        try:
            with open(self.history_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

    def save_history(self, history_data):
        """Saves the provided history data to the JSON file."""
        with open(self.history_file, 'w') as f:
            json.dump(history_data, f, indent=4)
            
    def add_entry(self, positive_prompt, negative_prompt):
        """Adds a new entry to the history, avoiding duplicates."""
        history = self.load_history()
        new_entry = {"positive": positive_prompt, "negative": negative_prompt}
        if not positive_prompt and not negative_prompt:
            return
        if new_entry not in history:
            history.insert(0, new_entry)
            self.save_history(history)

    def delete_entry(self, entry_to_delete):
        """Deletes a specific entry from the history."""
        history = self.load_history()
        # Create a new list excluding the entry that matches the one to be deleted
        new_history = [entry for entry in history if entry != entry_to_delete]
        
        if len(new_history) < len(history):
            self.save_history(new_history)
            return True # Item was deleted
        return False

## History Selection Dialog
class HistoryDialog(Gtk.Dialog):
    def __init__(self, parent, history_manager):
        super().__init__(title="Prompt History", transient_for=parent, flags=0)
        self.history_manager = history_manager
        
        self.add_buttons(
            "Close", Gtk.ResponseType.CLOSE,
            "Select", Gtk.ResponseType.OK
        )
        self.set_default_size(600, 400)
        self.set_border_width(10)
        self.selected_entry = None

        content_area = self.get_content_area()
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content_area.pack_start(scrolled_window, True, True, 0)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        scrolled_window.add(self.list_box)

        # Populate rows
        history_data = self.history_manager.load_history()
        for entry in history_data:
            self.add_history_row(entry)
        
        self.list_box.connect("row-activated", self.on_row_activated)
        self.show_all()

    def add_history_row(self, entry):
        """Creates a row with a label and a delete button."""
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add(hbox)

        pos_text = (entry['positive'][:70] + '...') if len(entry['positive']) > 70 else entry['positive']
        neg_text = (entry['negative'][:70] + '...') if len(entry['negative']) > 70 else entry['negative']
        label = Gtk.Label(label=f"Positive: {pos_text}\nNegative: {neg_text}", xalign=0)
        hbox.pack_start(label, True, True, 5)

        delete_button = Gtk.Button.new_from_icon_name("edit-delete", Gtk.IconSize.BUTTON)
        delete_button.set_tooltip_text("Delete this entry")
        delete_button.connect("clicked", self.on_delete_entry_clicked, row)
        hbox.pack_start(delete_button, False, False, 5)
        
        row.entry_data = entry
        self.list_box.insert(row, -1)

    def on_delete_entry_clicked(self, widget, row):
        """Handles the click of a delete button on a row."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Delete this entry?",
        )
        dialog.format_secondary_text("This action cannot be undone.")
        
        response = dialog.run()
        if response == Gtk.ResponseType.YES:
            if self.history_manager.delete_entry(row.entry_data):
                self.list_box.remove(row)
                self.show_all()
        dialog.destroy()

    def on_row_activated(self, list_box, row):
        """Responds to a double-click on a row, same as clicking 'Select'."""
        self.selected_entry = row.entry_data
        self.response(Gtk.ResponseType.OK)

    def get_selected_entry(self):
        if self.selected_entry:
            return self.selected_entry
        row = self.list_box.get_selected_row()
        return row.entry_data if row else None