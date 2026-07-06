import nuke
import os
import re
import json
import socket
import threading

try:
    import urllib2
    def http_post(url, payload):
        req = urllib2.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        response = urllib2.urlopen(req)
        return response.read()
except ImportError:
    import urllib.request
    def http_post(url, payload):
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        response = urllib.request.urlopen(req)
        return response.read()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
COMFYUI_HOST = "http://127.0.0.1:8188"

# Path Builder output location is derived from the Nuke script's location.
# LEVELS_UP controls how many folders to climb from the .nk file.
# OUTPUT_SUBFOLDER is the folder name appended after climbing.
#
# Example - script at:
#   E:\Shows\BigProject\Shots\BP_303_003\nuke\scripts\BP_303_003_comp_v001.nk
# With LEVELS_UP = 2 and OUTPUT_SUBFOLDER = "elements":
#   E:\Shows\BigProject\Shots\BP_303_003\elements\
#
# If your scripts folder sits one level deep (no "scripts" subfolder):
#   E:\Shows\BigProject\Shots\BP_303_003\nuke\BP_303_003_comp_v001.nk
# Set LEVELS_UP = 1 instead.

LEVELS_UP = 1
OUTPUT_SUBFOLDER = "elements"
LISTENER_PORT_START = 54321
LISTENER_PORT_RANGE = 10

# Shot name derivation
# Set SHOT_ENV_VAR to the environment variable your pipeline uses for shot name.
# Set SHOT_VERSION_SEPARATOR to the string that separates shot name from the rest
# of the script filename (e.g. "_v", "-v", "_comp_v", "_nukeScript_v").
SHOT_ENV_VAR = "SHOT"
SHOT_VERSION_SEPARATOR = "_comp_v"
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {
    "exr", "tiff", "tif", "dpx", "hdr", "png", "jpeg", "jpg",
    "bmp", "tga", "psd", "ico", "rla", "sgi", "pnm", "ppm", "pgm",
    "pbm", "webp", "gif", "heic", "jp2", "jxr", "pic", "pcx", "im", "dib"
}

ALLOWED_COLORSPACES = {"raw", "sRGB", "linear", "ACEScg"}

def _derive_file_location():
    """Climb LEVELS_UP from the .nk script location and append OUTPUT_SUBFOLDER."""
    script_path = nuke.root().name()
    if not script_path or script_path == "Root":
        return ""
    base = os.path.dirname(os.path.abspath(script_path))
    for _ in range(LEVELS_UP):
        parent = os.path.dirname(base)
        if parent == base:
            break
        base = parent
    result = os.path.join(base, OUTPUT_SUBFOLDER, "").replace("\\", "/")
    return result


def _derive_version(script_path):
    """Extract version digits from the .nk filename. Returns e.g. '001' or '01'. Fallback: '01'."""
    filename = os.path.basename(script_path)
    match = re.search(r'v(\d{2,3})(?=\D|$)', filename, re.IGNORECASE)
    if match:
        return match.group(1)
    return "01"


def _derive_frame_delim(file_path):
    """Extract the character immediately before the frame pattern in the file path.
    Handles #### and %04d style patterns. Returns None if not found (leave widget default)."""
    match = re.search(r'(.)(?:#+|%\d+d)', file_path)
    if match:
        return match.group(1)
    return None


def _derive_shot(script_path):
    """Derive shot name from environment variable or script filename."""
    env_val = os.environ.get(SHOT_ENV_VAR, "").strip()
    if env_val:
        return env_val
    if not script_path or script_path == "Root":
        return ""
    filename = os.path.splitext(os.path.basename(script_path))[0]
    sep = SHOT_VERSION_SEPARATOR
    idx = filename.lower().find(sep.lower())
    if idx > 0:
        return filename[:idx]
    return ""


def send_to_comfyui():
    selected = nuke.selectedNodes()
    if not selected:
        nuke.message("No node selected.\n\nPlease select one or more Read nodes.")
        return

    read_nodes = [n for n in selected if n.Class() == "Read"]
    if not read_nodes:
        nuke.message("No Read nodes in selection.\n\nPlease select one or more Read nodes.")
        return

    script_path = nuke.root().name()
    file_location = _derive_file_location()
    version_number = _derive_version(script_path) if script_path and script_path != "Root" else "01"

    reads = []
    skipped = []

    for node in read_nodes:
        file_path = node["file"].value()
        if not file_path:
            skipped.append("{} (no file path)".format(node.name()))
            continue

        ext = os.path.splitext(file_path)[1].lstrip(".").lower()
        if ext not in ALLOWED_EXTENSIONS:
            skipped.append("{} (unsupported type .{})".format(node.name(), ext))
            continue

        if node["raw"].value():
            colorspace = "raw"
        else:
            colorspace_val = node["colorspace"].value()
            if colorspace_val in ALLOWED_COLORSPACES:
                colorspace = colorspace_val
            else:
                cs_lower = colorspace_val.lower()
                if "acescg" in cs_lower:
                    colorspace = "ACEScg"
                elif "srgb" in cs_lower:
                    colorspace = "sRGB"
                elif "linear" in cs_lower:
                    colorspace = "linear"
                else:
                    colorspace = "raw"

        first_frame    = int(node["first"].value())
        last_frame     = int(node["last"].value())
        missing_frames = node["on_error"].value()
        if missing_frames not in {"error", "black", "hold", "nearest"}:
            missing_frames = "black"

        reads.append({
            "file_path":      file_path,
            "first_frame":    first_frame,
            "last_frame":     last_frame,
            "colorspace":     colorspace,
            "missing_frames": missing_frames,
        })

    if not reads:
        nuke.message("No valid Read nodes to send.")
        return

    if not _listener_port:
        nuke.message("NukeLink listener is not running.\n\nRestart Nuke and try again.")
        return

    frame_delim = None
    for r in reads:
        frame_delim = _derive_frame_delim(r["file_path"])
        if frame_delim:
            break

    shot = _derive_shot(script_path)

    payload = json.dumps({
        "reads": reads,
        "file_location": file_location,
        "version_number": version_number,
        "frame_delim": frame_delim,
        "shot": shot,
        "send_path_builder": True,
        "nuke_port": _listener_port,
    }).encode("utf-8")

    try:
        http_post(COMFYUI_HOST + "/nukelink/receive", payload)
        msg = "{} Read node{} sent to ComfyUI. Switch to ComfyUI to see the node{} on the canvas.".format(
            len(reads),
            "s" if len(reads) != 1 else "",
            "s" if len(reads) != 1 else "",
        )
        if skipped:
            msg += "\n\nSkipped:\n" + "\n".join(skipped)
        nuke.message(msg)
    except Exception as e:
        nuke.message("Failed to send to ComfyUI:\n{}".format(str(e)))

# ---------------------------------------------------------------------------
# ComfyUI -> Nuke listener
# ---------------------------------------------------------------------------

def _create_read_node(params, result_holder):
    try:
        n = nuke.nodes.Read(
            file=params.get("file_path", ""),
            first=params.get("first_frame", 1001),
            last=params.get("last_frame", 1001),
        )
        colorspace = params.get("colorspace")
        if colorspace:
            try:
                if colorspace == "raw":
                    n["raw"].setValue(True)
                else:
                    n["colorspace"].setValue(colorspace)
            except Exception:
                pass
        result_holder["result"] = "OK"
    except Exception as e:
        result_holder["result"] = "ERROR: {}".format(str(e))


def _handle_client(conn):
    try:
        data = conn.recv(65536)
        payload = json.loads(data.decode("utf-8"))

        result_holder = {}
        nuke.executeInMainThreadWithResult(_create_read_node, args=(payload, result_holder))

        conn.sendall(result_holder.get("result", "NO RESULT").encode("utf-8"))
    except Exception as e:
        try:
            conn.sendall("ERROR: {}".format(str(e)).encode("utf-8"))
        except Exception:
            pass
    finally:
        conn.close()


def _server_loop(sock):
    while True:
        conn, addr = sock.accept()
        threading.Thread(target=_handle_client, args=(conn,), daemon=True).start()

_listener_port = None

def start_listener():
    global _listener_port
    for port in range(LISTENER_PORT_START, LISTENER_PORT_START + LISTENER_PORT_RANGE):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            s.listen(5)
            threading.Thread(target=_server_loop, args=(s,), daemon=True).start()
            _listener_port = port
            print("[NukeLink] listener started on port {}".format(port))
            return port
        except OSError:
            continue
    print("[NukeLink] could not start listener, no available port in range")
    return None
