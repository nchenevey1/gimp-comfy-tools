#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Common utilities for file I/O, JSON handling, and GIMP 3.0 image manipulation
"""

import os
import json
import re
import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gio

import config

# -------------------------------------------------------------------
#                           File & JSON I/O
# -------------------------------------------------------------------

def load_json(file_path: str) -> Dict[str, Any]:
    """
    Loads a JSON file
    """
    path = Path(file_path)
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"[GimpUtils] Error loading JSON {path}: {e}")
        return {}

def save_json(data: Dict[str, Any], file_path: str) -> bool:
    """
    Writes data to a JSON file, ensuring the directory exists
    Returns True on success
    """
    path = Path(file_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        Gimp.message(f"Error writing settings to {path.name}: {e}")
        return False

def update_json(data: Dict[str, Any], file_path: str) -> None:
    """
    Merges new data into an existing JSON file
    """
    current_data = load_json(file_path)
    current_data.update(data)
    save_json(current_data, file_path)

def sanitize_filename(filename: str, replacement: str = "_") -> str:
    """
    Sanitizes a string to be safe for use as a filename
    """
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', replacement, filename).strip()

def log_message(message: str, log_file: str = "plugin.log") -> None:
    """
    Appends a timestamped message to a log file
    """
    path = Path(config.settings.comfy_dir) / log_file
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        print(f"Logging failed: {e}")

# -------------------------------------------------------------------
#                        GIMP Image Operations
# -------------------------------------------------------------------

def insert_image_layer(
    image: Gimp.Image, 
    file_path: str, 
    layer_name: str = "Comfy Layer"
) -> Optional[Gimp.Layer]:
    """
    Loads an image file as a new layer
    """
    path = Path(file_path)
    if not path.exists():
        return None

    try:
        g_file = Gio.File.new_for_path(str(path))
        # Load the layer
        new_layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, g_file)
        
        if not new_layer:
            raise RuntimeError("Failed to load layer from file.")

        new_layer.set_name(layer_name)
        
        # Center the layer
        offset_x = (image.get_width() - new_layer.get_width()) // 2
        offset_y = (image.get_height() - new_layer.get_height()) // 2
        new_layer.set_offsets(offset_x, offset_y)

        # Insert at top (position 0)
        image.insert_layer(new_layer, None, 0)
        
        return new_layer

    except Exception as e:
        print(f"[GimpUtils] Insert Layer Error: {e}")
        return None
        

def save_image_to_disk(image: Gimp.Image, file_path: str) -> bool:
    """
    Exports the given GIMP image to disk (PNG/JPG based on extension)
    """
    try:
        file_out = Gio.File.new_for_path(file_path)
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, file_out)
        return True
    except Exception as e:
        Gimp.message(f"Export failed: {e}")
        return False

def create_mask_from_selection(image: Gimp.Image) -> Optional[str]:
    """
    Generates a black & white mask based on the current selection
    
    Strategy:
    1. Duplicates the image to avoid modifying active work
    2. Converts selection to B/W layer
    3. Exports to a temp file
    4. Cleans up
    
    Returns: Path to the generated mask file, or None if no selection
    """
    if Gimp.Selection.is_empty(image):
        return None

    temp_path = os.path.join(config.settings.temp_images_dir, "temp_mask.png")
    temp_img = None

    try:
        # 1. Duplicate Image
        temp_img = image.duplicate()
        
        # 2. Save Context (Colors, etc.)
        Gimp.context_push()
        
        # 3. Save selection channel, create mask layer
        saved_sel = Gimp.Selection.save(temp_img)
        
        mask_layer = Gimp.Layer.new(
            temp_img, "Mask",
            temp_img.get_width(), temp_img.get_height(),
            Gimp.ImageType.RGBA_IMAGE, 100, Gimp.LayerMode.NORMAL
        )
        temp_img.insert_layer(mask_layer, None, 0)

        # 4. Fill Background (Black)
        Gimp.Selection.none(temp_img)
        Gimp.context_set_default_colors() # FG=Black, BG=White
        mask_layer.edit_fill(Gimp.FillType.FOREGROUND) 

        # 5. Fill Selection (White)
        temp_img.select_item(Gimp.ChannelOps.REPLACE, saved_sel)
        Gimp.context_swap_colors() # FG=White
        mask_layer.edit_fill(Gimp.FillType.FOREGROUND)

        # 6. Export
        save_image_to_disk(temp_img, temp_path)
        return temp_path

    except Exception as e:
        print(f"[GimpUtils] Mask Creation Error: {e}")
        return None

    finally:
        Gimp.context_pop()
        if temp_img:
            temp_img.delete()

def get_layer_by_name(image: Gimp.Image, name: str) -> Optional[Gimp.Layer]:
    """
    Finds the first layer matching 'name' in the image stack
    """
    for layer in image.list_layers():
        if layer.get_name() == name:
            return layer
    return None