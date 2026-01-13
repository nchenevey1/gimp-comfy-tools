#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UI components for the ComfyUI Plugin
Includes widgets for Samplers, LoRAs, Prompts, and Style browsing
"""

import os
import json
import threading
from typing import Dict, Any, List, Optional, Callable

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, Gtk, GdkPixbuf

# Local Imports
import config
import gimp_utils as GimpUtils
from gimp_history import HistoryDialog, HistoryManager

# -------------------------------------------------------------------
#                           UI Factory
# -------------------------------------------------------------------

class UIFactory:
    """
    Factory for creating consistent, styled Gtk widgets
    """

    @staticmethod
    def create_spin_row(
        grid: Gtk.Grid, 
        row_idx: int, 
        label_text: str, 
        value: float, 
        lower: float, 
        upper: float, 
        step: float = 1.0, 
        digits: int = 0, 
        tooltip: str = None
    ) -> Gtk.SpinButton:
        """Creates a labeled SpinButton row attached to a Grid"""
        label = Gtk.Label(label=label_text)
        label.set_halign(Gtk.Align.END)
        label.set_valign(Gtk.Align.CENTER)
        
        if tooltip:
            label.set_tooltip_text(tooltip)

        adj = Gtk.Adjustment(
            value=value, 
            lower=lower, 
            upper=upper, 
            step_increment=step, 
            page_increment=step * 10, 
            page_size=0
        )
        spin = Gtk.SpinButton(adjustment=adj, climb_rate=step, digits=digits)
        spin.set_hexpand(True)
        spin.set_valign(Gtk.Align.CENTER)
        
        if tooltip:
            spin.set_tooltip_text(tooltip)

        grid.attach(label, 0, row_idx, 1, 1)
        grid.attach(spin, 1, row_idx, 1, 1)
        return spin

    @staticmethod
    def create_combo_row(
        grid: Gtk.Grid, 
        row_idx: int, 
        label_text: str, 
        options: List[str], 
        default_val: str,
        tooltip: str = None
    ) -> Gtk.ComboBoxText:
        """Creates a labeled ComboBoxText row attached to a Grid"""
        label = Gtk.Label(label=label_text)
        label.set_halign(Gtk.Align.END)
        label.set_valign(Gtk.Align.CENTER)

        if tooltip:
            label.set_tooltip_text(tooltip)
        
        combo = Gtk.ComboBoxText()
        for opt in options:
            combo.append_text(str(opt))
        
        # Set active
        if default_val in options:
            combo.set_active(options.index(default_val))
        elif len(options) > 0:
            combo.set_active(0)
        
        combo.set_hexpand(True)
        
        grid.attach(label, 0, row_idx, 1, 1)
        grid.attach(combo, 1, row_idx, 1, 1)
        return combo


# -------------------------------------------------------------------
#                        KSampler Widget
# -------------------------------------------------------------------

class KSamplerWidget(Gtk.Box):
    """
    Widget containing primary generation parameters:
    Steps, CFG, Sampler, Scheduler, Seed, Denoise, and Dimensions
    """

    def __init__(self, previous_inputs: Dict[str, Any], client=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_margin_top(10)
        self.client = client
        
        # Layout Grid
        self.grid = Gtk.Grid()
        self.grid.set_column_spacing(12)
        self.grid.set_row_spacing(10)
        self.pack_start(self.grid, True, True, 0)

        # Initialize Options (Remote or Default)
        self._samplers = config.settings.SAMPLERS
        self._schedulers = config.settings.SCHEDULERS
        self._fetch_remote_options()

        # Build Controls
        self._build_ui(previous_inputs)

    def _fetch_remote_options(self):
        """Attempts to fetch updated lists from the ComfyUI client"""
        if self.client and self.client.is_reachable():
            try:
                remote_samplers = self.client.get_available_samplers()
                if remote_samplers: 
                    self._samplers = remote_samplers
                
                remote_schedulers = self.client.get_available_schedulers()
                if remote_schedulers: 
                    self._schedulers = remote_schedulers
            except Exception:
                pass # Silently fail back to config defaults

    def _build_ui(self, inputs: Dict[str, Any]):
        # Sampling
        self.steps = UIFactory.create_spin_row(
            self.grid, 0, "Steps", 
            inputs.get("steps", 20), 1, 200, 1, 0, "Number of sampling steps"
        )
        self.cfg = UIFactory.create_spin_row(
            self.grid, 1, "CFG Scale", 
            inputs.get("cfg", 8.0), 1.0, 30.0, 0.5, 1, "Classifier Free Guidance scale"
        )

        # Algorithms
        self.sampler = UIFactory.create_combo_row(
            self.grid, 2, "Sampler", 
            self._samplers, inputs.get("sampler", self._samplers[0])
        )
        self.scheduler = UIFactory.create_combo_row(
            self.grid, 3, "Scheduler", 
            self._schedulers, inputs.get("scheduler", self._schedulers[0])
        )

        # Variations
        self.seed = UIFactory.create_spin_row(
            self.grid, 4, "Seed", 
            inputs.get("seed", -1), -1, 2**32, 1, 0, "Set to -1 for random seed"
        )
        self.denoise = UIFactory.create_spin_row(
            self.grid, 5, "Denoise", 
            inputs.get("denoise_strength", 1.0), 0.0, 1.0, 0.05, 2, "Image-to-Image strength"
        )

        # Dimensions
        w, h = self._resolve_dimensions(inputs)
        self.width = UIFactory.create_spin_row(self.grid, 6, "Width", w, 64, 8192, 64)
        self.height = UIFactory.create_spin_row(self.grid, 7, "Height", h, 64, 8192, 64)

    def _resolve_dimensions(self, inputs: Dict[str, Any]):
        """Defaults to current image size if available, else 512x512"""
        w, h = inputs.get("width", 512), inputs.get("height", 512)
        return w, h

    def get_settings(self) -> Dict[str, Any]:
        return {
            "steps": self.steps.get_value_as_int(),
            "cfg": round(self.cfg.get_value(), 2),
            "sampler": self.sampler.get_active_text(),
            "scheduler": self.scheduler.get_active_text(),
            "seed": int(self.seed.get_value()),
            "denoise_strength": round(self.denoise.get_value(), 2),
            "width": self.width.get_value_as_int(),
            "height": self.height.get_value_as_int()
        }
    
    def set_settings(self, data: Dict[str, Any]):
        """Programmatically updates UI values"""
        if "steps" in data: self.steps.set_value(data["steps"])
        if "cfg" in data: self.cfg.set_value(data["cfg"])
        if "seed" in data: self.seed.set_value(data["seed"])
        if "denoise_strength" in data: self.denoise.set_value(data["denoise_strength"])
        if "width" in data: self.width.set_value(data["width"])
        if "height" in data: self.height.set_value(data["height"])
        
        if "sampler" in data: self._set_active_text(self.sampler, data["sampler"])
        if "scheduler" in data: self._set_active_text(self.scheduler, data["scheduler"])

    def _set_active_text(self, combo: Gtk.ComboBoxText, text: str):
        for row in combo.get_model():
            if row[0] == text:
                combo.set_active_iter(row.iter)
                break


# -------------------------------------------------------------------
#                     Resource Gallery Widget
# -------------------------------------------------------------------

class ResourceGalleryWidget(Gtk.Box):
    """
    Gallery view for selecting Models/LoRAs
    Features async fetching and local icon mapping
    """
    
    # Store Columns: [Pixbuf, DisplayName, FullFilename]
    COL_PIX = 0
    COL_NAME = 1
    COL_FILE = 2

    def __init__(self, title: str, selection_mode: Gtk.SelectionMode, client, callback: Callable = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.title = title
        self.client = client
        self.callback = callback
        self.model_store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str)

        self._build_toolbar()
        self._build_view(selection_mode)
        
        # Initial Fetch
        self.refresh_gallery()

    def _build_toolbar(self):
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        
        btn_icons = Gtk.Button(label="Set Icons Folder")
        btn_icons.set_tooltip_text("Select a local folder containing thumbnails matching model names.")
        btn_icons.connect("clicked", self.on_set_icon_folder)
        
        btn_refresh = Gtk.Button.new_from_icon_name("view-refresh", Gtk.IconSize.BUTTON)
        btn_refresh.set_tooltip_text("Refresh list from ComfyUI Server")
        btn_refresh.connect("clicked", lambda b: self.refresh_gallery())

        toolbar.pack_start(btn_icons, True, True, 0)
        toolbar.pack_start(btn_refresh, False, False, 0)
        self.pack_start(toolbar, False, False, 0)

    def _build_view(self, mode):
        self.icon_view = Gtk.IconView.new_with_model(self.model_store)
        self.icon_view.set_selection_mode(mode)
        self.icon_view.set_pixbuf_column(self.COL_PIX)
        self.icon_view.set_text_column(self.COL_NAME)
        self.icon_view.set_item_width(85)
        self.icon_view.connect("selection-changed", self._on_selection_changed)

        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(180)
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        scroller.add(self.icon_view)
        self.pack_start(scroller, True, True, 0)

    def _on_selection_changed(self, widget):
        if self.callback:
            self.callback(self.icon_view)

    def on_set_icon_folder(self, widget):
        dialog = Gtk.FileChooserDialog(
            title=f"Select Icons for {self.title}", 
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        
        if dialog.run() == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            key = f"{self.title.lower()}_icons_folder"
            GimpUtils.update_json({key: path}, config.settings.last_inputs_path)
            self.refresh_gallery()
        
        dialog.destroy()

    def refresh_gallery(self):
        """Spawns a daemon thread to fetch data to avoid freezing UI"""
        self.model_store.clear()
        if not self.client: return
        threading.Thread(target=self._worker_fetch_data, daemon=True).start()

    def _worker_fetch_data(self):
        try:
            items = []
            if "checkpoint" in self.title.lower():
                items = self.client.get_available_checkpoints()
            elif "lora" in self.title.lower():
                items = self.client.get_available_loras()
            
            GLib.idle_add(self._populate_store, items)
        except Exception as e:
            print(f"Gallery Fetch Error: {e}")

    def _populate_store(self, items: List[str]):
        if not items: return False
        
        last_inputs = GimpUtils.load_json(config.settings.last_inputs_path)
        icon_dir = last_inputs.get(f"{self.title.lower()}_icons_folder")
        
        # Default Icon
        icon_theme = Gtk.IconTheme.get_default()
        default_icon = icon_theme.load_icon("image-x-generic", 64, 0)

        for filename in sorted(items):
            display_name = os.path.splitext(filename)[0]
            pixbuf = default_icon

            # Resolve Local Icon
            if icon_dir and os.path.exists(icon_dir):
                pixbuf = self._resolve_local_icon(icon_dir, filename, display_name) or default_icon
            
            self.model_store.append([pixbuf, display_name, filename])
        return False

    def _resolve_local_icon(self, directory, filename, display_name):
        candidates = [filename, display_name]
        for c in candidates:
            for ext in ['.png', '.jpg', '.webp']:
                path = os.path.join(directory, c + ext)
                if os.path.exists(path):
                    try:
                        return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 100, 100, True)
                    except: pass
        return None

    def select_item_by_name(self, name: str):
        """Scrolls to and selects an item if it exists"""
        if not name: return
        for row in self.model_store:
            if row[self.COL_FILE] == name: 
                self.icon_view.select_path(row.path)
                self.icon_view.scroll_to_path(row.path, False, 0.0, 0.0)
                return


# -------------------------------------------------------------------
#                        Prompt Widget
# -------------------------------------------------------------------

class PromptWidget(Gtk.Box):
    """
    Manages Positive and Negative prompt inputs with History
    """
    def __init__(self, previous_inputs: Dict[str, Any], parent_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.parent_window = parent_window
        self.history_manager = HistoryManager()

        self.pos_view = self._create_text_area(
            "Positive Prompt", 
            previous_inputs.get("positive_generate_prompt", "")
        )
        self.neg_view = self._create_text_area(
            "Negative Prompt", 
            previous_inputs.get("negative_generate_prompt", "")
        )

        self._build_history_button()

    def _create_text_area(self, label_text: str, content: str) -> Gtk.TextView:
        label = Gtk.Label(label=f"<b>{label_text}</b>", xalign=0, use_markup=True)
        self.pack_start(label, False, False, 0)
        
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(80)
        scroller.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        
        text_view = Gtk.TextView()
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text_view.set_left_margin(8)
        text_view.set_right_margin(8)
        text_view.set_top_margin(8)
        text_view.set_bottom_margin(8)
        text_view.get_buffer().set_text(content)
        
        scroller.add(text_view)
        self.pack_start(scroller, True, True, 2)
        return text_view

    def _build_history_button(self):
        box = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL)
        box.set_layout(Gtk.ButtonBoxStyle.START)
        
        btn = Gtk.Button(label="Load History")
        btn.set_tooltip_text("Load previously used prompts")
        btn.connect("clicked", self._on_history_clicked)
        
        box.pack_start(btn, False, False, 0)
        self.pack_start(box, False, False, 5)

    def get_prompts(self) -> tuple[str, str]:
        p_buf = self.pos_view.get_buffer()
        n_buf = self.neg_view.get_buffer()
        return (
            p_buf.get_text(p_buf.get_start_iter(), p_buf.get_end_iter(), True),
            n_buf.get_text(n_buf.get_start_iter(), n_buf.get_end_iter(), True)
        )

    def set_prompts(self, pos: str, neg: str):
        if pos is not None: self.pos_view.get_buffer().set_text(pos)
        if neg is not None: self.neg_view.get_buffer().set_text(neg)

    def save_history(self):
        p, n = self.get_prompts()
        if p or n:
            self.history_manager.add_entry(p, n)

    def _on_history_clicked(self, widget):
        try:
            dialog = HistoryDialog(self.parent_window, self.history_manager)
        except Exception as e:
            Gimp.message(f"ERROR: {e}")
        if dialog.run() == Gtk.ResponseType.OK:
            sel = dialog.get_selected_entry()
            if sel: 
                self.set_prompts(sel.get("positive"), sel.get("negative"))
        dialog.destroy()


# -------------------------------------------------------------------
#                       LoRA Manager Widget
# -------------------------------------------------------------------

class LoraManagerWidget(Gtk.Box):
    """
    A split view:
    Top: LoRA Gallery
    Bottom: Active LoRA list with strength sliders
    """
    def __init__(self, previous_inputs: Dict[str, Any], client):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.active_loras = {} # {filename: {strength: float, widget: Gtk.Widget}}

        # Gallery
        self.gallery = ResourceGalleryWidget(
            "Loras", Gtk.SelectionMode.SINGLE, client, self._on_gallery_select
        )
        expander = Gtk.Expander(label="Add LoRAs from Library")
        expander.add(self.gallery)
        self.pack_start(expander, False, False, 0)

        # Active List Container
        self.active_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.active_list_box.set_margin_top(10)
        self.pack_start(self.active_list_box, False, False, 0)

        # Restore State
        self._restore_state(previous_inputs.get("loras", {}))

    def _restore_state(self, saved_data):
        if isinstance(saved_data, dict):
            for f, s in saved_data.items(): 
                self.add_lora(f, s)
        elif isinstance(saved_data, list):
            for item in saved_data: 
                self.add_lora(item.get("file"), item.get("strength", 1.0))

    def _on_gallery_select(self, icon_view):
        sel = icon_view.get_selected_items()
        if not sel: return
        
        model = icon_view.get_model()
        fname = model.get_value(model.get_iter(sel[0]), ResourceGalleryWidget.COL_FILE)
        
        if fname not in self.active_loras:
            self.add_lora(fname, 1.0)
        
        icon_view.unselect_all()

    def add_lora(self, filename: str, strength: float):
        """Creates the UI row for a single active LoRA"""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        # Remove Button
        btn_del = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON)
        btn_del.set_relief(Gtk.ReliefStyle.NONE)
        btn_del.set_tooltip_text("Remove this LoRA")
        btn_del.connect("clicked", lambda b: self.remove_lora(filename))
        row.pack_start(btn_del, False, False, 0)

        # Name Label (Truncated)
        display_name = os.path.splitext(filename)[0]
        label_text = (display_name[:25] + "...") if len(display_name) > 28 else display_name
        
        lbl = Gtk.Label(label=label_text)
        lbl.set_halign(Gtk.Align.START)
        lbl.set_tooltip_text(filename)
        row.pack_start(lbl, True, True, 0)

        # Strength Spinner
        adj = Gtk.Adjustment(value=strength, lower=-2.0, upper=5.0, step_increment=0.1)
        spin = Gtk.SpinButton(adjustment=adj, digits=2)
        spin.set_width_chars(5)
        spin.set_tooltip_text("LoRA Strength")
        spin.connect("value-changed", lambda s: self._update_strength(filename, s.get_value()))
        row.pack_start(spin, False, False, 0)

        self.active_list_box.pack_start(row, False, False, 0)
        row.show_all()
        
        self.active_loras[filename] = {"strength": strength, "widget": row}

    def remove_lora(self, filename: str):
        if filename in self.active_loras:
            widget = self.active_loras[filename]["widget"]
            self.active_list_box.remove(widget)
            del self.active_loras[filename]

    def _update_strength(self, filename: str, val: float):
        if filename in self.active_loras:
            self.active_loras[filename]["strength"] = round(val, 2)

    def get_loras(self) -> Dict[str, float]:
        return {k: v["strength"] for k, v in self.active_loras.items()}
    
    def clear(self):
        for k in list(self.active_loras.keys()):
            self.remove_lora(k)


# -------------------------------------------------------------------
#                     Style Browser Widget
# -------------------------------------------------------------------

class StyleBrowserWidget(Gtk.Box):
    """
    Right-side pane for managing saved generation styles (Presets)
    """
    COL_ICON = 0
    COL_NAME = 1
    COL_PATH = 2

    def __init__(self, main_dialog):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.main_dialog = main_dialog
        
        self._build_header()
        self._build_view()
        self.refresh()

    def _build_header(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.set_margin_start(10)
        header.set_margin_end(10)
        
        lbl = Gtk.Label(label="<b>Saved Styles</b>", use_markup=True, xalign=0)
        header.pack_start(lbl, True, True, 0)
        
        btn_icon = Gtk.Button.new_from_icon_name("image-x-generic", Gtk.IconSize.BUTTON)
        btn_icon.set_tooltip_text("Set custom thumbnail for selected style")
        btn_icon.connect("clicked", self.on_set_icon)
        header.pack_start(btn_icon, False, False, 0)
        
        self.pack_start(header, False, False, 0)

    def _build_view(self):
        # Container
        self.viewbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.viewbox.set_margin_start(10)
        self.viewbox.set_margin_end(10)

        # Store & IconView
        self.store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str)
        self.view = Gtk.IconView.new_with_model(self.store)
        self.view.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.view.set_item_width(110)
        self.view.set_text_column(self.COL_NAME)
        self.view.set_pixbuf_column(self.COL_ICON)
        self.view.connect("item-activated", self.on_apply_style)
        
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        scroller.add(self.view)
        
        self.viewbox.pack_start(scroller, True, True, 0)
        self.pack_start(self.viewbox, True, True, 0)

        # Delete Button
        btn_del = Gtk.Button(label="Delete Selected Style")
        btn_del.get_style_context().add_class("destructive-action")
        btn_del.connect("clicked", self.on_delete)
        self.pack_start(btn_del, False, False, 5)

    def refresh(self):
        self.store.clear()
        if not os.path.exists(config.settings.styles_dir): return
        
        icon_theme = Gtk.IconTheme.get_default()
        def_icon = icon_theme.load_icon("image-x-generic", 128, 0)

        for f in sorted(os.listdir(config.settings.styles_dir)):
            if f.endswith(".json"):
                full_path = os.path.join(config.settings.styles_dir, f)
                display_name = os.path.splitext(f)[0]
                
                # Try to find matching image
                icon = self._find_icon(display_name) or def_icon
                self.store.append([icon, display_name, full_path])

    def _find_icon(self, name_no_ext):
        base = os.path.join(config.settings.styles_dir, name_no_ext)
        for ext in ['.png', '.jpg', '.webp']:
            if os.path.exists(base + ext):
                try:
                    return GdkPixbuf.Pixbuf.new_from_file_at_scale(base + ext, 128, 128, True)
                except: pass
        return None

    def on_apply_style(self, view, path):
        """Loads the style JSON and pushes it to the main dialog"""
        model = view.get_model()
        fpath = model.get_value(model.get_iter(path), self.COL_PATH)
        try:
            with open(fpath, 'r') as f:
                data = json.load(f)
                self.main_dialog._load_style(data)
        except Exception as e:
            Gimp.message(f"Error loading style: {e}")

    def on_set_icon(self, widget):
        sel = self.view.get_selected_items()
        if not sel: return
        
        model = self.view.get_model()
        json_path = model.get_value(model.get_iter(sel[0]), self.COL_PATH)
        
        dialog = Gtk.FileChooserDialog(title="Select Icon Image", action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        
        if dialog.run() == Gtk.ResponseType.OK:
            img_path = dialog.get_filename()
            dest = os.path.splitext(json_path)[0] + ".png"
            try:
                pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(img_path, 128, 128, True)
                pix.savev(dest, "png", [], [])
                self.refresh()
            except Exception as e:
                Gimp.message(f"Error saving icon: {e}")
        
        dialog.destroy()

    def on_delete(self, widget):
        sel = self.view.get_selected_items()
        if not sel: return
        
        model = self.view.get_model()
        fpath = model.get_value(model.get_iter(sel[0]), self.COL_PATH)
        
        # Confirmation
        confirm = Gtk.MessageDialog(
            text="Delete Style?", 
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL
        )
        confirm.format_secondary_text(f"Are you sure you want to delete '{os.path.basename(fpath)}'?")
        
        if confirm.run() == Gtk.ResponseType.OK:
            if os.path.exists(fpath):
                os.remove(fpath)
                # Cleanup associated image
                base = os.path.splitext(fpath)[0]
                for ext in ['.png', '.jpg', '.webp']:
                    if os.path.exists(base + ext): 
                        os.remove(base + ext)
                self.refresh()
        
        confirm.destroy()