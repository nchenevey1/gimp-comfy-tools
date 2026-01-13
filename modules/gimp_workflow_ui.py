#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Manages the storage and UI interaction for ComfyUI workflow JSON files
Includes the WorkflowManager backend and the WorkflowDialog frontend
"""

import os
from typing import List, Dict, Optional
from gi.repository import Gtk, GLib

import config
import gimp_utils as GimpUtils


class WorkflowManager:
    """
    Backend logic for loading, saving, and managing workflow references
    Data is persisted to a JSON file defined in config
    """

    def __init__(self):
        self.file_path = config.settings.workflows_json_path

    def load_workflows(self) -> Dict[str, List[Dict[str, str]]]:
        """Loads the workflow registry from disk"""
        if not os.path.exists(self.file_path):
            return {"workflows": []}
        
        return GimpUtils.load_json(self.file_path)

    def save_workflows(self, data: Dict[str, List[Dict[str, str]]]) -> bool:
        """Persists the workflow registry to disk"""
        return GimpUtils.save_json(data, self.file_path)

    def add_workflows(self, paths: List[str]) -> int:
        """
        Registers new workflow files
        Returns:
            int: The number of new workflows successfully added
        """
        data = self.load_workflows()
        existing_paths = {w['path'] for w in data.get("workflows", [])}
        count = 0

        for path in paths:
            if not path.lower().endswith('.json'):
                continue
            
            # Normalize path to ensure consistency
            clean_path = os.path.abspath(path)
            
            if clean_path not in existing_paths:
                title = os.path.splitext(os.path.basename(clean_path))[0]
                
                data.setdefault("workflows", []).append({
                    "path": clean_path, 
                    "title": title
                })
                existing_paths.add(clean_path)
                count += 1

        if count > 0:
            self.save_workflows(data)
            
        return count

    def delete_workflow(self, path_to_remove: str) -> bool:
        """Removes a workflow from the registry"""
        data = self.load_workflows()
        original_list = data.get("workflows", [])
        
        new_list = [w for w in original_list if w['path'] != path_to_remove]
        
        if len(new_list) < len(original_list):
            data["workflows"] = new_list
            self.save_workflows(data)
            return True
            
        return False


class WorkflowDialog(Gtk.Dialog):
    """
    A dialog for managing the list of available workflows
    Allows adding new JSON files, deleting existing ones, and selecting a workflow
    """

    def __init__(self, parent: Gtk.Window, manager: WorkflowManager):
        super().__init__(title="Manage Workflows", transient_for=parent, flags=0)
        self.manager = manager
        self.selected_workflow: Optional[Dict] = None
        
        self.set_default_size(500, 600)
        self.set_border_width(10)

        self._init_ui()
        self._load_data()

    def _init_ui(self):
        """Initializes the UI components"""
        content_area = self.get_content_area()
        content_area.set_spacing(10)

        # --- Toolbar (Search & Add) ---
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        # Search Entry
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search workflows...")
        self.search_entry.connect("search-changed", self._on_search_changed)
        toolbar.pack_start(self.search_entry, True, True, 0)
        
        content_area.pack_start(toolbar, False, False, 0)

        # --- List View ---
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        scrolled_window.set_min_content_height(300)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.set_filter_func(self._filter_rows)
        self.listbox.connect("row-activated", self._on_row_activated)
        
        scrolled_window.add(self.listbox)
        content_area.pack_start(scrolled_window, True, True, 0)

        # --- Action Buttons ---
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        
        btn_add = Gtk.Button(label="Import JSON...")
        btn_add.get_style_context().add_class("suggested-action")
        btn_add.connect("clicked", lambda b: self.response(Gtk.ResponseType.APPLY))
        
        action_area = self.get_action_area()
        action_area.pack_start(btn_add, False, False, 0)
        btn_add.show()

        self.btn_select = self.add_button("Select", Gtk.ResponseType.OK)
        self.btn_select.set_sensitive(False) # Disabled until selection made
        self.btn_select.get_style_context().add_class("suggested-action")

        self.show_all()

    def _load_data(self):
        """Populates the listbox with data from the manager"""
        # Clear existing
        for child in self.listbox.get_children():
            self.listbox.remove(child)

        data = self.manager.load_workflows()
        workflows = data.get("workflows", [])

        if not workflows:
            self._show_empty_state()
            return

        for wf in workflows:
            row = self._create_row(wf)
            self.listbox.add(row)
        
        self.listbox.show_all()

    def _create_row(self, workflow_data: Dict) -> Gtk.ListBoxRow:
        """Creates a styled list row for a workflow item"""
        row = Gtk.ListBoxRow()
        row.data = workflow_data
        
        # Main container
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        hbox.set_margin_top(8)
        hbox.set_margin_bottom(8)
        hbox.set_margin_start(10)
        hbox.set_margin_end(10)

        # Icon
        icon = Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.LARGE_TOOLBAR)
        icon.set_opacity(0.6)
        hbox.pack_start(icon, False, False, 0)

        # Text Container
        vbox_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        
        # Title
        lbl_title = Gtk.Label(label=workflow_data['title'], xalign=0)
        lbl_title.get_style_context().add_class("title-label") # Custom class hooks if needed
        markup = f"<b>{GLib.markup_escape_text(workflow_data['title'])}</b>"
        lbl_title.set_markup(markup)
        vbox_text.pack_start(lbl_title, True, True, 0)

        # Path (Subtitle)
        lbl_path = Gtk.Label(label=workflow_data['path'], xalign=0)
        lbl_path.set_ellipsize(3) # END
        lbl_path.get_style_context().add_class("dim-label")
        lbl_path.set_opacity(0.5)
        lbl_path.set_max_width_chars(50)
        vbox_text.pack_start(lbl_path, False, False, 0)

        hbox.pack_start(vbox_text, True, True, 0)

        # Delete Button
        btn_del = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
        btn_del.set_relief(Gtk.ReliefStyle.NONE)
        btn_del.set_tooltip_text("Remove from list")
        btn_del.connect("clicked", self._on_delete_clicked, row)
        hbox.pack_start(btn_del, False, False, 0)

        row.add(hbox)
        return row

    def _show_empty_state(self):
        """Displays a placeholder when no workflows exist"""
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        lbl = Gtk.Label(label="No workflows found.\nClick 'Import JSON' to add one.")
        lbl.set_justify(Gtk.Justification.CENTER)
        lbl.set_margin_top(40)
        lbl.set_margin_bottom(40)
        lbl.set_opacity(0.5)
        row.add(lbl)
        self.listbox.add(row)
        self.listbox.show_all()

    # --- Event Handlers ---

    def _on_row_activated(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow):
        """Handles row selection"""
        if row and hasattr(row, 'data'):
            self.selected_workflow = row.data
            self.btn_select.set_sensitive(True)
        else:
            self.btn_select.set_sensitive(False)

    def _on_delete_clicked(self, button: Gtk.Button, row: Gtk.ListBoxRow):
        """Handles deletion with confirmation"""
        # Prevent row activation when clicking delete
        self.listbox.select_row(row)
        
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Remove Workflow?"
        )
        dialog.format_secondary_text(
            f"Are you sure you want to remove '{row.data['title']}' from the list?\n"
            "The actual file will not be deleted."
        )
        
        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.OK:
            if self.manager.delete_workflow(row.data['path']):
                self.listbox.remove(row)
                # Re-check for empty state
                if len(self.listbox.get_children()) == 0:
                    self._show_empty_state()

    def _on_search_changed(self, entry):
        """Trigger filtering when search text changes"""
        self.listbox.invalidate_filter()

    def _filter_rows(self, row: Gtk.ListBoxRow) -> bool:
        """Filters rows based on the search entry text"""
        # Always show non-data rows (like empty state msg)
        if not hasattr(row, 'data'):
            return True
            
        query = self.search_entry.get_text().lower()
        if not query:
            return True
            
        title = row.data.get('title', '').lower()
        path = row.data.get('path', '').lower()
        
        return query in title or query in path

    # --- Public API ---

    def get_selected_workflow(self) -> Optional[Dict]:
        """Returns the selected workflow data dictionary"""
        return self.selected_workflow

    def run_file_chooser(self):
        """Opens a native file chooser to import JSON workflows"""
        dialog = Gtk.FileChooserDialog(
            title="Import Workflow JSON",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK,
        )
        dialog.set_select_multiple(True)

        # File Filter
        json_filter = Gtk.FileFilter()
        json_filter.set_name("JSON Workflows (*.json)")
        json_filter.add_pattern("*.json")
        dialog.add_filter(json_filter)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            paths = dialog.get_filenames()
            count = self.manager.add_workflows(paths)
            if count > 0:
                self._load_data() # Refresh list
        
        dialog.destroy()