# ComfyUI-NukeLink

![Version](https://img.shields.io/badge/version-0.2.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Nuke](https://img.shields.io/badge/Nuke-10%2B-yellow)
![Nuke Indie](https://img.shields.io/badge/Nuke%20Indie-supported-yellow)
![Python](https://img.shields.io/badge/python-2%2F3-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![ComfyUI Manager](https://img.shields.io/badge/ComfyUI%20Manager-coming%20soon-orange)

A bridge between Nuke and ComfyUI on the same machine, allowing you to send Read nodes from Nuke directly into ComfyUI and return rendered outputs back to Nuke as Read nodes.

![Hero Shot](https://github.com/user-attachments/assets/d5d216bc-f877-4d7a-b0b3-949c4d1ca95d)

---

## 📚 Table of Contents

- [✨ Features](#-features)
- [📋 Requirements](#-requirements)
- [🛠️ Installation](#️-installation)
  - [ComfyUI Side](#comfyui-side)
  - [Nuke Side](#nuke-side)
  - [Configuration](#configuration)
- [🚀 Usage](#-usage)
  - [➡️ Nuke to ComfyUI](#-nuke-to-comfyui)
  - [⬅️ ComfyUI to Nuke](#-comfyui-to-nuke)
  - [🧱 Working with Templates](#-working-with-templates)
  - [ComfyUI Settings Panel](#comfyui-settings-panel)
- [🧩 Nodes](#-nodes)
  - [Read - NukeLink](#read---nukelink)
  - [Write - NukeLink](#write---nukelink)
  - [Path Builder - NukeLink](#path-builder---nukelink)
- [⚠️ Known Limitations](#️-known-limitations)
- [🙏 Acknowledgements](#-acknowledgements)

---

## ✨ Features

- Send one or more Nuke Read nodes to ComfyUI with knob values intact: file path, colorspace, frame range, and missing frames mode
- Skip rebuilding the same ComfyUI graph over and over, pick a saved workflow template right from the Nuke send dialog.
- Supports a wide range of file types including EXR, TIFF, DPX, PNG, JPG, TGA, and more
- Path Builder node dropped on canvas automatically, pre-populated with output location, and shot name
- Shot name and output location derived automatically from your Nuke script path and pipeline environment variables
- Supports multiple simultaneous Nuke instances, with each instance automatically assigned its own listener port
- Turn an executed Write node into a new Read node with one right-click, no need to copy and paste file paths.
- Send ComfyUI outputs back to Nuke as Read nodes via right-click on any NukeLink - Write node
- Sequence and still image preview on Read and Write nodes with playback controls: show/hide, pause/resume, re-render, and sync
- Missing frames handling: black, hold, nearest, and error modes
- Colorspace support: raw, sRGB, linear, and ACEScg
- Open in Explorer directly from the node right-click menu
- Works with standard, portable, and desktop ComfyUI installs

---

## 📋 Requirements

- Nuke 10 or later (including Nuke Indie)
- ComfyUI local install: standard, portable, or desktop (not ComfyUI Cloud)
- ffmpeg (required for in node preview for sequences in ComfyUI)
- One of the following image libraries for reading and writing frames:
  - OpenImageIO (recommended)
  - OpenCV (cv2)
  - Pillow (PIL)

---

## 🛠️ Installation

### ComfyUI Side

1. Navigate to your ComfyUI `custom_nodes` folder
2. Clone this repo:
`git clone https://github.com/drberkowitz/ComfyUI-NukeLink.git`
3. Restart ComfyUI

### Nuke Side

1. Locate the `SendToComfy-NukeLink/` folder inside this repo. It contains the following structure:
```
SendToComfy-NukeLink/
├── menu.py
└── sendToComfyUI.py
```
2. Copy the whole `SendToComfy-NukeLink` folder into your `.nuke` folder.
3. Add the following line to your `.nuke/init.py` (`menu.py` will work as well, but isn't recommended):

```python
nuke.pluginAddPath('./SendToComfy-NukeLink')
```

4. Before restarting Nuke, continue to the [Configuration](#configuration) section below and edit `sendToComfyUI.py` to match your pipeline.
5. Restart Nuke.

Once Nuke restarts, you'll find the command under **Edit > Node > Send To ComfyUI**, and via Tab search or **Nodes > Other > Send To ComfyUI**. A keyboard shortcut can be set by editing the commented-out example near the top of `SendToComfy-NukeLink/menu.py`.

### Configuration

Open `sendToComfyUI.py` in a text editor. The config block near the top of the file is the primary section you will need to edit for your pipeline.

- `COMFYUI_HOST` - The address ComfyUI is running on. Default is `http://127.0.0.1:8188`. Change this if you are running ComfyUI on a different port.

NukeLink uses a shared token system to fill in shot names, show names, version numbers, output locations, and workflow templates automatically. `SCRIPT_PATH_PATTERNS` is where these tokens come from, and `OUTPUT_LOCATION`, `NAME_PATTERN`, and `WORKFLOW_FOLDERS` are where they get used.

- `SCRIPT_PATH_PATTERNS` - An ordered list of patterns matched against your current `.nk` script's file path, used to pull out tokens like `{shot}`, `{show}`, and `{version}` automatically. Patterns are tried in order from top to bottom, and the first one that matches is used. Write `{`token`}` to capture a piece of the path (like a folder or filename segment), and `...` to skip over a stretch of path you don't care about, such as a drive letter or a run of parent folders. There must always be a real character, like `/` or `_`, between two tokens sitting next to each other, `{shot}{version}` on its own isn't allowed.

  For example, if your script lives at `E:/Shows/BigProject/shots/BP_303_003/nuke/BP_303_003_comp_v001.nk`, the pattern `.../{shot}_comp_v{version}.nk` would capture `BP_303_003` as the shot and `001` as the version.

  You can list more than one pattern if you work across shows or clients with different folder structures. Add your own entries above or below the default and NukeLink will try each in order until one matches.

> [!TIP]
> The `...` wildcard will skip over more of the path than you might expect if your folder structure repeats similar names at different levels. Keep patterns as specific as you reasonably can.

- `OUTPUT_LOCATION` - Where NukeLink tells Path Builder to write output, built using the tokens above. You can also set this to a plain, fixed folder path with no tokens in it at all if you don't need it to vary per shot. If a token in this string can't be resolved, the output location is left blank and you'll be told to check this setting when you send to ComfyUI.

- `NAME_PATTERN` - The base filename sent over to ComfyUI's Path Builder node. `{name}`, `{shot}`, and `{version}` all stay as literal, unfilled text in this file, they're filled in later on the ComfyUI side, using the shot and version number fields on the Path Builder node itself. If `SCRIPT_PATH_PATTERNS` resolves successfully, those two fields come over already filled in from Nuke, so in practice you're usually just typing in `{name}` yourself once you're in ComfyUI.

- `WORKFLOW_FOLDERS` - Folders NukeLink scans for ComfyUI workflow templates, offered as a dropdown when you send to ComfyUI. Each entry pairs a folder path (tokens allowed, same as above) with a label. Leave the label blank to mark that folder as your global template folder, its templates always appear first in the dropdown, no matter where that entry sits in the list. Give a folder any other label, a token like `{show}` or just plain text like *Wan 2.2*, and its templates show up below, grouped and prefixed with that label, sorted alphabetically alongside any other labeled folders.

  Each folder is scanned recursively, so templates in subfolders show up too, labeled with their subfolder name. If a folder contains a file named `Default.json` (not case sensitive), that template is automatically selected when the send dialog opens, instead of you having to pick one every time. If a folder listed here doesn't exist on disk, it's simply skipped, no templates from it, no warning.

  If no `Default.json` exists anywhere in your global folder or the show folder that ends up preselected, the dropdown instead shows and preselects `*`, meaning no template, just the standard Read and Path Builder nodes.

---

## 🚀 Usage

### ➡️ Nuke to ComfyUI

1. In Nuke, select one or more Read nodes
2. Tab search for **Send To ComfyUI** or right click in the node graph and select it under the SendToComfyUI menu
3. A dialog will appear asking you to pick a workflow template, or `*` for no template (plain Read and Path Builder nodes, the default behavior). An alert will pop up confirming the node was sent and asking you to switch to ComfyUI. A `Read - NukeLink` node will be dropped on the canvas for each selected Nuke Read node, pre-populated with file path, colorspace, frame range, and missing frames mode. A Path Builder node will also be created to the right, pre-populated with your output location, version number, and shot name.  The Path Builder node also includes the correct Nuke listener port so the Write node knows exactly where to send renders back to.

### ⬅️ ComfyUI to Nuke

1. In ComfyUI, right-click a Write node after the graph has been executed and image(s) have been written to disk
2. Select **Send to Nuke** from the context menu
3. Switch back to Nuke. A Read node will have dropped into the node graph pointing to the rendered output.

<table>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/bb30a1af-10a2-4574-a307-2af047026d11" width="100%"/></td>
    <td><img src="https://github.com/user-attachments/assets/3c35e73e-aa1a-454a-b20b-6c11e82615b1" width="100%"/></td>
  </tr>
</table>

### 🧱 Working with Templates

A template is nothing more than a ComfyUI workflow you've saved. It isn't limited to just Read, Path Builder, and Write nodes, any nodes at all can be part of it. Whatever you connect in the saved graph gets set up automatically for you when that template is used.

**To create one:** build the graph you want in ComfyUI (a `Read - NukeLink` node and any other nodes connected however you like), then export it as a workflow `.json`.

**Where to save it:** the file needs to live inside one of the folders listed in `WORKFLOW_FOLDERS` to show up in the send dialog's dropdown. See the [Configuration](#configuration) section above for how folder scanning, `Default.json`, and folder labels work.

**Rules of thumb**

- The template must contain a `Read - NukeLink` node, that's the injection point for the plate you're sending.
- A `Path Builder - NukeLink` is strongly recommended, since it's what carries `nuke_port` back to the Write node for the return trip.
- Templates are added to your current graph, they don't replace it.
- If you select more than one Read node in Nuke, only the first is injected into the template's Read node. The rest are added as plain Read nodes beside it.
- A node type your template references that isn't installed is skipped with a console warning rather than failing the whole send.

### ComfyUI Settings Panel

NukeLink has a settings section to ComfyUI's built-in settings panel, controlling default values for new nodes created directly in ComfyUI as well as preview behavior for Read and Write nodes.

Settings include defaults for:
- Preview visibility and playback on Read and Write nodes
- Missing frames behavior
- Colorspace
- File type, bit depth, and compression on Write nodes
- First frame number on Write nodes
- Path Builder fields on new nodes

---

## 🧩 Nodes

### Read - NukeLink

| Widget | Description |
|---|---|
| `file_path` | Path to an image or sequence. Accepts `####` and `%04d` style frame padding patterns (e.g. `image.####.exr` or `image.%04d.exr`). |
| `first_frame` | First frame number to load from a sequence. |
| `last_frame` | Last frame number to load from a sequence. |
| `missing_frames` | How to handle missing frames in a sequence. Options: `black`, `hold`, `nearest`, `error`. |
| `colorspace` | The colorspace of the incoming image data. Options: `raw`, `sRGB`, `linear`, `ACEScg`. |


***Right-Click Options***

| Option | Description |
| ------ | ------------ |
| Open in Explorer | Opens the folder containing the current frame in your system's file browser. |
| Preview controls | Hide/show, pause/resume, or re-render the preview. |


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


***Right-Click Options***

| Option | Description |
| ------ | ------------ |
| Open in Explorer | Opens the folder containing the current frame in your system's file browser. |
| Preview controls | Hide/show, pause/resume, or re-render the preview. |
| Create Read from Write | Creates a new Read node pre-filled with the file path, frame range, and colorspace from this node's last execution. |
| Send to Nuke | Sends the rendered output back to Nuke as a new Read node. See [ComfyUI to Nuke](#️-comfyui-to-nuke) for details. |


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
| `name_pattern`    | The pattern used to build the output filename. See [NAME_PATTERN](#configuration) for how tokens in this pattern resolve.      |
| `version_number` | The version number. Must be a numeric string. Highlighted in red when invalid. |
| `version_iterate` | When enabled, automatically increments the version number by one each time the graph executes. |
| `frame_delim` | The character placed between the output stem and the frame padding. Default is `.`. |


***Right-Click Options***

| Option | Description |
| ------ | ------------ |
| Update Path Preview | Manually refreshes the live path preview shown under the node. |


---

## ⚠️ Known Limitations

- **Mac and Linux are untested.** NukeLink was designed with cross-platform support in mind, but could not be thoroughly tested beyond Windows.
- **Multiple Write nodes cannot be sent back to Nuke simultaneously.** Only one Write node at a time can be sent via the right-click Send to Nuke option.
- **Missing Viewer LUT in ComfyUI** Nuke applies a viewer LUT (commonly sRGB by default) on top of whatever colorspace a Read node is set to. ComfyUI does not have an equivalent viewer LUT. As a result, the same colorspace setting will produce visually different results between the two applications. This is a fundamental difference in how the two applications handle color display and is not something NukeLink can resolve automatically.

---

## 🙏 Acknowledgements

**Nuke node logic** - [sumitchatterjee13](https://github.com/sumitchatterjee13/nuke-nodes-comfyui) for the foundational Nuke node approach this tool builds on.

**Preview logic** - [kosinkadink](https://github.com/kosinkadink/ComfyUI-VideoHelperSuite) for the ComfyUI video preview approach referenced in building the NukeLink preview system.

**Template picker inspiration** - [ardaevin](https://github.com/ardaevin/ComfyUI-NukeLink) for the fork that inspired the workflow template picker and the drop-in Nuke install structure.

---

*ComfyUI-NukeLink was developed by Daniel Berkowitz. The majority of the code was written with the assistance of [Claude](https://claude.ai)*