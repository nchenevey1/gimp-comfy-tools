#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Classes:
# --------
# MainProcedureDialog(GimpUi.ProcedureDialog)
#     - Main dialog for the "generate" procedure
# LoraDialog(GimpUi.ProcedureDialog)
#     - Dialog for selecting and assigning weights to Lora models.
# FavoritesManager
#     - Handles loading, saving, and adding favorite workflow JSON files.
# HistoryManager
#     - Manages prompt history: loading, saving, adding, and deleting prompt entries.
# HistoryDialog(Gtk.Dialog)
#     - Dialog for browsing, selecting, and deleting prompt history entries.
# Global Variables:
# -----------------
# comfy_dir_name: Name of the main plugin data directory.
# gimp_dir: Path to the user's GIMP directory.
# comfy_dir: Path to the plugin's data directory.
# data_dir: Path to the plugin's data subdirectory.
# last_inputs_file_name: Filename for storing last used inputs.
# last_inputs_file_path: Full path to the last inputs JSON file.
# workflows_dir: Path to the workflows directory.
# favorites_json_path: Path to the favorite workflows JSON file.

# Python imports
import os
import json
import importlib.util

# GIMP imports
import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
gi.require_version('GimpUi', '3.0')
from gi.repository import GimpUi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf

comfy_dir_name = "comfy"
gimp_dir = Gimp.directory()
comfy_dir = os.path.join(gimp_dir, comfy_dir_name)
os.makedirs(comfy_dir, exist_ok=True)

### Set values for defaults ###
data_dir = os.path.join(comfy_dir, "data")
os.makedirs(data_dir, exist_ok=True)

last_inputs_file_name = "last_inputs.json"
last_inputs_file_path = os.path.join(data_dir, last_inputs_file_name)

# Read favorites.json from comfy_dir and check existence
workflows_dir = os.path.join(comfy_dir, "Workflows")
os.makedirs(workflows_dir, exist_ok=True)

# 
favorites_json_path = os.path.join(workflows_dir, "favorites.json")
favorites_exists = os.path.exists(favorites_json_path)
if favorites_exists:
    with open(favorites_json_path, "r", encoding="utf-8") as f:
        favorites_data = json.load(f)
    favorites = favorites_data.get("favorites", [])
else:
    favorites = []\

gimp_utils_import_path = os.path.join(os.path.dirname(__file__), "gimp_utils.py")
gimp_utils_spec = importlib.util.spec_from_file_location("gimp_utils", gimp_utils_import_path)
GimpUtils = importlib.util.module_from_spec(gimp_utils_spec)
gimp_utils_spec.loader.exec_module(GimpUtils)

# ***********************************************
#           GIMP Generate Dialog and Procedure
# ***********************************************
class MainProcedureDialog(GimpUi.ProcedureDialog):
    def __init__(self, procedure, config, previous_inputs):
        super().__init__(procedure=procedure, config=config)
        self.set_default_size(700, 700)
        self.history_manager = HistoryManager()
        self.favorites_manager = FavoritesManager()

        # Apply CSS
        self.apply_css()

        # Get the main content area of the ProcedureDialog
        content_area = self.get_content_area()
        content_area.get_style_context().add_class("content_area")

        # Create a scrolled window for the entire dialog
        scrolled_window = self.create_scrolled_window("content_scrolled_window", Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC, 400, 300)

        # Create a container (VBox) to hold all UI elements inside the scroll area
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content_box.set_border_width(10)
        content_box.get_style_context().add_class("content_box")

        # Positive Prompt
        self.positive_textview = self.add_labeled_textview(content_box, "Positive Prompt", previous_inputs.get("positive_generate_prompt", ""))
        # Negative Prompt
        self.negative_textview = self.add_labeled_textview(content_box, "Negative Prompt", previous_inputs.get("negative_generate_prompt", ""))

        # Action buttons
        action_buttons_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        # History Button
        self.history_button = Gtk.Button.new_with_label("Prompt History")
        self.history_button.connect("clicked", self.on_reveal_history_clicked)
        action_buttons_hbox.pack_start(self.history_button, False, False, 0)
        self.update_history_button_sensitivity()

        # Favorites Button
        add_favorite_button = Gtk.Button(label="Add Favorite Workflow")
        add_favorite_button.set_tooltip_text("Add one or more .json workflow files to your favorites.")
        add_favorite_button.connect("clicked", self.on_add_favorite_clicked)
        action_buttons_hbox.pack_end(add_favorite_button, False, False, 0)

        content_box.pack_start(action_buttons_hbox, False, False, 10)

        workflow_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        workflow_label = Gtk.Label(label="Workflow", xalign=0)
        self.workflow_combo = Gtk.ComboBoxText()
        workflow_box.pack_start(workflow_label, False, False, 0)
        workflow_box.pack_start(self.workflow_combo, False, False, 0)
        
        # Populate the dropdown from favorites.json
        self.populate_workflows_dropdown()

        self.workflow_combo.connect("changed", self.on_workflow_selected)
        content_box.pack_start(workflow_box, False, False, 10)

        # Populate GIMP's default argument UI elements
        self.fill(None)

        child_list = content_area.get_children()
        ksampler_children = []
        for idx, child in enumerate(child_list):
            if idx == len(child_list) - 1 or idx == len(child_list) - 2: # Don't remove the last two children (buttons)
                continue
            content_area.remove(child) # Remove Children
            if idx < 4: # Skip adding the first 4 children (steps, cfg, sampler, scheduler)
                ksampler_children.append(child)
                continue
            content_box.pack_start(child, False, False, 5) # Repack Children

        # Add the KSampler children into an expandable section
        self.ksampler_section = self.add_expandable_section(content_box, "KSampler Settings", "ksampler", ksampler_children, None)

        # Expandable Icon Views
        try:
            self.checkpoints_view = self.add_expandable_section(content_box, "Checkpoints", "icon_view", [], Gtk.SelectionMode.SINGLE)
            self.loras_view = self.add_expandable_section(content_box, "Loras", "icon_view", [], Gtk.SelectionMode.MULTIPLE)
            self.initialize_icon_view_from_config("Checkpoints")
            self.initialize_icon_view_from_config("Loras")
        except Exception as e:
            print(f"Error creating expandable sections: {e}")

        # Add the box inside the scrolled window
        scrolled_window.add(content_box)

        # Add the scrolled window into the GimpUi dialog
        content_area.pack_start(scrolled_window, True, True, 0)

        self.show_all()

    def populate_workflows_dropdown(self):
        """Loads favorites and populates the workflow ComboBox."""
        favorites_data = self.favorites_manager.load_favorites()
        
        # Add each favorite from the JSON file
        for fav in favorites_data.get("favorites", []):
            # The ID is the path, the visible text is the title
            self.workflow_combo.append(fav['path'], fav['title'])
        
        if not favorites_data.get("favorites"):
            self.workflow_combo.append(None, "Select a Favorite Workflow...")

        self.workflow_combo.set_active(0)
        self.selected_workflow_path = self.workflow_combo.get_active_id()
    
    def on_workflow_selected(self, combo):
        """
        Handles the selection of a workflow from the dropdown.
        Stores the selected workflow's file path.
        """
        self.selected_workflow_path = combo.get_active_id()

    def on_add_favorite_clicked(self, widget):
        """Opens a file chooser to select and add favorite JSON workflows."""
        dialog = Gtk.FileChooserDialog(
            title="Please choose one or more workflow files",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK,
        )
        dialog.set_select_multiple(True)

        # Show only JSON files
        json_filter = Gtk.FileFilter()
        json_filter.set_name("JSON files (*.json)")
        json_filter.add_pattern("*.json")
        dialog.add_filter(json_filter)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            file_paths = dialog.get_filenames()
            added_count = self.favorites_manager.add_favorites(file_paths)
            
            info_dialog = Gtk.MessageDialog(
                transient_for=self,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text=f"Added {added_count} new favorite(s).",
            )
            skipped_count = len(file_paths) - added_count
            if skipped_count > 0:
                info_dialog.format_secondary_text(
                    f"{skipped_count} file(s) were skipped (already a favorite or not a .json file)."
                )
            if added_count > 0:
                self.workflow_combo.remove_all()
                self.populate_workflows_dropdown()
            
            info_dialog.run()
            info_dialog.destroy()

        dialog.destroy()

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

    def apply_css(self):
        css = """
            .content_box {
                padding-left: 30px;
                padding-right: 30px;
            }
            textview {
                min-height: 100px;
            }
            .textview_box {
                margin-top: 1rem;
                min-height: 100px;
            }
            .textview_scrolled_window {
                min-height: 100px;
            }
            .expander {
                margin-bottom: 25px;
            }
            
        """
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(css.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def create_scrolled_window(self, item_class, horizontal_scroll, vertical_scroll, requested_width=400, requested_height=300):
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(horizontal_scroll, vertical_scroll)
        scrolled_window.set_size_request(requested_width, requested_height)
        scrolled_window.get_style_context().add_class(item_class)
        return scrolled_window

    def add_labeled_textview(self, parent, label_text, default_value=""):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            box.get_style_context().add_class("textview_box")

            label = Gtk.Label(label=label_text)

            scrolled_window = self.create_scrolled_window("textview_scrolled_window", Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC, 0, 0)

            textview = Gtk.TextView()
            textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)  # ensure horizontal wrapping
            textview.get_style_context().add_class("textview_text")

            # Set default text
            buffer = textview.get_buffer()
            buffer.set_text(default_value)

            scrolled_window.add(textview)

            box.pack_start(label, False, False, 0)
            box.pack_start(scrolled_window, False, False, 0)
            parent.pack_start(box, False, False, 0)

            return textview

    def add_expandable_section(self, parent, title, sub_window, data, aux_data, width=400, height=300):
        expander = Gtk.Expander(label=title)
        expander.get_style_context().add_class("expander")

        if sub_window == "icon_view":
            # Main container
            container_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)

            button_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            button_hbox.set_margin_top(5)
            
            file_dir_button = Gtk.Button(label="Set Models Folder")
            icon_dir_button = Gtk.Button(label="Set Icons Folder")

            # Connect signals, passing the 'title' to identify the section (e.g., "Checkpoints")
            file_dir_button.connect("clicked", self.on_set_folder_clicked, title, "models")
            icon_dir_button.connect("clicked", self.on_set_folder_clicked, title, "icons")

            button_hbox.pack_start(file_dir_button, False, False, 0)
            button_hbox.pack_start(icon_dir_button, False, False, 0)
            container_box.pack_start(button_hbox, False, False, 0)

            # Create the icon view and get its data
            icon_view, list_store = self.create_icon_view(data, aux_data)
            
            if not hasattr(self, 'icon_view_models'):
                self.icon_view_models = {}
            self.icon_view_models[title] = list_store
            
            scrolled_window = self.create_scrolled_window("expander_scrolled_window", Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC, width, height)
            scrolled_window.add(icon_view)
            container_box.pack_start(scrolled_window, True, True, 0)
            
            expander.add(container_box)
            window_content = icon_view

        elif sub_window == "ksampler":
            window_content = self.create_ksampler_section(data)
            expander.add(window_content)
        
        parent.pack_start(expander, False, False, 0)
        return window_content

    def create_icon_view(self, icon_data, selection_mode, item_class="icon_view"):
        """Creates an IconView with a model that stores the full file path."""
        list_store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str)

        self.populate_icon_view_model(list_store, icon_data)

        icon_view = Gtk.IconView.new_with_model(list_store)
        icon_view.get_style_context().add_class(item_class)
        icon_view.set_selection_mode(selection_mode)
        
        icon_view.set_pixbuf_column(0)
        icon_view.set_text_column(1)
        icon_view.set_item_width(80)

        return icon_view, list_store

    def populate_icon_view_model(self, list_store, icon_data):
        """Fills a ListStore with icon, name, and the full file path."""
        list_store.clear()
        for item in icon_data:
            pixbuf = None
            try:
                if item.get("icon") and os.path.exists(item["icon"]):
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(item["icon"], 128, 128)
            except Exception:
                pixbuf = None
            
            if not pixbuf:
                pass
                # Optionally create a placeholder pixbuf if no icon is found
                # pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 128, 128)
                # pixbuf.fill(0xD3D3D3FF)

            model_name_no_ext = os.path.splitext(os.path.basename(item["file"]))[0]
            list_store.append([pixbuf, model_name_no_ext, item["file"]])

    def initialize_icon_view_from_config(self, section_title):
        """Checks the config file for paths and populates the IconView if found."""
        last_inputs = GimpUtils.load_json_file(last_inputs_file_path)
        
        key_base = section_title.lower()
        model_key = f"{key_base}_models_folder"
        icon_key = f"{key_base}_icons_folder"

        model_dir = last_inputs.get(model_key)
        icon_dir = last_inputs.get(icon_key)

        if model_dir and os.path.isdir(model_dir):
            print(f"Found saved path for '{section_title}' models: {model_dir}")
            
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
            GimpUtils.update_json_file(data_to_save, last_inputs_file_path)
            print(f"Saved '{json_key}' to '{last_inputs_file_path}'")
            
            # Rescan and update of the corresponding icon view
            self.rescan_and_update_icon_view(section_title)

        dialog.destroy()

    def rescan_and_update_icon_view(self, section_title):
        paths = self.custom_paths.get(section_title, {})
        model_dir = paths.get('models')
        icon_dir = paths.get('icons')
        
        if not model_dir:
            print(f"Model directory for '{section_title}' has not been set.")
            return

        print(f"Rescanning '{section_title}'... Models: '{model_dir}', Icons: '{icon_dir}'")
        new_data = self.scan_directory_for_items(model_dir, icon_dir)
        
        list_store = self.icon_view_models.get(section_title)
        if list_store:
            self.populate_icon_view_model(list_store, new_data)

    def scan_directory_for_items(self, model_dir, icon_dir=None):
        supported_model_exts = ['.safetensors', '.ckpt', '.pt']
        supported_icon_exts = ['.png', '.jpg', '.jpeg', '.webp']
        items = []

        if not os.path.isdir(model_dir):
            return []

        for filename in os.listdir(model_dir):
            if any(filename.lower().endswith(ext) for ext in supported_model_exts):
                model_path = os.path.join(model_dir, filename)
                item = {"file": model_path, "icon": None}
                
                # If an icon directory is provided, search for a matching icon
                if icon_dir and os.path.isdir(icon_dir):
                    model_name_base = os.path.splitext(filename)[0]
                    for icon_ext in supported_icon_exts:
                        potential_icon_path = os.path.join(icon_dir, model_name_base + icon_ext)
                        if os.path.exists(potential_icon_path):
                            item["icon"] = potential_icon_path
                            break # Found a matching icon
                items.append(item)
                
        return items
    
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

        for item_path in selected_items:
            tree_iter = model.get_iter(item_path)
            file_path = model.get_value(tree_iter, 2)
            file_name = os.path.basename(file_path)
            
        return file_name

    def get_selected_lora_data(self, icon_view):
        """
        Returns a list of file names (not full paths) for selected items in an IconView.
        """
        names = []
        model = icon_view.get_model()
        selected_items = icon_view.get_selected_items()

        for item_path in selected_items:
            tree_iter = model.get_iter(item_path)
            file_path = model.get_value(tree_iter, 2)
            file_name = os.path.basename(file_path)
            names.append(file_name)
            
        return names

# ***********************************************
#           Lora Dialog and Procedure
# ***********************************************
class LoraDialog(GimpUi.ProcedureDialog):
    def __init__(self, procedure, config, lora_selection):
        super().__init__(procedure=procedure, config=config)
        self.set_default_size(700, 200)

        # Get the main content area of the ProcedureDialog
        content_area = self.get_content_area()
        content_area.get_style_context().add_class("content_area")

        # Create a scrolled window for the entire dialog
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_size_request(400, 300)  # Adjust dialog size

        # Create a container (VBox) to hold all UI elements inside the scroll area
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content_box.set_border_width(10)
        content_box.get_style_context().add_class("content_box")

        # Populate GIMP's default argument UI elements
        self.fill(None)

        for child in content_area.get_children():
            if child.get_name() == "GtkBox":
                continue
            content_area.remove(child)  # Remove them

        try:
            self.lora_box = self.create_lora_box(content_box, lora_selection)
        except:
            pass

        # Add the box inside the scrolled window
        scrolled_window.add(content_box)

        # Add the scrolled window into the GimpUi dialog
        content_area.pack_start(scrolled_window, True, True, 0)

        self.show_all()

    def create_lora_box(self, parent, lora_selection):
        lora_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        lora_box.get_style_context().add_class("lora_box")

        for lora_file_path in lora_selection:
            lora_name = os.path.basename(lora_file_path)

            lora_label = Gtk.Label(label=lora_name)

            # Create a double spinner for the Lora weight
            adjustment = Gtk.Adjustment(value=1, lower=-5, upper=5, step_increment=0.01, page_increment=0.1, page_size=0)
            lora_spinner = Gtk.SpinButton(adjustment=adjustment, climb_rate=0.01, digits=2)
            lora_spinner.set_numeric(True)

            lora_box.pack_start(lora_label, False, False, 0)
            lora_box.pack_start(lora_spinner, False, False, 0)
            parent.pack_start(lora_box, False, False, 0)
        return lora_box
    
    def get_lora_dict(self):
        lora_dict = {}
        children = self.lora_box.get_children()
        for i in range(0, len(children), 2):
            lora_name = children[i].get_text()
            lora_weight = children[i + 1].get_value()
            lora_dict[lora_name] = lora_weight
        return lora_dict

##########################################################################
# Favorites Management Class
##########################################################################
class FavoritesManager:
    """Manages adding and storing favorite workflow files."""
    def __init__(self):
        pass

    def load_favorites(self):
        """Loads the favorites data from the JSON file."""
        if not os.path.exists(favorites_json_path):
            return {"favorites": []}
        try:
            with open(favorites_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Ensure the root "favorites" key with a list exists
                if "favorites" not in data or not isinstance(data.get("favorites"), list):
                    return {"favorites": []}
                return data
        except (json.JSONDecodeError, IOError):
            return {"favorites": []}

    def save_favorites(self, data):
        """Saves the favorites data to the JSON file."""
        try:
            with open(favorites_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except IOError as e:
            print(f"Error saving favorites: {e}")

    def add_favorites(self, file_paths_to_add):
        """Adds a list of file paths to favorites, checking for JSON and duplicates."""
        favorites_data = self.load_favorites()
        # Create a set of existing paths for duplicate checking
        existing_paths = {fav['path'] for fav in favorites_data.get("favorites", [])}
        added_count = 0

        for path in file_paths_to_add:
            if path.lower().endswith('.json') and path not in existing_paths:
                title = os.path.basename(path)[:-5] # Get filename without .json
                new_entry = {"path": path, "title": title}
                favorites_data["favorites"].append(new_entry)
                existing_paths.add(path)
                added_count += 1
        
        if added_count > 0:
            self.save_favorites(favorites_data)
        
        return added_count
    
##########################################################################
# History Management Class
##########################################################################
class HistoryManager:
    """Manages storing, retrieving, and deleting prompt history."""
    def __init__(self):
        self.history_path = os.path.join(comfy_dir, 'History')
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
            "Select", Gtk.ResponseType.OK,
            "Close", Gtk.ResponseType.CLOSE
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