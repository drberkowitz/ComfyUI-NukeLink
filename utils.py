import glob
import os
import re
import shutil
from typing import List, Optional, Tuple

# ============================================================================
# utils.py - utility functions for NukeLink
# ============================================================================

ALLOWED_IMAGE_EXTENSIONS = {
    "exr", "tiff", "tif", "dpx", "hdr", "png", "jpeg", "jpg",
    "bmp", "tga", "psd", "ico", "rla", "sgi", "pnm", "ppm", "pgm",
    "pbm", "webp", "gif", "heic", "jp2", "jxr", "pic", "pcx", "im", "dib"
}

def resolve_file_path(path: str) -> str:
    import folder_paths
    stripped = path.strip()

    path_components = re.split(r"[/\\]", stripped)
    if ".." in path_components:
        print(f"[NukeLink] Rejected path containing '..' component: {stripped}")
        return ""

    if os.path.isabs(stripped):
        return stripped

    path = os.path.expandvars(os.path.expanduser(stripped))
    if not os.path.isabs(path):
        output_dir = folder_paths.get_output_directory()
        joined = os.path.join(output_dir, path)
        real_joined = os.path.realpath(joined)
        real_output = os.path.realpath(output_dir)
        if os.path.commonpath([real_output, real_joined]) != real_output:
            print(f"[NukeLink] Rejected relative path escaping output dir: {path}")
            return ""
        path = joined
        return path

    return path


def resolve_pathbuilder_path(name, shot, file_location, bypass_location,
                               sequence_folder, name_pattern, version_number,
                               frame_delim) -> str:
    stripped = version_number.strip()
    version_used = "{version}" in name_pattern or "{version}" in file_location

    if version_used:
        if not stripped.isdigit():
            return ""
        version_str = stripped
    else:
        version_str = ""

    def substitute(text):
        text = text.replace("{shot}", shot)
        text = text.replace("{name}", name)
        if "{version}" in text:
            text = text.replace("{version}", version_str)
        return text

    stem = substitute(name_pattern)
    if not stem:
        stem = name
    if not stem:
        return ""

    file_location = substitute(file_location)

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

    return path

# ============================================================================
# ffmpeg resolution
# ============================================================================

def _find_ffmpeg() -> Optional[str]:
    candidates = []

    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        candidates.append(get_ffmpeg_exe())
    except Exception:
        pass

    system = shutil.which("ffmpeg")
    if system:
        candidates.append(system)

    if os.path.isfile("ffmpeg"):
        candidates.append(os.path.abspath("ffmpeg"))
    if os.path.isfile("ffmpeg.exe"):
        candidates.append(os.path.abspath("ffmpeg.exe"))

    if not candidates:
        print("[NukeLink] No ffmpeg found. Video preview will be unavailable.")
        return None

    return candidates[0]

ffmpeg_path = _find_ffmpeg()

# ============================================================================
# Library detection
# ============================================================================

try:
    import OpenImageIO as oiio
    OIIO_AVAILABLE = True
except ImportError:
    oiio = None
    OIIO_AVAILABLE = False

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    CV2_AVAILABLE = False

try:
    from PIL import Image as PILImage
    PIL_AVAILABLE = True
except ImportError:
    PILImage = None
    PIL_AVAILABLE = False

# ============================================================================
# Sequence pattern utilities
# ============================================================================

def parse_frame_pattern(filepath: str, user_separator: str = "", file_type: str = "") -> Tuple[str, Optional[str], int]:
    filepath = filepath.replace("\\", "/")
    match = re.search(r"%(\d*)d", filepath)
    if match:
        padding = int(match.group(1)) if match.group(1) else 4
        return filepath, match.group(0), padding
    match = re.search(r"(#+)", filepath)
    if match:
        hashes = match.group(1)
        padding = len(hashes)
        pattern = filepath.replace(hashes, f"%0{padding}d")
        return pattern, hashes, padding
    if user_separator and file_type:
        base, _ = os.path.splitext(filepath)
        filepath = f"{base}{user_separator}####.{file_type}"
        hashes = "####"
        padding = 4
        pattern = filepath.replace(hashes, f"%0{padding}d")
        return pattern, hashes, padding
    match = re.search(r"(\d+)(\.[^.]+)$", filepath)
    if match:
        if os.path.isfile(filepath):
            return filepath, None, 0
        frame_str = match.group(1)
        padding = len(frame_str)
        ext = match.group(2)
        base = filepath[: match.start()]
        pattern = f"{base}%0{padding}d{ext}"
        return pattern, frame_str, padding
    return filepath, None, 0


def expand_frame_pattern(pattern: str, frame: int, padding: int = 4) -> str:
    if "%" in pattern:
        return pattern % frame
    if "#" in pattern:
        hashes = re.search(r"#+", pattern).group(0)
        return pattern.replace(hashes, str(frame).zfill(len(hashes)))
    return pattern


def detect_sequence(filepath: str) -> Tuple[str, List[int], int]:
    filepath = filepath.replace("\\", "/")
    pattern, frame_spec, padding = parse_frame_pattern(filepath)

    if frame_spec is None or padding == 0:
        if os.path.exists(filepath):
            return filepath, [0], 0
        return filepath, [], 0

    glob_pattern = re.sub(r"%\d*d", "*", pattern)
    glob_pattern = re.sub(r"#+", "*", glob_pattern)

    matching_files = glob.glob(glob_pattern)
    if not matching_files:
        return pattern, [], padding

    frames = []
    for f in matching_files:
        match = re.search(r"(\d+)\.[^.]+$", f)
        if match:
            frames.append(int(match.group(1)))

    frames.sort()
    return pattern, frames, padding

def resolve_loose_path(path: str) -> str:
    stem = path.rstrip("./\\")
    matches = glob.glob(stem + "*")
    matches = [
        m for m in matches
        if os.path.splitext(m)[1].lstrip(".").lower() in ALLOWED_IMAGE_EXTENSIONS
    ]
    if not matches:
        return path
    _, frame_spec, _ = parse_frame_pattern(path)
    if frame_spec is not None:
        return path
    for m in sorted(matches):
        base = os.path.basename(m)
        if any(c.isdigit() for c in base):
            return m
    return matches[0]


def resolve_loose_sequence_path(path: str) -> str:
    stem = path.rstrip("./\\")
    matches = glob.glob(stem + "*")
    matches = [
        m for m in matches
        if os.path.splitext(m)[1].lstrip(".").lower() in ALLOWED_IMAGE_EXTENSIONS
    ]
    if not matches:
        return path

    _, frame_spec, _ = parse_frame_pattern(path)
    if frame_spec is not None:
        return path

    digit_matches = []
    for m in sorted(matches):
        base = os.path.basename(m)
        frame_match = re.search(r"(\d+)(\.[^.]+)$", base)
        if frame_match:
            digit_matches.append((m, frame_match))

    if len(digit_matches) < 2:
        # Not a sequence, defer to single-file behaviour
        for m in sorted(matches):
            base = os.path.basename(m)
            if any(c.isdigit() for c in base):
                return m
        return matches[0]

    # Reconstruct a frame pattern from the first digit match, same
    # convention as parse_frame_pattern's trailing-digits branch.
    sample_path, sample_match = digit_matches[0]
    frame_str = sample_match.group(1)
    ext = sample_match.group(2)
    padding = len(frame_str)
    base_dir = os.path.dirname(sample_path)
    base_name = os.path.basename(sample_path)[: sample_match.start(1)]
    pattern = os.path.join(base_dir, f"{base_name}%0{padding}d{ext}") if base_dir else f"{base_name}%0{padding}d{ext}"
    return pattern.replace("\\", "/")

# ============================================================================
# Image reading
# ============================================================================

def read_image_oiio(filepath: str) -> Optional["np.ndarray"]:
    if not OIIO_AVAILABLE:
        return None
    try:
        import numpy as np
        config = oiio.ImageSpec()
        config.attribute("oiio:UnassociatedAlpha", 1)
        inp = oiio.ImageInput.open(filepath, config)
        if inp is None:
            print(f"[NukeLink] OIIO error: {oiio.geterror()}")
            return None
        spec = inp.spec()
        pixels = inp.read_image("float")
        inp.close()
        if pixels is None:
            return None
        pixels = np.array(pixels, dtype=np.float32)
        pixels = pixels.reshape(spec.height, spec.width, spec.nchannels)
        return pixels
    except Exception as e:
        print(f"[NukeLink] OIIO error reading {filepath}: {e}")
        return None


def read_image_cv2(filepath: str) -> Optional["np.ndarray"]:
    if not CV2_AVAILABLE:
        return None
    try:
        import numpy as np
        img = cv2.imread(filepath, cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
        if len(img.shape) == 3:
            if img.shape[2] == 4:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
            elif img.shape[2] == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if img.dtype == "uint8":
            img = img.astype(np.float32) / 255.0
        elif img.dtype == "uint16":
            img = img.astype(np.float32) / 65535.0
        else:
            img = img.astype(np.float32)
        return img
    except Exception as e:
        print(f"[NukeLink] cv2 error reading {filepath}: {e}")
        return None


def read_image_pil(filepath: str) -> Optional["np.ndarray"]:
    if not PIL_AVAILABLE:
        return None
    try:
        import numpy as np
        img = PILImage.open(filepath)
        raw = np.array(img)
        if raw.dtype == np.uint16:
            img = raw.astype(np.float32) / 65535.0
        else:
            img = raw.astype(np.float32) / 255.0
        if len(img.shape) == 2:
            img = img[:, :, np.newaxis]
        return img
    except Exception as e:
        print(f"[NukeLink] PIL error reading {filepath}: {e}")
        return None


def read_image(filepath: str) -> Optional["np.ndarray"]:
    if not os.path.exists(filepath):
        print(f"[NukeLink] File not found: {filepath}")
        return None
    if OIIO_AVAILABLE:
        img = read_image_oiio(filepath)
        if img is not None:
            return img
    if CV2_AVAILABLE:
        img = read_image_cv2(filepath)
        if img is not None:
            return img
    if PIL_AVAILABLE:
        img = read_image_pil(filepath)
        if img is not None:
            return img
    print(f"[NukeLink] No library could read: {filepath}")
    return None

# ============================================================================
# Image writing
# ============================================================================

def write_image_oiio(filepath: str, pixels: "np.ndarray", bit_depth: str = "16f", compression: str = "dwaa") -> bool:
    if not OIIO_AVAILABLE:
        return False
    try:
        import numpy as np
        height, width = pixels.shape[:2]
        channels = pixels.shape[2] if pixels.ndim > 2 else 1

        if bit_depth == "8":
            fmt = oiio.UINT8
            pixels_out = (np.clip(pixels, 0, 1) * 255).astype(np.uint8)
        elif bit_depth == "16":
            fmt = oiio.UINT16
            pixels_out = (np.clip(pixels, 0, 1) * 65535).astype(np.uint16)
        elif bit_depth == "16f":
            fmt = oiio.HALF
            pixels_out = pixels.astype(np.float16)
        elif bit_depth == "32f":
            fmt = oiio.FLOAT
            pixels_out = pixels.astype(np.float32)
        else:
            fmt = oiio.HALF
            pixels_out = pixels.astype(np.float16)

        pixels_out = np.ascontiguousarray(pixels_out)
        spec = oiio.ImageSpec(width, height, channels, fmt)

        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".exr":
            spec.attribute("compression", compression)
        elif ext in (".tif", ".tiff"):
            spec.attribute("compression", "zip")
        elif ext in (".jpg", ".jpeg"):
            spec.attribute("jpeg:quality", 95)

        out = oiio.ImageOutput.create(filepath)
        if out is None:
            print(f"[NukeLinkWrite] OIIO cannot create: {oiio.geterror()}")
            return False
        if not out.open(filepath, spec):
            print(f"[NukeLinkWrite] OIIO open failed: {out.geterror()}")
            return False
        if not out.write_image(pixels_out):
            print(f"[NukeLinkWrite] OIIO write failed: {out.geterror()}")
            out.close()
            return False
        out.close()
        return True
    except Exception as e:
        print(f"[NukeLinkWrite] OIIO error writing {filepath}: {e}")
        return False


def write_image_cv2(filepath: str, pixels: "np.ndarray", bit_depth: str = "16f") -> bool:
    if not CV2_AVAILABLE:
        return False
    try:
        import numpy as np
        if bit_depth == "8":
            pixels_out = (np.clip(pixels, 0, 1) * 255).astype(np.uint8)
        else:
            pixels_out = (np.clip(pixels, 0, 1) * 65535).astype(np.uint16)

        if pixels_out.shape[2] == 4:
            pixels_out = cv2.cvtColor(pixels_out, cv2.COLOR_RGBA2BGRA)
        elif pixels_out.shape[2] == 3:
            pixels_out = cv2.cvtColor(pixels_out, cv2.COLOR_RGB2BGR)

        return cv2.imwrite(filepath, pixels_out)
    except Exception as e:
        print(f"[NukeLinkWrite] cv2 error writing {filepath}: {e}")
        return False


def write_image_pil(filepath: str, pixels: "np.ndarray") -> bool:
    if not PIL_AVAILABLE:
        return False
    try:
        import numpy as np
        pixels_out = (np.clip(pixels, 0, 1) * 255).astype(np.uint8)
        if pixels_out.shape[2] == 1:
            pixels_out = pixels_out[:, :, 0]
        PILImage.fromarray(pixels_out).save(filepath)
        return True
    except Exception as e:
        print(f"[NukeLinkWrite] PIL error writing {filepath}: {e}")
        return False


def write_image(filepath: str, pixels: "np.ndarray", bit_depth: str = "16f", compression: str = "dwaa") -> bool:
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    if OIIO_AVAILABLE:
        if write_image_oiio(filepath, pixels, bit_depth, compression):
            return True
    if CV2_AVAILABLE:
        if write_image_cv2(filepath, pixels, bit_depth):
            return True
    if PIL_AVAILABLE:
        if write_image_pil(filepath, pixels):
            return True
    print(f"[NukeLinkWrite] No library could write: {filepath}")
    return False