#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Manages prompt history storage and provides a Gtk Dialog for selection
"""

import json
from pathlib import Path
from typing import List, Dict, Optional

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango

import config

# Constants
HISTORY_FILE_NAME = "prompt_history.json"
MAX_ENTRIES = 50  # Prevent infinite growth
TRUNCATE_LEN = 80 # Character limit for list view preview

class HistoryManager:
    """
    Backend logic for persisting generation prompts
    Enforces a MRU (Most Recently Used) list with a hard limit
    """
    
    def __init__(self):
        self.path = Path(config.settings.comfy_dir) / 'History' / HISTORY_FILE_NAME
        self._ensure_dir()

    def _ensure_dir(self):
        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> List[Dict[str, str]]:
        """
        Loads history from disk
        Returns empty list on failure
        """
        if not self.path.exists():
            return []
        try:
            with self.path.open('r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError):
            return []

    def save(self, data: List[Dict[str, str]]):
        """Persists the list to disk"""
        try:
            with self.path.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except IOError as e:
            print(f"[HistoryManager] Save failed: {e}")

    def add_entry(self, pos: str, neg: str):
        """
        Adds an entry to the top of the history
        If entry exists, moves it to the top (Bubble up)
        """
        if not pos and not neg:
            return

        history = self.load()
        new_entry = {"positive": pos, "negative": neg}

        # Remove existing to avoid duplicates and bubble to top
        history = [item for item in history if item != new_entry]
        
        # Insert at top
        history.insert(0, new_entry)
        
        # Enforce max size
        if len(history) > MAX_ENTRIES:
            history = history[:MAX_ENTRIES]

        self.save(history)

    def delete_entry(self, entry: Dict[str, str]):
        """Removes a specific entry"""
        history = self.load()
        history = [x for x in history if x != entry]
        self.save(history)


class HistoryDialog(Gtk.Dialog):
    """
    Dialog displaying prompt history
    """

    def __init__(self, parent: Gtk.Window, manager: HistoryManager):
        super().__init__(title="Prompt History", transient_for=parent, flags=0)
        self.manager = manager
        self.selected_entry: Optional[Dict[str, str]] = None
        
        self.set_default_size(650, 450)
        self.set_border_width(10)
        
        self._init_ui()
        self._populate_list()
        
        self.show_all()

    def _init_ui(self):
        # Main Layout
        content_area = self.get_content_area()
        content_area.set_spacing(10)

        # Instructions / Header
        header = Gtk.Label(label="Select a previously used prompt to load it:", xalign=0)
        header.get_style_context().add_class("dim-label")
        content_area.pack_start(header, False, False, 5)

        # Scrolled Window
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        scroller.set_min_content_height(300)
        
        # ListBox
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.set_activate_on_single_click(True)
        self.listbox.connect("row-activated", self._on_row_activated)
        scroller.add(self.listbox)
        
        content_area.pack_start(scroller, True, True, 0)

        # Action Buttons
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)

    def _populate_list(self):
        """Fetches data and builds UI rows."""
        entries = self.manager.load()
        
        # Clear existing
        for child in self.listbox.get_children():
            self.listbox.remove(child)

        if not entries:
            self._show_empty_state()
            return

        for entry in entries:
            row = self._create_row(entry)
            self.listbox.add(row)

    def _create_row(self, entry: Dict[str, str]) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.data = entry

        # Setup Tooltip (Full Text)
        full_pos = GLib.markup_escape_text(entry.get('positive', ''))
        full_neg = GLib.markup_escape_text(entry.get('negative', ''))
        tooltip_markup = (
            f"<b>Positive:</b> {full_pos}\n"
            f"<b>Negative:</b> {full_neg}"
        )
        row.set_tooltip_markup(tooltip_markup)

        # Container
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
        hbox.set_margin_top(8)
        hbox.set_margin_bottom(8)
        hbox.set_margin_start(10)
        hbox.set_margin_end(10)

        # Text Column
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        
        # Format strings for display (Truncated)
        pos_display = self._truncate(entry.get('positive', ''))
        neg_display = self._truncate(entry.get('negative', ''))
        
        # Pango Markup for coloring (Green for pos, Red/Gray for neg)
        markup = (
            f"<span foreground='#2e8b57' weight='bold'>+</span> {GLib.markup_escape_text(pos_display)}\n"
            f"<span foreground='#c0392b' weight='bold'>-</span> <span size='small' alpha='80%'>{GLib.markup_escape_text(neg_display)}</span>"
        )
        
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(markup)
        
        # Use Pango for proper ellipsization
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        
        vbox.pack_start(lbl, True, True, 0)
        hbox.pack_start(vbox, True, True, 0)

        # Delete Button
        btn_del = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
        btn_del.set_relief(Gtk.ReliefStyle.NONE)
        btn_del.set_tooltip_text("Delete from history")
        btn_del.connect("clicked", self._on_delete_clicked, row)
        
        hbox.pack_start(btn_del, False, False, 0)

        row.add(hbox)
        return row

    def _show_empty_state(self):
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        lbl = Gtk.Label(label="No history available.")
        lbl.set_opacity(0.5)
        lbl.set_margin_top(20)
        lbl.set_margin_bottom(20)
        row.add(lbl)
        self.listbox.add(row)

    def _truncate(self, text: str) -> str:
        if not text: return "None"
        clean = text.replace("\n", " ")
        return (clean[:TRUNCATE_LEN] + '...') if len(clean) > TRUNCATE_LEN else clean

    # --- Events ---

    def _on_row_activated(self, listbox, row):
        """Instant selection: Set data and close dialog with OK response"""
        if row and hasattr(row, 'data'):
            self.selected_entry = row.data
            self.response(Gtk.ResponseType.OK)

    def _on_delete_clicked(self, button, row):
        # Prevent row activation logic when clicking delete
        self.listbox.select_row(row)
        
        self.manager.delete_entry(row.data)
        self.listbox.remove(row)
        
        self.selected_entry = None

        if not self.listbox.get_children():
            self._show_empty_state()

    def get_selected_entry(self) -> Optional[Dict[str, str]]:
        return self.selected_entry