#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Robust client for interacting with the ComfyUI API
Handles API requests, WebSocket streaming, and workflow modifying
"""

import json
import os
import requests
import websocket
from typing import Optional, Dict, List, Any, Generator, Tuple

# --- Helpers ---

def api_guard(default_return: Any = None):
    """
    Decorator to wrap API calls with error handling
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except requests.exceptions.RequestException as e:
                print(f"[ComfyClient] Network Error in {func.__name__}: {e}")
            except Exception as e:
                print(f"[ComfyClient] Unexpected Error in {func.__name__}: {e}")
            return default_return
        return wrapper
    return decorator


class ComfyClient:
    """
    Manages communication with a ComfyUI server instance
    """

    def __init__(self, server_address: str = "127.0.0.1:8188", timeout: int = 10):
        self.server_address = server_address
        self.timeout = timeout
        self.base_url = f"http://{server_address}"
        self.ws_url = f"ws://{server_address}/ws"
        
        # Cache for expensive node definition queries
        self._object_info_cache: Optional[Dict] = None

    # =========================================================================
    #                                SYSTEM STATUS
    # =========================================================================

    def is_reachable(self) -> bool:
        """Checks if the server is online"""
        try:
            resp = requests.get(f"{self.base_url}/system_stats", timeout=3)
            return resp.status_code == 200
        except requests.exceptions.RequestException:
            return False

    @api_guard(default_return={})
    def get_system_stats(self) -> Dict:
        """Returns server statistics (e.g., queue size)"""
        resp = requests.get(f"{self.base_url}/system_stats", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    @api_guard(default_return=True)
    def interrupt(self) -> bool:
        """Sends an interrupt signal to stop current generation"""
        requests.post(f"{self.base_url}/interrupt", timeout=2)
        return True

    @api_guard(default_return=True)
    def clear_queue(self) -> bool:
        """Clears the pending generation queue"""
        requests.post(f"{self.base_url}/queue", json={"clear": True}, timeout=2)
        return True

    # =========================================================================
    #                            METADATA & DISCOVERY
    # =========================================================================

    @api_guard(default_return={})
    def _fetch_object_info(self) -> Dict:
        """
        Fetches definitions for all nodes
        Caches the result to improve performance on subsequent calls
        """
        if self._object_info_cache:
            return self._object_info_cache
            
        resp = requests.get(f"{self.base_url}/object_info", timeout=self.timeout)
        resp.raise_for_status()
        self._object_info_cache = resp.json()
        return self._object_info_cache

    def refresh_cache(self) -> None:
        """Forces a refresh of the internal node definition cache"""
        self._object_info_cache = None
        self._fetch_object_info()

    def _get_node_input_list(self, node_class: str, input_name: str, default: List[str] = []) -> List[str]:
        """Helper to extract a specific list of options from node definitions"""
        info = self._fetch_object_info()
        try:
            return info[node_class]['input']['required'][input_name][0]
        except (KeyError, TypeError):
            return default

    def get_available_samplers(self) -> List[str]:
        return self._get_node_input_list(
            'KSampler', 'sampler_name', 
            ["euler", "euler_ancestral", "heun", "dpm_2", "dpmpp_2m", "ddim"]
        )

    def get_available_schedulers(self) -> List[str]:
        return self._get_node_input_list(
            'KSampler', 'scheduler', 
            ["normal", "karras", "exponential", "simple", "ddim_uniform"]
        )

    def get_available_checkpoints(self) -> List[str]:
        return self._get_node_input_list('CheckpointLoaderSimple', 'ckpt_name')

    def get_available_loras(self) -> List[str]:
        return self._get_node_input_list('LoraLoader', 'lora_name')

    def get_available_vaes(self) -> List[str]:
        return self._get_node_input_list('VAELoader', 'vae_name')

    # =========================================================================
    #                            FILE I/O
    # =========================================================================

    def download_image(self, filename: str, subfolder: str, type_str: str, output_path: str) -> bool:
        """Downloads an image from the server to a local path"""
        params = {"filename": filename, "subfolder": subfolder, "type": type_str}
        url = f"{self.base_url}/api/view"
        
        try:
            with requests.get(url, params=params, stream=True, timeout=self.timeout) as r:
                r.raise_for_status()
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192): 
                        f.write(chunk)
            return True
        except Exception as e:
            print(f"[ComfyClient] Download Failed: {e}")
            return False

    def upload_image(self, file_path: str, subfolder: str = "", overwrite: bool = True) -> Optional[Dict]:
        """
        Uploads an image to the ComfyUI input directory
        Returns the JSON response (containing 'name' and 'subfolder') or None
        """
        url = f"{self.base_url}/api/upload/image"
        try:
            with open(file_path, 'rb') as f:
                files = {'image': f}
                data = {'overwrite': str(overwrite).lower(), 'subfolder': subfolder}
                resp = requests.post(url, files=files, data=data, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            print(f"[ComfyClient] Upload Failed: {e}")
            return None

    # =========================================================================
    #                       WORKFLOW & GENERATION
    # =========================================================================

    @api_guard(default_return=None)
    def queue_prompt(self, workflow_json: Dict, client_id: str):
        """Submits a workflow to the execution queue"""
        payload = {"prompt": workflow_json, "client_id": client_id}
        resp = requests.post(f"{self.base_url}/api/prompt", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def stream_generation(self, workflow: Dict, client_id: str, timeout: int = 2) -> Generator[Tuple[str, Any], None, None]:
        """
        Orchestrates the generation process via WebSocket.
        Yields events: ('progress', ...), ('preview_bytes', ...), ('finished_metadata', ...), ('error', ...)
        """
        ws = websocket.WebSocket()
        try:
            ws.connect(f"{self.ws_url}?clientId={client_id}", timeout=self.timeout)
        except Exception as e:
            yield ("error", f"WebSocket Connection Failed: {e}")
            return

        # Queue the job
        prompt_resp = self.queue_prompt(workflow, client_id)
        if not prompt_resp:
            ws.close()
            yield ("error", "Failed to queue workflow. Check nodes and inputs.")
            return

        ws.settimeout(timeout)

        # Event Loop
        while True:
            try:
                out = ws.recv()
                
                # Binary Message = Preview Image
                if isinstance(out, bytes):
                    # ComfyUI sends 8 bytes header (type + format) followed by image data
                    if len(out) > 8:
                        yield ("preview_bytes", out[8:])
                    continue

                # Text Message = JSON Event
                message = json.loads(out)
                msg_type = message.get("type")
                data = message.get("data", {})

                if msg_type == "progress":
                    yield ("progress", (data["value"], data["max"]))
                
                elif msg_type == "executing":
                    if data.get("node") is None:
                        # 'node' is None implies execution finished
                        yield ("finished", None)
                        break
                
                elif msg_type == "executed":
                    if "images" in data.get("output", {}):
                        yield ("finished_metadata", data["output"]["images"])
                        
                elif msg_type == "execution_error":
                    err_msg = data.get("exception_message", "Unknown Error")
                    yield ("error", f"Workflow Error: {err_msg}")
                    break

            except websocket.WebSocketTimeoutException:
                # Alive check
                yield ("heartbeat", None)
                continue
            
            except Exception as e:
                yield ("error", f"Stream Read Error: {e}")
                break
        
        ws.close()

    # =========================================================================
    #                        WORKFLOW PREPARATION
    # =========================================================================

    def prepare_workflow(self, 
                         workflow_path: str, 
                         main_params: Dict, 
                         lora_params: Dict[str, float], 
                         sampler_params: Dict) -> Tuple[Dict, Dict]:
        """
        Injects parameters, LoRAs, and Masks into a workflow template
        Returns: (Processed Workflow JSON, Save Metadata)
        """
        if not os.path.exists(workflow_path):
            raise FileNotFoundError(f"Workflow file missing: {workflow_path}")

        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        if "nodes" in workflow:
            raise ValueError("Invalid format. Please export workflow in API format (no 'nodes' key)")

        save_inputs = {}
        
        # 1. Update Standard Nodes (KSampler, Checkpoint, Seed, Dims)
        self._update_standard_params(workflow, main_params, sampler_params)
        
        # 2. Update Prompts
        prompt_meta = self._update_prompts(workflow, main_params)
        save_inputs.update(prompt_meta)

        # 3. Inject LoRAs
        if lora_params:
            self._inject_loras(workflow, main_params.get("checkpoint_selection"), lora_params)

        # 4. Inject Mask
        if main_params.get("mask_name"):
            self._inject_mask(workflow, main_params["mask_name"])

        return workflow, save_inputs

    def _update_standard_params(self, workflow: Dict, main_params: Dict, sampler_params: Dict):
        """Updates KSampler settings, Checkpoint, Seed, and Image Dimensions"""
        param_map = {
            "steps": "steps", "cfg": "cfg", "sampler_name": "sampler",
            "scheduler": "scheduler", "denoise": "denoise_strength"
        }
        
        for node in workflow.values():
            inputs = node.get("inputs", {})
            cls = node.get("class_type", "")

            # Image Input
            if cls == "LoadImage":
                if main_params['input_image_name']:
                    inputs["image"] = main_params["input_image_name"]
                else:
                    inputs["image"] = "no_image_found_check_input_mask.jpg"

            # Checkpoint
            if cls in ["CheckpointLoaderSimple", "CheckpointLoader"]:
                if main_params.get("checkpoint_selection"):
                    inputs["ckpt_name"] = main_params["checkpoint_selection"]

            # Sampler Settings
            for comfy_key, local_key in param_map.items():
                if comfy_key in inputs and local_key in sampler_params:
                    inputs[comfy_key] = sampler_params[local_key]

            # Seed
            if "seed" in inputs and main_params.get("seed"):
                inputs["seed"] = main_params["seed"]
            if "noise_seed" in inputs and main_params.get("seed"):
                inputs["noise_seed"] = main_params["seed"]

            # Dimensions
            if "width" in inputs and "height" in inputs:
                if main_params.get("image_width") and main_params.get("image_height"):
                    inputs["width"] = main_params["image_width"]
                    inputs["height"] = main_params["image_height"]

    def _update_prompts(self, workflow: Dict, main_params: Dict) -> Dict:
        """Traces prompt connections to find and update the correct Text Encode nodes"""
        meta = {}
        
        for node in workflow.values():
            inputs = node.get("inputs", {})
            
            # Look for a node that takes both 'positive' and 'negative' inputs (usually KSampler)
            if "positive" in inputs and "negative" in inputs:
                
                # Helper to resolve link: [node_id, slot_idx]
                def resolve_node(link):
                    if isinstance(link, list) and len(link) > 0:
                        return str(link[0])
                    return None

                pos_id = resolve_node(inputs["positive"])
                neg_id = resolve_node(inputs["negative"])

                if pos_id and pos_id in workflow:
                    p_node = workflow[pos_id]
                    if "text" in p_node.get("inputs", {}) and main_params.get("positive_prompt"):
                        p_node["inputs"]["text"] = main_params["positive_prompt"]
                        meta["positive_generate_prompt"] = main_params["positive_prompt"]

                if neg_id and neg_id in workflow:
                    n_node = workflow[neg_id]
                    if "text" in n_node.get("inputs", {}) and main_params.get("negative_prompt"):
                        n_node["inputs"]["text"] = main_params["negative_prompt"]
                        meta["negative_generate_prompt"] = main_params["negative_prompt"]
        
        return meta

    def _inject_loras(self, workflow: Dict, checkpoint_name: Optional[str], lora_params: Dict[str, float]):
        """Injects a chain of LoRA loaders between the Checkpoint Loader and its consumers"""
        
        # 1. Find the Checkpoint Node ID
        ckpt_node_id = None
        for nid, node in workflow.items():
            if node.get("class_type") in ["CheckpointLoaderSimple", "CheckpointLoader"]:
                # If a specific checkpoint was requested, ensure we match (or just take the first one)
                ckpt_node_id = nid
                break
        
        if not ckpt_node_id: 
            return

        # 2. Identify consumers (nodes connected to this checkpoint)
        consumers = []
        for nid, node in workflow.items():
            if nid == ckpt_node_id: continue
            inputs = node.get("inputs", {})
            for key, val in inputs.items():
                # ComfyUI Links are lists: [node_id, slot_index]
                if isinstance(val, list) and len(val) == 2:
                    if str(val[0]) == ckpt_node_id:
                        consumers.append((node, key, val[1]))

        # 3. Create LoRA Chain
        current_model = [ckpt_node_id, 0]
        current_clip = [ckpt_node_id, 1]

        # Helper to generate unique IDs
        ids = [int(k) for k in workflow.keys() if k.isdigit()]
        next_id = max(ids) + 1 if ids else 1

        for lora_name, strength in lora_params.items():
            new_id = str(next_id)
            workflow[new_id] = {
                "inputs": {
                    "lora_name": lora_name,
                    "strength_model": round(strength, 2),
                    "strength_clip": round(strength, 2),
                    "model": current_model,
                    "clip": current_clip
                },
                "class_type": "LoraLoader",
                "_meta": {"title": f"LoRA: {lora_name}"}
            }
            
            current_model = [new_id, 0]
            current_clip = [new_id, 1]
            next_id += 1

        # 4. Rewire consumers to the end of the chain
        for node, key, slot in consumers:
            if slot == 0:
                node["inputs"][key] = current_model
            elif slot == 1:
                node["inputs"][key] = current_clip

    def _inject_mask(self, workflow: Dict, mask_name: str):
        """Injects a LoadImageMask node and connects it to nodes expecting a 'mask'"""
        
        if mask_name == None:
            raise ValueError("No mask found")

        # 1. Find nodes that need a mask
        target_nodes = []
        for node in workflow.values():
            if "mask" in node.get("inputs", {}):
                target_nodes.append(node)
        
        if not target_nodes: 
            return

        # 2. Create the Mask Loader Node
        ids = [int(k) for k in workflow.keys() if k.isdigit()]
        new_id = str(max(ids) + 1 if ids else 1)

        workflow[new_id] = {
            "inputs": {
                "image": mask_name,
                "channel": "green", 
                "upload": "image"
            },
            "class_type": "LoadImageMask",
            "_meta": {"title": "Load Image (as Mask)"}
        }

        # 3. Connect targets
        for node in target_nodes:
            node["inputs"]["mask"] = [new_id, 0]