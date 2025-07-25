#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Utility functions for handling JSON data and logging within GIMP Python plugins.
# Functions:
#     is_jsonable(x):
#         Check if the input can be parsed as JSON.
#     write_to_log_file(data, log_file_path):
#         Append a string to a log file. Displays a GIMP message on error.
#     write_to_json_file(data, file_path):
#         Write a Python object to a JSON file with indentation.
#     load_json_file(file_path):
#         Load and return JSON data from a file. Returns an empty dict on error or if the file does not exist.
#     update_json_file(data, file_path):
#         Merge new data with existing JSON data in a file and write the result back.
#     load_previous_inputs(previous_inputs_path):
#         Load previous input data from a JSON file and return both the data and the file path.

import os
import json

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp

def is_jsonable(x):
    try:
        json.loads(x)
        return True
    except (TypeError, OverflowError, ValueError):
        return False
    
def write_to_log_file(data, log_file_path):
    try:
        with open(log_file_path, "a") as log_file:
            log_file.write(data + "\n\n")
    except Exception as log_error:
        Gimp.message(f"Error writing to log file: {log_error}")

def write_to_json_file(data, file_path):
    """Write data to a JSON file with indentation."""
    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)

def load_json_file(file_path):
    """Load JSON data from a file. Returns {} on error or if file doesn't exist."""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as file:
                return json.load(file)
        except (json.JSONDecodeError, IOError, FileNotFoundError):
            return {}
    return {}

def update_json_file(data, file_path):
    """Merge and write updated data to a JSON file."""
    existing_data = load_json_file(file_path)
    existing_data.update(data)
    write_to_json_file(existing_data, file_path)

def load_previous_inputs(previous_inputs_path):
    """Load previous inputs from a JSON file and return the data and path."""
    previous_inputs = {}
    if os.path.exists(previous_inputs_path):
        with open(previous_inputs_path, "r") as text_inputs_file:
            previous_inputs = json.load(text_inputs_file)
    return previous_inputs, previous_inputs_path