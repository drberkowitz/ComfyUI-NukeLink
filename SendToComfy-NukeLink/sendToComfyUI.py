import nuke
import os
import re
import json
import socket
import threading

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
COMFYUI_HOST = "http://127.0.0.1:8188"

# If you change LISTENER_PORT_START or LISTENER_PORT_RANGE, you must also
# update NUKE_PORT_START and NUKE_PORT_RANGE in server.py in the ComfyUI-NukeLink
# folder to match, or NukeLink will not be able to find the Nuke listener.
LISTENER_PORT_START = 54321
LISTENER_PORT_RANGE = 10

# Shot name derivation for envivronment variables. If your pipeline sets an
# environment variable for the current shot or show name, you can set both
# and this script will use it to fill. Leave the value empty or untouched
# if you don't have one, {show} will then only resolve if your
# SCRIPT_PATH_PATTERNS captures it directly.
SHOT_ENV_VAR = "SHOT"
SHOW_ENV_VAR = "SHOW"

# SCRIPT_PATH_PATTERNS
# An ordered list of patterns matched against the current .nk script's real
# file path to derive tokens like {shot}, {show}, {version} automatically.
# Patterns are tried top to bottom, first match wins. Copy, paste, and edit
# more than one entry if you work across multiple shows or clients with different folder
# structures.
#
# Syntax:
#   {token}  - captures one folder/filename segment (e.g. {shot}, {show},
#              {version}). A literal separator (like "/" or "_" or even "-") is
#              required between two adjacent tokens, "{shot}{version}" is not allowed.
#   ...      - wildcard, matches any run of characters, including "/". Use
#              it to skip over parts of the path that vary and don't matter
#              (drive letters, extra parent folders, etc). Can appear
#              anywhere in the pattern, not just at the start.
#   Everything else is matched literally.
#
# Example - script located at:
#   E:/Shows/BigProject/shots/BP_303_003/nuke/BP_303_003_comp_v001.nk
# matches the default pattern below, capturing shot as "BP_303_003" and
# the version number as "001"
SCRIPT_PATH_PATTERNS = [
    ".../{shot}_comp_v{version}.nk",
]

# OUTPUT_LOCATION
# Where NukeLink tells Path Builder to write output, built from tokens.
#
# Tokens available:
#   {shot}             - from SHOT_ENV_VAR, or from SCRIPT_PATH_PATTERNS if
#                         it captures a {shot} group and no env var is set.
#   {show}             - from SHOW_ENV_VAR, or from SCRIPT_PATH_PATTERNS if
#                         it captures a {show} group and no env var is set.
#   {version}          - from the .nk filename (see _derive_version), or
#                         from SCRIPT_PATH_PATTERNS if it captures a
#                         {version} group.
#   {nuke_script_dir}  - the folder the current .nk script is in. Add :N to
#                         climb N folders up, e.g. {nuke_script_dir:2}.
#   any other name     - only resolves if your SCRIPT_PATH_PATTERNS entry
#                         captures a group with that exact name.
#
# Can also be a full absolute path with no tokens at all, e.g.:
#   E:/Shows/BigProject/elements/
#
# If a token in this string can't be resolved, Path Builder's file_location
# is left empty and the send confirmation message will tell you to check
# this file.
OUTPUT_LOCATION = "{nuke_script_dir:1}/elements/"

# NAME_PATTERN
# The filename stem sent to ComfyUI's Path Builder, built from tokens the
# same way OUTPUT_LOCATION is. {name} is left as a literal, unresolved
# token on purpose. It's a placeholder that for the user to fill it in on the
# ComfyUI side, Path Builder resolves it from there, not this script.
NAME_PATTERN = "{shot}_{name}_v{version}"

# WORKFLOW_FOLDERS
# Folders NukeLink scans for ComfyUI workflow templates, offered as a dropdown
# in the send dialog. First string are folder paths (tokens allowed, resolved the same
# way as OUTPUT_LOCATION/NAME_PATTERN). Next are the dropdown prefix label
# for that folder's entries: "" means it's the global folder (entries appear
# unprefixed, always listed first). A non-empty value like "{show}" becomes a
# "SHOW/TemplateName" prefix for that folder's entries.
#
# If a folder doesn't exist on disk, or whose path contains a token that can't be
# resolved, it simply contributes no entries (an unresolved token additionally
# produces a warning in the send confirmation, same as OUTPUT_LOCATION/NAME_PATTERN).
#
# Default.json (case-insensitive) if present in the global  folder, becomes the
# "Default" entry, always listed first and pre-selected. If no global Default.json
# exists but a show folder has one, that becomes "SHOW/Default", pre-selected, listed
# in its normal alphabetical spot within that show's entries. "*" (no template, true
# default Read + Path Builder behaviour) is only added to the list when no global or show
# Default.json exists.
WORKFLOW_FOLDERS = {
    "E:/ComfyUI/Templates/": "",
    "E:/Shows/{show}/ComfyUITemplates/": "{show}",
}
# ---------------------------------------------------------------------------

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

ALLOWED_EXTENSIONS = {
    "exr", "tiff", "tif", "dpx", "hdr", "png", "jpeg", "jpg",
    "bmp", "tga", "psd", "ico", "rla", "sgi", "pnm", "ppm", "pgm",
    "pbm", "webp", "gif", "heic", "jp2", "jxr", "pic", "pcx", "im", "dib"
}

ALLOWED_COLORSPACES = {"raw", "sRGB", "linear", "ACEScg"}

FRAME_PATTERN_RE = re.compile(r'%0\d+d|#+')


def _is_abs_path(path):
    """True for drive-letter, UNC and posix-absolute paths."""
    if not path:
        return False
    return (
        os.path.isabs(path)
        or path.startswith("//")
        or re.match(r'^[A-Za-z]:[/\\]', path) is not None
    )


def _project_directory():
    """Root.project_directory, evaluated - it commonly holds a TCL expression
    such as [file dirname [value root.name]]. Returns '' when unset."""
    try:
        value = nuke.root()["project_directory"].evaluate() or ""
    except Exception:
        value = ""
    return value.replace("\\", "/").strip().rstrip("/")


def _read_file_value(node):
    """The Read's file path, with any TCL/env expression expanded but the frame
    pattern (%04d / ####) preserved."""
    raw = (node["file"].value() or "").strip()
    if not raw or ("[" not in raw and "$" not in raw):
        return raw.replace("\\", "/")
    try:
        expanded = (nuke.filename(node) or "").strip()
    except Exception:
        expanded = ""
    if expanded:
        had = FRAME_PATTERN_RE.search(raw) is not None
        keeps = FRAME_PATTERN_RE.search(expanded) is not None
        if not had or keeps:
            raw = expanded
    return raw.replace("\\", "/")


def _resolve_read_path(raw):
    """Make a Read path absolute. Absolute paths are returned untouched.
    Relative paths resolve against project_directory if it is set; if it is
    not set, there is nothing to resolve against and '' is returned so the
    caller can skip with a reason."""
    if not raw:
        return ""
    path = raw.replace("\\", "/")
    if _is_abs_path(path):
        return path
    base = _project_directory()
    if not base:
        return ""
    return os.path.normpath(os.path.join(base, path)).replace("\\", "/")


TOKEN_RE = re.compile(r'\{(\w+)\}')


def _validate_pattern_tokens(pattern):
    """Reject patterns where two {tokens} sit directly adjacent with no
    literal separator between them - that's ambiguous and can't be safely
    matched. Returns an error string, or None if the pattern is fine."""
    positions = [(m.start(), m.end()) for m in TOKEN_RE.finditer(pattern)]
    for i in range(len(positions) - 1):
        this_end = positions[i][1]
        next_start = positions[i + 1][0]
        if pattern[this_end:next_start] == "":
            return "Pattern has two tokens with no separator between them: {}".format(pattern)
    return None


def _pattern_to_regex(pattern):
    """Convert a SCRIPT_PATH_PATTERNS entry into a compiled regex, plus a
    map of internal group names back to their real token name. A token can
    appear more than once in a pattern (e.g. {shot} in both a folder and a
    filename) - repeats get an internal suffix since re doesn't allow
    duplicate group names, and are folded back together after matching."""
    error = _validate_pattern_tokens(pattern)
    if error:
        return None, None, error

    regex_parts = []
    group_to_token = {}
    seen_counts = {}
    pos = 0
    length = len(pattern)

    while pos < length:
        if pattern[pos:pos + 3] == "...":
            regex_parts.append(r'.*?')
            pos += 3
            continue

        token_match = TOKEN_RE.match(pattern, pos)
        if token_match:
            name = token_match.group(1)
            seen_counts[name] = seen_counts.get(name, 0) + 1
            group_name = name if seen_counts[name] == 1 else "{}__{}".format(name, seen_counts[name])
            group_to_token[group_name] = name
            regex_parts.append(r'(?P<{}>[^/]+?)'.format(group_name))
            pos = token_match.end()
            continue

        next_wildcard = pattern.find("...", pos)
        next_token = TOKEN_RE.search(pattern, pos)
        next_token_pos = next_token.start() if next_token else length
        stop = min(
            next_wildcard if next_wildcard != -1 else length,
            next_token_pos,
        )
        literal_chunk = pattern[pos:stop]
        regex_parts.append(re.escape(literal_chunk))
        pos = stop

    regex_str = "".join(regex_parts) + "$"
    try:
        return re.compile(regex_str), group_to_token, None
    except re.error as e:
        return None, None, "Pattern could not be compiled: {} ({})".format(pattern, str(e))

def _match_script_path(script_path):
    """Try each pattern in SCRIPT_PATH_PATTERNS, in order, against
    script_path. Returns (tokens_dict, pattern_used, match_error).
    match_error is None on success, otherwise a string explaining why no
    pattern produced usable tokens."""
    if not script_path or script_path == "Root":
        return {}, None, "no .nk script is currently saved"

    normalized = script_path.replace("\\", "/")
    last_error = None

    for pattern in SCRIPT_PATH_PATTERNS:
        regex, group_to_token, error = _pattern_to_regex(pattern)
        if error:
            print("[NukeLink] {}".format(error))
            last_error = error
            continue

        match = regex.search(normalized)
        if not match:
            continue

        captured = match.groupdict()
        tokens = {}
        mismatch = False
        for group_name, value in captured.items():
            token_name = group_to_token[group_name]
            if token_name in tokens and tokens[token_name] != value:
                mismatch_msg = (
                    "pattern '{}' matched but {{{}}} captured different "
                    "values ('{}' vs '{}')".format(pattern, token_name, tokens[token_name], value)
                )
                print("[NukeLink] {}, skipping this pattern.".format(mismatch_msg))
                last_error = mismatch_msg
                mismatch = True
                break
            tokens[token_name] = value

        if mismatch:
            continue

        return tokens, pattern, None

    if last_error:
        return {}, None, last_error
    return {}, None, "script path did not match any SCRIPT_PATH_PATTERNS entry"

def _derive_file_location(tokens):
    """Fill OUTPUT_LOCATION using the resolved token pool. Returns (result,
    unresolved) - if unresolved is non-empty, result is not safe to use as-is
    and the caller should leave Path Builder's file_location blank."""
    result, unresolved = _substitute_tokens(OUTPUT_LOCATION, tokens)
    if not result.endswith("/"):
        result += "/"
    return result, unresolved


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


def _derive_shot():
    """Derive shot name from environment variable."""
    return os.environ.get(SHOT_ENV_VAR, "").strip()

def _derive_show():
    """Derive show name from environment variable."""
    return os.environ.get(SHOW_ENV_VAR, "").strip()


def _scan_json_tree(folder):
    """Recursively scan folder for .json files, building a nested tree.

    Each node is a dict: {"default_path": str_or_None,
                           "entries": [(name, path), ...],
                           "children": {subfolder_name: node, ...}}.
    A file named default.json (case-insensitive) directly inside a folder
    becomes that folder's own default_path, not a regular entry, and is
    excluded from entries. Unreadable folders/files are skipped, with the
    error printed to console, rather than aborting the whole scan."""

    def make_node():
        return {"default_name": None, "default_path": None, "entries": [], "children": {}}

    root = make_node()

    try:
        walker = os.walk(folder)
    except Exception as e:
        print("[NukeLink] could not scan {}: {}".format(folder, str(e)))
        return root

    for dirpath, dirnames, filenames in walker:
        dirnames.sort(key=lambda s: s.lower())
        try:
            rel = os.path.relpath(dirpath, folder).replace("\\", "/")
        except Exception as e:
            print("[NukeLink] could not resolve path for {}: {}".format(dirpath, str(e)))
            continue

        node = root
        if rel not in (".", ""):
            for part in rel.split("/"):
                node = node["children"].setdefault(part, make_node())

        try:
            json_files = sorted(
                (f for f in filenames if f.lower().endswith(".json")),
                key=lambda s: s.lower(),
            )
        except Exception as e:
            print("[NukeLink] could not list files in {}: {}".format(dirpath, str(e)))
            continue

        for fname in json_files:
            try:
                full_path = os.path.join(dirpath, fname).replace("\\", "/")
                name = fname[:-5]
                if name.lower() == "default":
                    node["default_name"] = name
                    node["default_path"] = full_path
                else:
                    node["entries"].append((name, full_path))
            except Exception as e:
                print("[NukeLink] could not read {}: {}".format(fname, str(e)))
                continue

    return root


def _flatten_workflow_tree(node, prefix):
    """Depth-first flatten of a _scan_json_tree() node into an ordered list
    of (label, path) pairs. This node's own default (if any) comes first,
    then its own entries alphabetical, then children alphabetical by folder
    name, each recursed with prefix + foldername + '/'."""
    results = []

    if node["default_path"]:
        results.append((prefix + node["default_name"], node["default_path"]))

    for name, path in node["entries"]:
        results.append((prefix + name, path))

    for child_name in sorted(node["children"].keys(), key=lambda s: s.lower()):
        child_prefix = prefix + child_name + "/"
        results.extend(_flatten_workflow_tree(node["children"][child_name], child_prefix))

    return results


def _build_workflow_dropdown(resolved_tokens):
    """Resolve WORKFLOW_FOLDERS and build the send dialog's Workflow dropdown.

    Returns (labels, label_to_path, preselect_label, warnings):
      labels          - ordered list of strings for the Enumeration_Knob
      label_to_path   - dict mapping a label back to its .json full path,
                         entries not in this dict (e.g. "*") have no file
      preselect_label - which label to setValue() on the panel
      warnings        - list of warning strings for unresolved folder tokens
    """
    warnings = []
    global_flat = []
    global_default_path = None
    show_sections = []  # list of (show_label, flat_entries, default_path_or_None)

    for folder_key, prefix_label in WORKFLOW_FOLDERS.items():
        resolved_folder, unresolved = _substitute_tokens(folder_key, resolved_tokens)
        if unresolved:
            warnings.append(
                "WORKFLOW_FOLDERS entry '{}' could not be fully resolved, missing: {}. "
                "Skipped.".format(folder_key, ", ".join(unresolved))
            )
            continue
        if not os.path.isdir(resolved_folder):
            continue

        resolved_prefix_label, unresolved_label = _substitute_tokens(prefix_label, resolved_tokens)
        if unresolved_label:
            warnings.append(
                "WORKFLOW_FOLDERS prefix label '{}' could not be fully resolved, missing: {}. "
                "Skipped.".format(prefix_label, ", ".join(unresolved_label))
            )
            continue

        tree = _scan_json_tree(resolved_folder)

        if resolved_prefix_label == "":
            global_flat = _flatten_workflow_tree(tree, "")
            global_default_path = tree["default_path"]
        else:
            flat = _flatten_workflow_tree(tree, "")
            show_sections.append((resolved_prefix_label, flat, tree["default_path"]))

    show_sections.sort(key=lambda section: section[0].lower())

    labels = []
    label_to_path = {}
    preselect_label = None

    if global_default_path:
        preselect_label = "Default"
    else:
        labels.append("*")
        preselect_label = "*"

    for label, path in global_flat:
        labels.append(label)
        label_to_path[label] = path

    for show_label, flat, default_path in show_sections:
        for name, path in flat:
            combined = "{}/{}".format(show_label, name)
            labels.append(combined)
            label_to_path[combined] = path
            if path == default_path and preselect_label == "*" and not global_default_path:
                preselect_label = combined
                labels.remove("*")

    # Disambiguate exact-string collisions in order encountered
    seen_counts = {}
    deduped_labels = []
    for label in labels:
        seen_counts[label] = seen_counts.get(label, 0) + 1
        if seen_counts[label] == 1:
            deduped_labels.append(label)
        else:
            new_label = "{} ({})".format(label, seen_counts[label] - 1)
            label_to_path[new_label] = label_to_path[label]
            deduped_labels.append(new_label)

    return deduped_labels, label_to_path, preselect_label, warnings


def _resolve_tokens(matched_tokens):
    """Build the final token pool used by OUTPUT_LOCATION and NAME_PATTERN.
    Env vars take priority over pattern-matched values, since an env var is
    explicit studio configuration and a pattern match is a best-effort
    fallback for when that configuration doesn't exist.
    Starts from matched_tokens (whatever SCRIPT_PATH_PATTERNS captured, if
    anything), then overlays the env-var-derived shot/show on top when set."""
    tokens = dict(matched_tokens)

    shot = _derive_shot()
    if shot:
        tokens["shot"] = shot

    show = _derive_show()
    if show:
        tokens["show"] = show

    return tokens


try:
    import nukescripts
except ImportError:
    nukescripts = None


class SendToComfyUIPanel(nukescripts.PythonPanel):
    """Modal send dialog. Lets the user pick a workflow template. OK acts as
    the Send button. Selecting '*' means no template (plain Read + Path
    Builder, current default behaviour)."""

    def __init__(self, labels, label_to_path, preselect_label):
        nukescripts.PythonPanel.__init__(self, "Send To ComfyUI")

        self._label_to_path = label_to_path

        self.setMinimumSize(400, 100)

        self.workflowKnob = nuke.Enumeration_Knob("workflow", "Template:", labels)
        self.workflowKnob.setTooltip(
            "'*' sends a plain Read + Path Builder graph, no template.\n"
            "'Default' is Default.json from your global or show WORKFLOW_FOLDERS entry.\n"
            "Anything else is a .json from WORKFLOW_FOLDERS."
        )
        self.addKnob(self.workflowKnob)

        self.addKnob(nuke.Text_Knob("", ""))

        if preselect_label:
            self.workflowKnob.setValue(preselect_label)

        self.okButton = nuke.Script_Knob("okButton", "Send")
        self.addKnob(self.okButton)
        self.okButton.setFlag(nuke.STARTLINE)
        self.cancelButton = nuke.Script_Knob("cancelButton", "Cancel")
        self.addKnob(self.cancelButton)

    def selected_template_path(self):
        """Path to the chosen .json, or None if '*' (no template) was chosen."""
        label = self.workflowKnob.value()
        return self._label_to_path.get(label)


NUKE_SCRIPT_DIR_RE = re.compile(r'\{nuke_script_dir(?::(\d+))?\}')
PLAIN_TOKEN_RE = re.compile(r'\{(\w+)\}')

def _nuke_script_dir(levels_up=0):
    """Folder the current .nk script is in, optionally climbed levels_up
    folders further. Returns '' if there is no saved script."""
    script_path = nuke.root().name()
    if not script_path or script_path == "Root":
        return ""
    base = os.path.dirname(os.path.abspath(script_path)).replace("\\", "/")
    for _ in range(levels_up):
        parent = os.path.dirname(base)
        if parent == base:
            break
        base = parent
    return base

def _substitute_tokens(template, tokens, preserve=None):
    """Fill {token} and {nuke_script_dir[:N]} placeholders in template.
    Names listed in preserve are left as literal {name} text instead of
    being resolved or flagged unresolved - used for tokens like {name} that
    are intentionally left for a later stage to fill in.
    Returns (result, unresolved) where unresolved is a list of token names
    that had no value and were left blank."""
    preserve = preserve or ()
    unresolved = []

    def replace_script_dir(match):
        levels = int(match.group(1)) if match.group(1) else 0
        value = _nuke_script_dir(levels)
        if not value:
            unresolved.append("nuke_script_dir")
        return value

    result = NUKE_SCRIPT_DIR_RE.sub(replace_script_dir, template)

    def replace_plain(match):
        name = match.group(1)
        if name in preserve:
            return match.group(0)
        value = tokens.get(name, "")
        if not value:
            unresolved.append(name)
        return value

    result = PLAIN_TOKEN_RE.sub(replace_plain, result)

    return result, unresolved

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

    matched_tokens, matched_pattern, match_error = _match_script_path(script_path)
    pattern_warning = ""
    if matched_tokens:
        print("[NukeLink] script path matched pattern: {}".format(matched_pattern))
    else:
        pattern_warning = "SCRIPT_PATH_PATTERNS: {}. Falling back to best-effort defaults.".format(match_error)
        print("[NukeLink] {}".format(pattern_warning))

    version_number = _derive_version(script_path) if script_path and script_path != "Root" else "01"
    resolved_tokens = _resolve_tokens(matched_tokens)
    resolved_tokens.setdefault("version", version_number)

    file_location, unresolved_location_tokens = _derive_file_location(resolved_tokens)
    location_warning = ""
    if unresolved_location_tokens:
        file_location = ""
        location_warning = (
            "OUTPUT_LOCATION could not be fully resolved, missing: {}. "
            "Path Builder's file_location was left blank, check your config.".format(
                ", ".join(unresolved_location_tokens)
            )
        )
        print("[NukeLink] {}".format(location_warning))

    name_pattern_resolved, unresolved_name_tokens = _substitute_tokens(
    NAME_PATTERN, resolved_tokens, preserve=("name", "shot", "version")
)
    name_pattern_warning = ""
    if unresolved_name_tokens:
        name_pattern_resolved = ""
        name_pattern_warning = (
            "NAME_PATTERN could not be fully resolved, missing: {}. "
            "Path Builder's name pattern was left blank, check your config.".format(
                ", ".join(unresolved_name_tokens)
            )
        )
        print("[NukeLink] {}".format(name_pattern_warning))

    reads = []
    skipped = []

    for node in read_nodes:
        raw_path = _read_file_value(node)
        if not raw_path:
            skipped.append("{} (no file path)".format(node.name()))
            continue

        file_path = _resolve_read_path(raw_path)
        if not file_path or not _is_abs_path(file_path):
            skipped.append(
                "{} (relative path could not be resolved, no project_directory set: {})".format(
                    node.name(), raw_path
                )
            )
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

    template_path = None
    template_workflow = None
    template_name = None
    template_folder_warnings = []

    if nukescripts is not None:
        labels, label_to_path, preselect_label, template_folder_warnings = _build_workflow_dropdown(resolved_tokens)
        panel = SendToComfyUIPanel(labels, label_to_path, preselect_label)
        if not panel.showModalDialog():
            return
        template_path = panel.selected_template_path()

    if template_path:
        try:
            with open(template_path, "r") as f:
                template_workflow = json.load(f)
            template_name = os.path.splitext(os.path.basename(template_path))[0]
        except Exception as e:
            nuke.message(
                "Template could not be loaded, sending Read and Path Builder only:\n{}\n\n{}".format(
                    template_path, str(e)
                )
            )

    frame_delim = None
    for r in reads:
        frame_delim = _derive_frame_delim(r["file_path"])
        if frame_delim:
            break

    shot = resolved_tokens.get("shot", "")

    payload = json.dumps({
        "reads": reads,
        "file_location": file_location,
        "name_pattern": name_pattern_resolved,
        "version_number": version_number,
        "frame_delim": frame_delim,
        "shot": shot,
        "send_path_builder": True,
        "nuke_port": _listener_port,
        "template_workflow": template_workflow,
    }).encode("utf-8")

    try:
        http_post(COMFYUI_HOST + "/nukelink/receive", payload)
        msg = "{} Read node{} sent to ComfyUI. Switch to ComfyUI to see the node{} on the canvas.".format(
            len(reads),
            "s" if len(reads) != 1 else "",
            "s" if len(reads) != 1 else "",
        )
        if template_name:
            msg += "\n\nTemplate: {}".format(template_name)
        if pattern_warning:
            msg += "\n\n" + pattern_warning
        if location_warning:
            msg += "\n\n" + location_warning
        if name_pattern_warning:
            msg += "\n\n" + name_pattern_warning
        if template_folder_warnings:
            msg += "\n\n" + "\n".join(template_folder_warnings)
        if skipped:
            msg += "\n\nSkipped:\n" + "\n".join(skipped)
        nuke.message(msg)
    except Exception as e:
        nuke.message("Failed to send to ComfyUI:\n{}".format(str(e)))

# ---------------------------------------------------------------------------
# ComfyUI -> Nuke listener
# ---------------------------------------------------------------------------

def _relativize_if_under_project(path):
    """If project_directory is set and path lives under it, return the path
    relative to project_directory (empty, no leading ./), matching how Nuke
    itself expresses a Read's file knob when created inside a project. If
    project_directory is unset or path isn't under it, return path unchanged."""
    base = _project_directory()
    if not base:
        return path
    normalized = path.replace("\\", "/")
    prefix = base + "/"
    if normalized.startswith(prefix):
        return normalized[len(prefix):]
    return path


def _create_read_node(params, result_holder):
    try:
        file_path = _relativize_if_under_project(params.get("file_path", ""))
        n = nuke.nodes.Read(
            file=file_path,
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
                print("[NukeLink] Could not set colorspace '{}' on Read node".format(colorspace))
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
