# ComfyUI-NukeLink

![Version](https://img.shields.io/badge/version-0.1.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Nuke](https://img.shields.io/badge/Nuke-10%2B-yellow)
![Nuke Indie](https://img.shields.io/badge/Nuke%20Indie-supported-yellow)
![Python](https://img.shields.io/badge/python-2%2F3-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![ComfyUI Manager](https://img.shields.io/badge/ComfyUI%20Manager-coming%20soon-orange)

A bridge between Nuke and ComfyUI on the same machine, allowing you to send Read nodes from Nuke directly into ComfyUI and return rendered outputs back to Nuke as Read nodes.

![Hero Shot](https://github.com/user-attachments/assets/d5d216bc-f877-4d7a-b0b3-949c4d1ca95d)

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
  - [ComfyUI Side](#comfyui-side)
  - [Nuke Side](#nuke-side)
  - [Configuration](#configuration)
- [Usage](#usage)
  - [Nuke to ComfyUI](#nuke-to-comfyui)
  - [ComfyUI to Nuke](#comfyui-to-nuke)
  - [ComfyUI Settings Panel](#comfyui-settings-panel)
- [Nodes](#nodes)
  - [Read - NukeLink](#read---nukelink)
  - [Write - NukeLink](#write---nukelink)
  - [Path Builder - NukeLink](#path-builder---nukelink)
- [Known Limitations](#known-limitations)
- [Acknowledgements](#acknowledgements)

---

## Features

- Send one or more Nuke Read nodes to ComfyUI with knob values intact: file path, colorspace, frame range, and missing frames mode
- Supports a wide range of file types including EXR, TIFF, DPX, PNG, JPG, TGA, and more
- Path Builder node dropped on canvas automatically, pre-populated with output location, and shot name
- Shot name and output location derived automatically from your Nuke script path and pipeline environment variables
- Supports multiple simultaneous Nuke instances, with each instance automatically assigned its own listener port
- Send ComfyUI outputs back to Nuke as Read nodes via right-click on any NukeLink - Write node
- Sequence and still image preview on Read and Write nodes with playback controls: show/hide, pause/resume, re-render, and sync
- Missing frames handling: black, hold, nearest, and error modes
- Colorspace support: raw, sRGB, linear, and ACEScg
- Open in Explorer directly from the node right-click menu
- Works with standard, portable, and desktop ComfyUI installs

---

## Requirements

- Nuke 10 or later (including Nuke Indie)
- ComfyUI local install: standard, portable, or desktop (not ComfyUI Cloud)
- ffmpeg (required for in node preview for sequences in ComfyUI)
- One of the following image libraries for reading and writing frames:
  - OpenImageIO (recommended)
  - OpenCV (cv2)
  - Pillow (PIL)

---

## Installation

### ComfyUI Side

1. Navigate to your ComfyUI `custom_nodes` folder
2. Clone this repo:
`git clone https://github.com/drberkowitz/ComfyUI-NukeLink.git`
3. Restart ComfyUI

### Nuke Side

1. Locate the `nuke/` folder inside this repo. It contains the following structure:
```
nuke/
├── menu.py
└── python/
    └── sendToComfyUI.py
```
2. Copy `sendToComfyUI.py` into the folder where you keep Python scripts inside your `.nuke` folder. The included `menu.py` assumes this is a folder called `python`, so the script would live at `.nuke/python/sendToComfyUI.py`. If you store scripts elsewhere, update the `nuke.pluginAddPath` line in `menu.py` to match your folder name.
3. If you do not have a `menu.py` in your `.nuke` folder, copy `menu.py` into the `.nuke` folder.
4. If you already have a `menu.py` in your `.nuke` folder, do not replace it. Add the following lines to your existing `menu.py`:
```python
   nuke.pluginAddPath( './python/' )
   
   import sendToComfyUI

   sendToComfyUI.start_listener()

   nodesMenu = nuke.menu('Nodes').addMenu("SendToComfyUI","")
   nodesMenu.addCommand("Send To ComfyUI", "sendToComfyUI.send_to_comfyui()", "")
```
5. If your pipeline uses an `init.nuke` file, it is recommended to move the `nuke.pluginAddPath` line there instead of keeping it in `menu.py`.
6. Restart Nuke

### Configuration

Open `sendToComfyUI.py` in a text editor. The config block near the top of the file is the primary section you will need to edit for your pipeline:

- `COMFYUI_HOST` - The address ComfyUI is running on. Default is `http://127.0.0.1:8188`. Change this if you are running ComfyUI on a different port.
- `LEVELS_UP` - How many folders to climb from your `.nk` script location to reach the shot root. For example, if your script lives at `E:/Shows/Project/Shots/SH010/nuke/scripts/SH010_comp_v001.nk`, set this to `2` to land at `E:/Shows/Project/Shots/SH010/`.
- `OUTPUT_SUBFOLDER` - The folder name appended after climbing. Default is `elements`. This becomes the base output location populated in the Path Builder node.
- `SHOT_ENV_VAR` - The name of the environment variable your pipeline uses to identify the current shot. NukeLink will look this up at runtime using `os.environ.get()`. For example, if your pipeline sets an environment variable called `SHOTGUN_SHOT` or `SHOW_SHOT`, put that name here. If the variable is not found in the environment, NukeLink will fall back to parsing the shot name from the script filename using `SHOT_VERSION_SEPARATOR`.
- `SHOT_VERSION_SEPARATOR` - The string in your script filename that separates the shot name from the version. Default is `"_comp_v"`. For example, `SH010_comp_v001.nk` would yield shot name `SH010`. Adjust this to match your naming convention.

---

## Usage

### Nuke to ComfyUI

1. In Nuke, select one or more Read nodes
2. Tab search for **Send To ComfyUI** or right click in the node graph and select it under the SendToComfyUI menu
3. An alert will pop up confirming the node was sent and asking you to switch to ComfyUI. A NukeLink - Read node will be dropped on the canvas for each selected Nuke Read node, pre-populated with file path, colorspace, frame range, and missing frames mode. A Path Builder node will also be created to the right, pre-populated with your output location, version number, and shot name.  The Path Builder node also includes the correct Nuke listener port so the Write node knows exactly where to send renders back to.

### ComfyUI to Nuke

1. In ComfyUI, right-click a Write node after the graph has been executed and image(s) have been written to disk
2. Select **Send to Nuke** from the context menu
3. Switch back to Nuke. A Read node will have dropped into the node graph pointing to the rendered output.

![ComfyUI Write node right-click context menu](https://github.com/user-attachments/assets/bb30a1af-10a2-4574-a307-2af047026d11)
![Toast notification](https://github.com/user-attachments/assets/3c35e73e-aa1a-454a-b20b-6c11e82615b1)

### ComfyUI Settings Panel

NukeLink has a settings section to ComfyUI's built-in settings panel, controlling default values for new nodes created directly in ComfyUI as well as preview behavior for Read and Write nodes.

Settings include defaults for:
- Preview visibility and playback on Read and Write nodes
- Missing frames behavior
- Colorspace
- File type, bit depth, and compression on Write nodes
- First frame number on Write nodes

---

## Nodes

### Read - NukeLink

| Widget | Description |
|---|---|
| `file_path` | Path to an image or sequence. Accepts `####` and `%04d` style frame padding patterns (e.g. `image.####.exr` or `image.%04d.exr`). |
| `first_frame` | First frame number to load from a sequence. |
| `last_frame` | Last frame number to load from a sequence. |
| `missing_frames` | How to handle missing frames in a sequence. Options: `black`, `hold`, `nearest`, `error`. |
| `colorspace` | The colorspace of the incoming image data. Options: `raw`, `sRGB`, `linear`, `ACEScg`. |

---

### Write - NukeLink

| Widget | Description |
|---|---|
| `file_path` | Output path for the rendered image or sequence. Accepts `####` and `%04d` style frame padding patterns. Without a pattern, single frames write as typed; multi-frame batches append the frame number automatically based off of `first_frame` (e.g. `image.png` becomes `image_1001.png`, `image_1002.png`) |
| `first_frame` | The frame number the output sequence starts at. |
| `file_type` | Output file format. Options: `exr`, `tiff`, `png`, `jpg`, `tga`, `bmp`. |
| `bit_depth` | Bit depth of the output file. Options: `8` and `16` (integer), `16f` and `32f` (floating point).|
| `compression` | Compression method for the output file. Only applies to EXR output. TIFF output always uses `zip` compression regardless of this setting. For all other file types this setting is ignored. Options: `none`, `rle`, `zip`, `zips`, `piz`, `pxr24`, `b44`, `b44a`, `dwaa`, `dwab`. |
| `colorspace` | The colorspace to encode the output image into. Options: `raw`, `sRGB`, `linear`, `ACEScg`. |

---

### Path Builder - NukeLink

The Path Builder constructs an output file path and passes it to a connected Write node. Plug its output directly into the `file_path` input of a Write node. It is designed to be dropped alongside Read nodes when sending from Nuke, with most fields pre-populated automatically. The Path Builder can also be used independently of the Nuke workflow as a general purpose path construction tool.

| Widget | Description |
|---|---|
| `name` | The base name of the output, typically describing the element (e.g. `Arm`, `Smoke`). |
| `shot` | The shot name, prepended to the output name when provided. |
| `file_location` | The root output folder. |
| `bypass_location` | When enabled, omits the `file_location` from the output path, allowing output to fall back to ComfyUI's default output folder. |
| `sequence_folder` | When enabled, wraps the output inside a subfolder named after the output stem. |
| `version_append` | When enabled, appends a version string to the output name (e.g. `_v001`). |
| `version_number` | The version number. Must be a numeric string. Highlighted in red when invalid. |
| `version_iterate` | When enabled, automatically increments the version number by one each time the graph executes. |
| `version_delim` | The delimiter used between name components such as shot, name, and version (e.g. `SH010_Arm_v001`). Default is `_`. |
| `frame_delim` | The character placed between the output stem and the frame padding. Default is `.`. |

---

## Known Limitations

- **Mac and Linux are untested.** NukeLink was designed with cross-platform support in mind, but could not be thoroughly tested beyond Windows.
- **Multiple Write nodes cannot be sent back to Nuke simultaneously.** Only one Write node at a time can be sent via the right-click Send to Nuke option.
- **Missing Viewer LUT in ComfyUI** Nuke applies a viewer LUT (commonly sRGB by default) on top of whatever colorspace a Read node is set to. ComfyUI does not have an equivalent viewer LUT. As a result, the same colorspace setting will produce visually different results between the two applications. This is a fundamental difference in how the two applications handle color display and is not something NukeLink can resolve automatically.

---

## Acknowledgements

**Nuke node logic** - [sumitchatterjee13](https://github.com/sumitchatterjee13/nuke-nodes-comfyui) for the foundational Nuke node approach this tool builds on.

**Preview logic** - [kosinkadink](https://github.com/kosinkadink/ComfyUI-VideoHelperSuite) for the ComfyUI video preview approach referenced in building the NukeLink preview system.

---

*ComfyUI-NukeLink was developed by Daniel Berkowitz. The majority of the code was written with the assistance of [Claude](https://claude.ai)*