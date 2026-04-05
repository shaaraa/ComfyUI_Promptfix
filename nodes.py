import os
import hashlib
import time
import torch
import numpy as np
from PIL import Image, ImageOps
from io import BytesIO
import folder_paths
from nodes import SaveImage
import aiohttp
import asyncio

# Setup paths
nodepath = os.path.dirname(os.path.abspath(__file__))

def is_changed_file(filepath):
    try:
        with open(filepath, "rb") as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        if not hasattr(is_changed_file, "file_hashes"):
            is_changed_file.file_hashes = {}
        if filepath in is_changed_file.file_hashes:
            if is_changed_file.file_hashes[filepath] == file_hash:
                return False
        is_changed_file.file_hashes[filepath] = file_hash
        return float("NaN") # Always re-execute if hash changed
    except Exception as e:
        return float("NaN")

class PromptFixInput:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT")
    RETURN_NAMES = ("Canvas", "Mask", "Width", "Height")
    FUNCTION = "execute"
    CATEGORY = "PromptFix"

    def execute(self):
        self.canvasDir = os.path.join(nodepath, "data", "ps_inputs", "PS_canvas.png")
        self.maskImgDir = os.path.join(nodepath, "data", "ps_inputs", "PS_mask.png")
        
        # In case backend is still writing files, allow mild retry
        for _ in range(5):
            if os.path.exists(self.canvasDir):
                break
            time.sleep(0.5)

        # Load Canvas
        self.loadImg(self.canvasDir)
        canvas = self.i.convert("RGB")
        canvas = np.array(canvas).astype(np.float32) / 255.0
        canvas = torch.from_numpy(canvas)[None,]
        width, height = self.i.size

        # Load Mask
        self.loadImg(self.maskImgDir)
        self.i = ImageOps.exif_transpose(self.i)
        
        # The mask is provided as a black/white color image from Photoshop.
        # Ignore its Alpha channel entirely, and just convert the visual colors to grayscale (Luminance).
        
        # To avoid transparent background turning black (if any), paste it over a black background first just in case
        if "A" in self.i.getbands():
            new_img = Image.new("RGBA", self.i.size, "BLACK")
            new_img.paste(self.i, (0, 0), self.i)
            mask_img = new_img.convert("L")
        else:
            mask_img = self.i.convert("L")

        mask = np.array(mask_img).astype(np.float32) / 255.0
            
        mask = torch.from_numpy(mask)

        # Ensure #010101 or almost black acts as perfect 0
        mask_np = mask.numpy()
        mask_np[mask_np <= (1.0 / 255.0)] = 0.0
        mask = torch.from_numpy(mask_np)

        return (canvas, mask.unsqueeze(0), int(width), int(height))

    def loadImg(self, path):
        try:
            with open(path, "rb") as file:
                img_data = file.read()
            self.i = Image.open(BytesIO(img_data))
            self.i.verify()
            self.i = Image.open(BytesIO(img_data))
        except Exception as e:
            print(f"[PromptFix] Could not load {path}: {e}")
            self.i = Image.new(mode="RGB", size=(256, 256), color=(0, 0, 0))

    @classmethod
    def IS_CHANGED(cls):
        canvasDir = os.path.join(nodepath, "data", "ps_inputs", "PS_canvas.png")
        maskImgDir = os.path.join(nodepath, "data", "ps_inputs", "PS_mask.png")
        c1 = is_changed_file(canvasDir)
        c2 = is_changed_file(maskImgDir)
        if c1 or c2:
            return float("NaN")
        return 0

import urllib.request

class PromptFixOutput(SaveImage):
    def __init__(self):
        self.output_dir = folder_paths.get_temp_directory()
        self.type = "temp"
        self.prefix_append = "_promptfix_"
        self.compress_level = 4

    @staticmethod
    def INPUT_TYPES():
        return {
            "required": {
                "output_image": ("IMAGE",),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    FUNCTION = "execute"
    CATEGORY = "PromptFix"
    OUTPUT_NODE = True 

    def notify_backend_sync(self, filename):
        try:
            from server import PromptServer
            port = PromptServer.instance.port
            url = f"http://127.0.0.1:{port}/promptfix/renderdone?filename={filename}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req) as response:
                return response.read().decode('utf-8')
        except Exception as e:
            print(f"[PromptFix] Error notifying backend of render completion: {e}")

    def execute(
        self,
        output_image: torch.Tensor,
        filename_prefix="PF_OUT",
        prompt=None,
        extra_pnginfo=None,
    ):
        # SaveImage.save_images
        result = self.save_images(output_image, filename_prefix, prompt, extra_pnginfo)
        
        # Get filename of saved file
        filename = result["ui"]["images"][0]["filename"]
        
        # Send HTTP notification to our backend script synchronously
        self.notify_backend_sync(filename)
        
        return result

NODE_CLASS_MAPPINGS = {
    "PromptFixInput": PromptFixInput,
    "PromptFixOutput": PromptFixOutput,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptFixInput": "🎨 PromptFix Input (From Photoshop)",
    "PromptFixOutput": "🎨 PromptFix Output (To Photoshop)",
}
