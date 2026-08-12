import asyncio
import io
import os
import shutil
import socket
import subprocess
import json
import uuid

import numpy as np
from PIL import Image as PILImage

import folder_paths
import server

from .utils import (
    ffmpeg_path,
    parse_frame_pattern,
    expand_frame_pattern,
    detect_sequence,
    read_image,
    resolve_loose_path,
    resolve_loose_sequence_path,
    resolve_pathbuilder_path,
    resolve_file_path,
)

# ============================================================================
# server.py - HTTP endpoints for NukeLink
# ============================================================================

web = server.web

@server.PromptServer.instance.routes.post("/nukelink/receive")
async def nukelink_receive(request):
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="invalid JSON")

    reads = data.get("reads", [])
    if not reads:
        return web.Response(status=400, text="missing reads")

    server.PromptServer.instance.send_sync("nukelink.receive", {
        "reads":             reads,
        "file_location":     data.get("file_location", ""),
        "name_pattern":      data.get("name_pattern", ""),
        "version_number":    data.get("version_number", "01"),
        "frame_delim":       data.get("frame_delim", None),
        "shot":              data.get("shot", ""),
        "send_path_builder": data.get("send_path_builder", True),
        "nuke_port":         data.get("nuke_port", None),
        "template_workflow": data.get("template_workflow", None),
    })

    return web.Response(status=200, text="ok")

# ============================================================================
# /nukelink/sendtonuke
# ============================================================================

@server.PromptServer.instance.routes.post("/nukelink/resolvepath")
async def nukelink_resolve_path(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)

    path = resolve_pathbuilder_path(
        data.get("name", ""),
        data.get("shot", ""),
        data.get("file_location", ""),
        data.get("bypass_location", False),
        data.get("sequence_folder", True),
        data.get("name_pattern", "{shot}_{name}_v{version}"),
        data.get("version_number", ""),
        data.get("frame_delim", "."),
    )

    if not path:
        return web.json_response({"error": "invalid version_number"}, status=422)

    return web.json_response({"path": path})


@server.PromptServer.instance.routes.post("/nukelink/sendtonuke")
async def nukelink_send_to_nuke(request):
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="invalid JSON")

    nuke_port = data.get("nuke_port")
    if not nuke_port:
        return web.Response(status=400, text="missing nuke_port")

    file_path = data.get("file_path", "")

    file_path = resolve_file_path(file_path)
    if not file_path:
        print("[NukeLink] sendtonuke rejected: invalid or unsafe path")
        return web.Response(status=403, text="invalid or unsafe path")

    file_path = resolve_loose_sequence_path(file_path)

    provided_first = data.get("first_frame")
    provided_last = data.get("last_frame")

    if provided_first is not None and provided_last is not None:
        try:
            first_frame = int(provided_first)
            last_frame = int(provided_last)
        except (ValueError, TypeError):
            provided_first = provided_last = None

    if provided_first is None or provided_last is None:
        _, frame_spec, _ = parse_frame_pattern(file_path)

        if frame_spec is None:
            if not os.path.isfile(file_path):
                return web.Response(status=404, text="file not found: {}".format(file_path))
            first_frame = 0
            last_frame = 0
        else:
            _, found_frames, _ = detect_sequence(file_path)
            if not found_frames:
                return web.Response(status=404, text="no frames found for: {}".format(file_path))
            first_frame = min(found_frames)
            last_frame = max(found_frames)

    payload = json.dumps({
        "file_path":   file_path.replace("\\", "/"),
        "first_frame": first_frame,
        "last_frame":  last_frame,
        "colorspace":  data.get("colorspace", "raw"),
    }).encode("utf-8")

    try:
        response = await asyncio.to_thread(_send_to_nuke_socket, int(nuke_port), payload)
    except Exception as e:
        return web.Response(status=502, text="failed to reach Nuke: {}".format(str(e)))

    return web.Response(status=200, text=response)


@server.PromptServer.instance.routes.get("/nukelink/pingport")
async def nukelink_ping_port(request):
    try:
        port = int(request.rel_url.query.get("port", 0))
    except ValueError:
        return web.Response(status=400, text="invalid port")

    if not (54321 <= port <= 54330):
        return web.Response(status=400, text="port out of range")

    def _try_connect(p):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", p))
            s.close()
            return True
        except OSError:
            return False

    found = await asyncio.to_thread(_try_connect, port)
    if found:
        return web.Response(status=200, text="ok")
    return web.Response(status=404, text="no listener")


@server.PromptServer.instance.routes.post("/nukelink/openinfolder")
async def nukelink_open_in_folder(request):
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="invalid JSON")

    path = data.get("path", "").strip()
    if not path:
        return web.Response(status=400, text="missing path")

    path = resolve_file_path(path)
    if not path:
        print("[NukeLink] openinfolder rejected: invalid or unsafe path")
        return web.Response(status=403, text="invalid or unsafe path")

    widget_file_type = data.get("file_type")
    widget_first_frame = data.get("first_frame")

    select_path = None

    if widget_file_type and widget_first_frame is not None:
        # Exact construction from widget values, no glob-guessing.
        base, _ = os.path.splitext(path.rstrip("./\\"))
        pattern, frame_spec, padding = parse_frame_pattern(path)
        is_sequence = frame_spec is not None and padding > 0

        if is_sequence:
            try:
                exact_frame = int(widget_first_frame)
                candidate = expand_frame_pattern(pattern, exact_frame, padding)
                candidate = os.path.normpath(candidate)
                if os.path.isfile(candidate):
                    select_path = candidate
            except (ValueError, TypeError):
                pass
        else:
            candidate = "{}.{}".format(base, widget_file_type)
            candidate = os.path.normpath(candidate)
            if os.path.isfile(candidate):
                select_path = candidate
    else:
        path = resolve_loose_path(path)
        _, frame_spec, padding = parse_frame_pattern(path)
        is_sequence = frame_spec is not None and padding > 0

        if is_sequence:
            _, found_frames, _ = detect_sequence(path)
            if found_frames:
                first_frame = min(found_frames)
                _, frame_spec, padding = parse_frame_pattern(path)
                select_path = expand_frame_pattern(path.replace("\\", "/"), first_frame, padding)
                select_path = os.path.normpath(select_path)
        else:
            if os.path.isfile(path):
                select_path = os.path.normpath(path)

    folder = os.path.dirname(select_path) if select_path else (
        os.path.normpath(path) if os.path.isdir(path) else os.path.dirname(os.path.normpath(path))
    )

    if not os.path.isdir(folder):
        return web.Response(status=404, text="folder not found: {}".format(folder))

    if folder.rstrip("/\\").lower().endswith(".app"):
        print(f"[NukeLink] openinfolder rejected: refusing to open .app bundle: {folder}")
        return web.Response(status=403, text="refusing to open an application bundle")

    import sys
    import subprocess
    try:
        if sys.platform == "win32":
            if select_path and os.path.isfile(select_path):
                subprocess.Popen(["explorer", "/select,", select_path])
            else:
                subprocess.Popen(["explorer", folder])
        elif sys.platform == "darwin":
            if select_path and os.path.isfile(select_path):
                subprocess.Popen(["open", "-R", select_path])
            else:
                subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception as e:
        return web.Response(status=500, text="failed to open folder: {}".format(str(e)))

    return web.Response(status=200, text="ok")

@server.PromptServer.instance.routes.get("/nukelink/fileexists")
async def nukelink_file_exists(request):
    path = request.rel_url.query.get("path", "").strip()
    if not path:
        return web.Response(status=400, text="missing path")

    path = resolve_file_path(path)
    if not path:
        print("[NukeLink] fileexists rejected: invalid or unsafe path")
        return web.Response(status=403, text="invalid or unsafe path")

    path = resolve_loose_sequence_path(path)
    _, frame_spec, padding = parse_frame_pattern(path)
    is_sequence = frame_spec is not None and padding > 0

    if is_sequence:
        _, found_frames, _ = detect_sequence(path)
        if found_frames:
            return web.Response(status=200, text="ok")
        return web.Response(status=404, text="no frames found")
    else:
        if os.path.isfile(path):
            return web.Response(status=200, text="ok")
        return web.Response(status=404, text="file not found")

def _send_to_nuke_socket(port, payload, timeout=5.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(("127.0.0.1", port))
    s.sendall(payload)
    response = s.recv(4096)
    s.close()
    return response.decode("utf-8")

# ============================================================================
# /nukelink/viewvideo
# ============================================================================

@server.PromptServer.instance.routes.get("/nukelink/viewvideo")
async def nukelink_view_video(request):
    query = request.rel_url.query

    if ffmpeg_path is None:
        return web.Response(status=500, text="ffmpeg not found")

    filename = query.get("filename")
    if not filename:
        return web.Response(status=400, text="missing filename")

    try:
        first_frame = int(query.get("first_frame", 0))
        last_frame  = int(query.get("last_frame",  0))
    except ValueError:
        return web.Response(status=400, text="invalid frame range")

    colorspace    = query.get("colorspace", "sRGB")
    missing_frames = query.get("missing_frames", "black")

    filename = filename.replace("\\", "/")

    pattern, frame_spec, padding = parse_frame_pattern(filename)

    if frame_spec is None or padding == 0:
        return web.Response(status=400, text="filename is not a sequence pattern")

    _, all_frames, _ = detect_sequence(filename)
    all_frames_set = set(all_frames)

    # Build the full frame list respecting missing_frames mode
    frames_to_write = []
    last_valid_path = None

    for f in range(first_frame, last_frame + 1):
        path = os.path.abspath(expand_frame_pattern(pattern, f, padding))
        if f in all_frames_set:
            frames_to_write.append(("file", path))
            last_valid_path = path
        else:
            if missing_frames == "hold" and last_valid_path:
                frames_to_write.append(("file", last_valid_path))
            elif missing_frames == "nearest" and all_frames:
                nearest = min(all_frames, key=lambda x: abs(x - f))
                nearest_path = os.path.abspath(
                    expand_frame_pattern(pattern, nearest, padding)
                )
                frames_to_write.append(("file", nearest_path))
            elif missing_frames == "error":
                frames_to_write.append(("error", f))
            else:
                # black
                frames_to_write.append(("black", f))

    if not frames_to_write:
        return web.Response(status=204)

    request_id = uuid.uuid4().hex[:8]

    # Generate placeholder images if needed (black or error frames)
    needs_placeholders = any(t in ("black", "error") for t, _ in frames_to_write)
    placeholder_dir = None
    black_path = None
    error_paths = {}

    if needs_placeholders:
        from PIL import ImageDraw

        placeholder_dir = os.path.join(
            folder_paths.get_temp_directory(), "nukelink_placeholders_{}".format(request_id)
        )
        os.makedirs(placeholder_dir, exist_ok=True)

        # Derive frame size from first real frame
        ref_path = next((p for t, p in frames_to_write if t == "file"), None)
        if ref_path:
            ref = read_image(ref_path)
            h, w = (ref.shape[0], ref.shape[1]) if ref is not None else (540, 960)
        else:
            h, w = 540, 960

        # Black frame
        black_arr = np.zeros((h, w, 3), dtype=np.uint8)
        black_path = os.path.join(placeholder_dir, "black.png")
        PILImage.fromarray(black_arr).save(black_path)

        # Font - proportionate to frame width, Pillow 10.1+ supports size param
        font_size = max(12, w // 30)
        try:
            from PIL import ImageFont
            font = ImageFont.load_default(size=font_size)
        except TypeError:
            # Pillow < 10.1 - load_default takes no size argument
            font = ImageFont.load_default()

        # Error frames
        for t, val in frames_to_write:
            if t == "error":
                frame_num = val
                err_arr = np.zeros((h, w, 3), dtype=np.uint8)
                err_arr[:, :, 0] = 180
                err_img = PILImage.fromarray(err_arr)
                draw = ImageDraw.Draw(err_img)
                text = f"MISSING FRAME {frame_num}"
                # Centre the text
                try:
                    bbox = draw.textbbox((0, 0), text, font=font)
                    text_w = bbox[2] - bbox[0]
                    text_h = bbox[3] - bbox[1]
                except AttributeError:
                    # Pillow < 8 fallback
                    text_w, text_h = draw.textsize(text, font=font)
                x = (w - text_w) // 2
                y = (h - text_h) // 2
                draw.text((x, y), text, fill=(255, 255, 255), font=font)
                err_path = os.path.join(placeholder_dir, f"error_{frame_num}.png")
                err_img.save(err_path)
                error_paths[frame_num] = err_path

    needs_colorspace = colorspace in ("sRGB", "ACEScg")
    processed_cache = {}

    def get_processed_path(src_path):
        if src_path in processed_cache:
            return processed_cache[src_path]
        img = read_image(src_path)
        if img is None:
            return src_path

        if img.ndim == 2:
            img = np.stack([img, img, img], axis=-1)
        elif img.shape[2] == 1:
            img = np.concatenate([img, img, img], axis=-1)
        elif img.shape[2] == 4:
            img = img[:, :, :3]

        if colorspace == "sRGB":
            img = np.clip(img, 0.0, 1.0)
        elif colorspace == "ACEScg":
            img = img / (img + 1.0)
            img = np.clip(img, 0.0, 1.0)
        elif colorspace == "linear":
            lum = 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]
            lum = lum[..., np.newaxis]
            lum_mapped = lum / (lum + 1.0)
            scale = np.where(lum > 1e-6, lum_mapped / lum, 1.0)
            img = np.clip(img * scale, 0.0, 1.0)
        else:
            # raw - clamp only, no tone mapping
            img = np.clip(img, 0.0, 1.0)

        img_uint8 = (img * 255.0).astype(np.uint8)
        out_name = os.path.basename(src_path) + "_preview.png"
        out_path = os.path.join(opaque_dir, out_name)
        PILImage.fromarray(img_uint8, mode="RGB").save(out_path)
        processed_cache[src_path] = out_path
        return out_path

    # Write ffconcat
    os.makedirs(folder_paths.get_temp_directory(), exist_ok=True)
    concat_path = os.path.join(
        folder_paths.get_temp_directory(), "nukelink_preview.txt"
    )

    opaque_dir = os.path.join(
        folder_paths.get_temp_directory(), "nukelink_processed_{}".format(request_id)
    )
    os.makedirs(opaque_dir, exist_ok=True)

    def ensure_opaque(src_path):
        img = read_image(src_path)
        if img is None:
            return src_path
        if img.ndim == 2:
            img = np.stack([img, img, img], axis=-1)
        elif img.shape[2] == 1:
            img = np.concatenate([img, img, img], axis=-1)
        rgb = (img[:, :, :3] * 255.0).astype(np.uint8)
        alpha = np.full((*rgb.shape[:2], 1), 255, dtype=np.uint8)
        img_uint8 = np.concatenate([rgb, alpha], axis=-1)
        out_name = os.path.basename(src_path) + "_opaque.png"
        out_path = os.path.join(opaque_dir, out_name)
        PILImage.fromarray(img_uint8, mode="RGBA").save(out_path)
        return out_path

    def build_concat_entries():
        results = []
        for entry_type, val in frames_to_write:
            if entry_type == "file":
                src = get_processed_path(val) if needs_colorspace else val
            elif entry_type == "black":
                src = black_path
            elif entry_type == "error":
                src = error_paths[val]
            opaque = ensure_opaque(src)
            results.append(opaque.replace("\\", "/").replace("'", "\\'"))
        return results

    print("[NukeLink DEBUG] about to build concat entries (thread)")
    opaque_paths = await asyncio.to_thread(build_concat_entries)
    print("[NukeLink DEBUG] concat entries built, count:", len(opaque_paths))
    with open(concat_path, "w") as f:
        f.write("ffconcat version 1.0\n")
        for write_path in opaque_paths:
            f.write(f"file '{write_path}'\n")
            f.write("duration 0.125\n")

    args = [
        ffmpeg_path,
        "-v", "error",
        "-safe", "0",
        "-stream_loop", "-1",
        "-i", concat_path,
        "-c:v", "libvpx-vp9",
        "-deadline", "realtime",
        "-cpu-used", "8",
        "-f", "webm",
        "-",
    ]

    print("[NukeLink DEBUG] about to launch ffmpeg subprocess")
    resp = web.StreamResponse()
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
        print("[NukeLink DEBUG] ffmpeg subprocess launched, pid:", proc.pid)
        try:
            resp.content_type = "video/webm"
            await resp.prepare(request)
            print("[NukeLink DEBUG] response prepared, entering read loop")
            chunk_count = 0
            while True:
                chunk = await proc.stdout.read(2 ** 20)
                if not chunk:
                    break
                chunk_count += 1
                await resp.write(chunk)
            print("[NukeLink DEBUG] read loop exited normally, chunks written:", chunk_count)
            await proc.wait()
            print("[NukeLink DEBUG] ffmpeg process exited, returncode:", proc.returncode)
        except (ConnectionResetError, ConnectionError):
            print("[NukeLink DEBUG] caught ConnectionResetError/ConnectionError, killing ffmpeg")
            proc.kill()
    except BrokenPipeError:
        print("[NukeLink DEBUG] caught BrokenPipeError")
        pass
    finally:
        for _dir in (placeholder_dir, opaque_dir):
            if _dir and os.path.isdir(_dir):
                shutil.rmtree(_dir, ignore_errors=True)

    return resp

# ============================================================================
# /nukelink/viewimage
# ============================================================================

@server.PromptServer.instance.routes.get("/nukelink/viewimage")
async def nukelink_view_image(request):
    query = request.rel_url.query

    filename = query.get("filename")
    if not filename:
        return web.Response(status=400, text="missing filename")

    filename = filename.replace("\\", "/")

    if not os.path.isfile(filename):
        return web.Response(status=204)

    try:
        img = await asyncio.to_thread(read_image, filename)
    except Exception as e:
        print(f"[NukeLink] viewimage read error: {e}")
        return web.Response(status=500)

    if img is None:
        return web.Response(status=500, text="could not read image")

    try:
        # Ensure RGB - drop alpha if present
        if img.ndim == 2:
            img = np.stack([img, img, img], axis=-1)
        elif img.shape[2] == 1:
            img = np.concatenate([img, img, img], axis=-1)
        elif img.shape[2] == 4:
            img = img[:, :, :3]

        # Tone map: simple exposure + clamp so EXR/HDR is viewable
        # Multiply by a modest stop to lift midtones, then clamp to 0-1
        img = np.clip(img * 0.8, 0.0, 1.0)

        # Convert to uint8
        img_uint8 = (img * 255.0).astype(np.uint8)

        pil_img = PILImage.fromarray(img_uint8, mode="RGB")
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=85)
        buf.seek(0)

        return web.Response(
            body=buf.read(),
            content_type="image/jpeg",
        )

    except Exception as e:
        print(f"[NukeLink] viewimage encode error: {e}")
        return web.Response(status=500)