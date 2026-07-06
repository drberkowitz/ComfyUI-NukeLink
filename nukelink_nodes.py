import os

import numpy as np
import torch

from .utils import (
    parse_frame_pattern,
    expand_frame_pattern,
    detect_sequence,
    read_image,
    write_image,
    resolve_file_path,
    OIIO_AVAILABLE,
    CV2_AVAILABLE,
    PIL_AVAILABLE,
)

# ============================================================================
# Colorspace matrices (no-CAT Rec.709 <-> ACEScg, matching Nuke nuke-default)
# ============================================================================

_REC709_PRIMARIES = {
    "R": (0.640, 0.330), "G": (0.300, 0.600),
    "B": (0.150, 0.060), "W": (0.3127, 0.3290),
}
_AP1_PRIMARIES_D65_LEGACY = {
    "R": (0.713, 0.293), "G": (0.165, 0.830),
    "B": (0.128, 0.044), "W": (0.3127, 0.3290),
}

def _rgb_to_xyz_matrix(primaries: dict) -> np.ndarray:
    xr, yr = primaries["R"]
    xg, yg = primaries["G"]
    xb, yb = primaries["B"]
    xw, yw = primaries["W"]
    def xyz_col(x, y):
        return np.array([x / y, 1.0, (1.0 - x - y) / y])
    M_p = np.column_stack([xyz_col(xr, yr), xyz_col(xg, yg), xyz_col(xb, yb)])
    W_xyz = xyz_col(xw, yw)
    S = np.linalg.solve(M_p, W_xyz)
    return M_p * S

_M_REC709_TO_XYZ = _rgb_to_xyz_matrix(_REC709_PRIMARIES)
_M_AP1_TO_XYZ   = _rgb_to_xyz_matrix(_AP1_PRIMARIES_D65_LEGACY)
_M_AP1_TO_REC709 = np.linalg.inv(_M_AP1_TO_XYZ) @ _M_REC709_TO_XYZ
_M_REC709_TO_AP1 = np.linalg.inv(_M_REC709_TO_XYZ) @ _M_AP1_TO_XYZ

def _apply_primary_matrix(img: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    if img.ndim != 3 or img.shape[2] not in (3, 4):
        raise ValueError(f"Expected (H, W, 3) or (H, W, 4), got {img.shape}")
    rgb = img[..., :3].astype(np.float32, copy=False)
    transformed = rgb @ matrix.T.astype(np.float32)
    if img.shape[2] == 4:
        return np.concatenate([transformed, img[..., 3:4]], axis=-1)
    return transformed

# ============================================================================
# NukeLinkRead node
# ============================================================================

class NukeLinkRead:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "file_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Path to image or sequence (e.g., X:/path/image.####.exr)",
                }),
                "_row_a": ("STRING", {"default": "", "hidden": True}),
                "first_frame": ("INT", {"default": 1001, "min": 1, "max": 999999, "step": 1}),
                "last_frame":  ("INT", {"default": 1001, "min": 1, "max": 999999, "step": 1}),
                "missing_frames": (["error", "black", "hold", "nearest"], {"default": "black"}),
                "colorspace": (["raw", "sRGB", "linear", "ACEScg"], {"default": "raw"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "INT")
    RETURN_NAMES = ("IMAGE", "MASK", "frame_count")
    FUNCTION = "execute"
    CATEGORY = "NukeLink"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def execute(self, file_path, first_frame, last_frame, missing_frames, colorspace, _row_a=""):
        if not file_path or not file_path.strip():
            print("[NukeLinkRead] No file path specified")
            empty_image = torch.zeros(1, 64, 64, 3)
            empty_mask = torch.zeros(1, 64, 64)
            return {"ui": {"images": []}, "result": (empty_image, empty_mask, 0)}

        file_path = resolve_file_path(file_path)
        
        print(f"[NukeLinkRead] Loading: {file_path}")
        
        try:
            first_frame = int(first_frame)
        except Exception:
            first_frame = 1001
        try:
            last_frame = int(last_frame)
        except Exception:
            last_frame = first_frame

        pattern, frame_spec, padding = parse_frame_pattern(file_path)
        is_sequence = frame_spec is not None and padding > 0

        if is_sequence:
            frames_to_load = list(range(first_frame, last_frame + 1))
            print(f"[NukeLinkRead] Sequence detected, loading frames {first_frame}-{last_frame}")
        else:
            frames_to_load = [0]
            print("[NukeLinkRead] Single file detected")

        # For hold/nearest we need the available frame list up front
        available_frames = []
        if is_sequence and missing_frames in ["hold", "nearest"]:
            _, available_frames, _ = detect_sequence(file_path)

        images = []
        masks  = []
        reference_shape = None

        for f in frames_to_load:
            actual_path = expand_frame_pattern(pattern, f, padding) if is_sequence else file_path
            img = None

            if os.path.exists(actual_path):
                img = read_image(actual_path)
            else:
                if missing_frames == "error":
                    print(f"[NukeLinkRead] Missing frame, raising error: {actual_path}")
                    raise FileNotFoundError(f"Frame not found: {actual_path}")
                elif missing_frames == "hold" and images:
                    img = images[-1]  # already processed RGB, safe to reuse
                elif missing_frames == "nearest" and available_frames:
                    nearest = min(available_frames, key=lambda x: abs(x - f))
                    nearest_path = expand_frame_pattern(pattern, nearest, padding)
                    img = read_image(nearest_path)
                # "black" stays None intentionally

            # Track reference shape from first real frame
            if img is not None and reference_shape is None:
                reference_shape = img.shape

            # Sentinel: defer black frame creation until after loop
            if img is None:
                images.append(None)
                masks.append(None)
                continue

            # Ensure at least 3 channels
            if len(img.shape) == 2:
                img = np.stack([img, img, img], axis=-1)
            elif img.shape[2] == 1:
                img = np.concatenate([img, img, img], axis=-1)

            # Extract mask from alpha if present, then strip to RGB
            if img.shape[2] == 4:
                mask = img[:, :, 3]
                img  = img[:, :, :3]
            else:
                mask = np.ones((img.shape[0], img.shape[1]), dtype=np.float32)

            # Colorspace conversion
            if colorspace == "sRGB":
                img = np.where(
                    img <= 0.04045,
                    img / 12.92,
                    np.power(np.clip((img + 0.055) / 1.055, 0.0, None), 2.4),
                )
            elif colorspace == "ACEScg":
                img = _apply_primary_matrix(img, _M_AP1_TO_REC709)

            images.append(img)
            masks.append(mask)
        
        # Replace None sentinels (black frames) with correctly-shaped zero arrays
        fallback_shape = reference_shape if reference_shape else (512, 512, 3)
        fallback_img  = np.zeros(fallback_shape[:2] + (3,), dtype=np.float32)  # always RGB after strip
        fallback_mask = np.ones(fallback_shape[:2], dtype=np.float32)

        images = [fallback_img if img is None else img for img in images]
        masks  = [fallback_mask if m  is None else m  for m  in masks]

        if images:
            result_images = torch.from_numpy(np.stack(images, axis=0))
            result_masks  = torch.from_numpy(np.stack(masks,  axis=0))
        else:
            result_images = torch.zeros(1, 512, 512, 3)
            result_masks  = torch.zeros(1, 512, 512)

        frame_count = result_images.shape[0]
        print(f"[NukeLinkRead] Loaded {frame_count} frame(s)")

        return {"ui": {"images": []}, "result": (result_images, result_masks, frame_count)}

# ============================================================================
# NukeLinkWrite node
# ============================================================================

class NukeLinkWrite:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image":      ("IMAGE",),
                "file_path":  ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Output path (e.g., X:/path/image.####.exr)",
                }),
                "first_frame": ("INT", {"default": 1001, "min": 1, "max": 999999, "step": 1}),
                "file_type":  (["exr", "tiff", "png", "jpg", "tga", "bmp"], {"default": "png"}),
                "bit_depth":  (["8", "16", "16f", "32f"], {"default": "16f"}),
                "compression":(["none","rle","zip","zips","piz","pxr24","b44","b44a","dwaa","dwab"], {"default": "none"}),
                "colorspace": (["raw", "sRGB", "linear", "ACEScg"], {"default": "raw"}),
            },
            "optional": {
                "mask": ("MASK",),
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "execute"
    CATEGORY = "NukeLink"
    OUTPUT_NODE = True

    def execute(self, image, file_path, first_frame, file_type, bit_depth, compression, colorspace, mask=None):
        if not file_path or not file_path.strip():
            print("[NukeLinkWrite] No file path specified")
            return {"ui": {"nukelink_preview": []}}

        file_path = resolve_file_path(file_path)
        
        # Capture separator intent from trailing non-alphanumeric character
        last_char = file_path[-1] if file_path else ""
        user_separator = last_char if not last_char.isalnum() else ""
        clean_path = file_path[:-1] if user_separator else file_path

        # Ensure correct extension
        base, ext = os.path.splitext(clean_path)
        if ext.lower().lstrip(".") != file_type:
            file_path = f"{base}.{file_type}"
        else:
            file_path = clean_path

        base, _ = os.path.splitext(file_path)
        pattern, frame_spec, padding = parse_frame_pattern(file_path, user_separator, file_type)
        explicit_pattern = frame_spec is not None and not (frame_spec.isdigit() and not user_separator)
        is_sequence = explicit_pattern and padding > 0
        if not is_sequence:
            padding = 4

        batch_size = image.shape[0]

        for i in range(batch_size):
            frame_num = first_frame + i
            pixels = image[i].cpu().numpy()

            # Composite mask into alpha channel
            if mask is not None:
                m = mask[i].cpu().numpy() if mask.shape[0] > 1 else mask[0].cpu().numpy()
                if pixels.shape[2] == 3:
                    pixels = np.concatenate([pixels, m[..., np.newaxis]], axis=-1)
                else:
                    pixels[..., 3] = m
            else:
                if pixels.shape[2] == 3:
                    alpha = np.ones((*pixels.shape[:2], 1), dtype=np.float32)
                    pixels = np.concatenate([pixels, alpha], axis=-1)

            # Colorspace encoding
            if colorspace == "sRGB":
                rgb = pixels[..., :3]
                rgb = np.where(
                    rgb <= 0.0031308,
                    rgb * 12.92,
                    1.055 * np.power(np.clip(rgb, 0.0031308, None), 1 / 2.4) - 0.055,
                )
                pixels = np.concatenate([rgb, pixels[..., 3:]], axis=-1)
            elif colorspace == "ACEScg":
                pixels = _apply_primary_matrix(pixels, _M_REC709_TO_AP1)

            # Resolve output path
            if is_sequence:
                output_path = expand_frame_pattern(pattern, frame_num, padding)
            else:
                if batch_size > 1:
                    frame_str = str(frame_num).zfill(padding)
                    output_path = f"{base}{user_separator}{frame_str}.{file_type}"
                else:
                    output_path = f"{base}.{file_type}"

            success = write_image(output_path, pixels, bit_depth, compression)
            if success:
                print(f"[NukeLinkWrite] Written: {output_path}")
            else:
                print(f"[NukeLinkWrite] Failed: {output_path}")

        last_frame_written = first_frame + batch_size - 1

        if is_sequence:
            preview_filename = pattern
        else:
            preview_filename = output_path

        return {
            "ui": {
                "nukelink_preview": [{
                    "filename": preview_filename,
                    "first_frame": first_frame,
                    "last_frame": last_frame_written,
                    "colorspace": colorspace,
                }]
            }
        }

# ============================================================================
# NukeLinkPathBuilder node
# ============================================================================

class NukeLinkPathBuilder:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "name":            ("STRING", {"default": "", "multiline": False, "placeholder": "e.g. Arm"}),
                "shot":            ("STRING", {"default": "", "multiline": False, "placeholder": "e.g. PN_010_030"}),
                "file_location":   ("STRING", {"default": "", "multiline": False, "placeholder": "e.g. E:/Shows/PathBuilder_Season1/Shots/PN_010_030/frmComfyUI/"}),
                "bypass_location": ("BOOLEAN", {"default": False}),
                "sequence_folder": ("BOOLEAN", {"default": True}),
                "version_append":  ("BOOLEAN", {"default": True}),
                "version_number":  ("STRING", {"default": "001"}),
                "version_iterate": ("BOOLEAN", {"default": True}),
                "version_delim":   ("STRING", {"default": "_"}),
                "frame_delim":     ("STRING", {"default": "."}),
                "nuke_port":       ("STRING", {"default": ""}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("file_path",)
    FUNCTION = "execute"
    CATEGORY = "NukeLink"
    OUTPUT_NODE = False

    def execute(self, name, shot, file_location, bypass_location, sequence_folder,
                version_append, version_number, version_iterate, version_delim, frame_delim, nuke_port):

        # Validate version_number - must be a non-negative integer string
        stripped = version_number.strip()
        if not stripped.isdigit():
            print("[NukeLinkPathBuilder] Invalid version_number, outputting blank path")
            return ("",)

        version_str = stripped.zfill(len(stripped))

        # Build the versioned name stem
        name_full = f"{shot}{version_delim}{name}" if shot else name
        if version_append:
            stem = f"{name_full}{version_delim}v{version_str}"
        else:
            stem = name_full

        # Build folder portion
        if bypass_location:
            folder = ""
        else:
            loc = file_location.rstrip("/\\")
            folder = loc + "/" if loc else ""

        # Assemble full path
        if sequence_folder:
            path = f"{folder}{stem}/{stem}{frame_delim}"
        else:
            path = f"{folder}{stem}{frame_delim}"

        print(f"[NukeLinkPathBuilder] Output path: {path}")
        return {"ui": {"nukelink_iterate": []}, "result": (path,)}


# ============================================================================
# Mappings
# ============================================================================

NODE_CLASS_MAPPINGS = {
    "Read - NukeLink":         NukeLinkRead,
    "Write - NukeLink":        NukeLinkWrite,
    "Path Builder - NukeLink": NukeLinkPathBuilder,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "Read - NukeLink":         "Read - NukeLink",
    "Write - NukeLink":        "Write - NukeLink",
    "Path Builder - NukeLink": "Path Builder - NukeLink",
}
