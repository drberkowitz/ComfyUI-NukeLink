import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

function chainCallback(object, property, callback) {
    if (object[property]) {
        const original = object[property];
        object[property] = function() {
            original.apply(this, arguments);
            callback.apply(this, arguments);
        };
    } else {
        object[property] = callback;
    }
}

function fitHeight(node) {
    node.setSize([node.size[0], node.computeSize([node.size[0], node.size[1]])[1]]);
    node.graph?.setDirtyCanvas(true);
}

function watchValue(widget, onChange) {
    let _value = widget.value;
    Object.defineProperty(widget, "value", {
        get() { return _value; },
        set(v) {
            _value = v;
            onChange(v);
        },
        configurable: true,
    });
}

function allowDragFromWidget(widget) {
    widget.onPointerDown = function(pointer, node) {
        pointer.onDragStart = () => {
            app.canvas.emitBeforeChange?.();
            app.canvas.graph?.beforeChange?.();
            pointer.finally = () => {
                app.canvas.isDragging = false;
                app.canvas.graph?.afterChange?.();
                app.canvas.emitAfterChange?.();
            };
            app.canvas.processSelect(node, pointer.eDown, true);
            app.canvas.isDragging = true;
        };
        pointer.onDragEnd = () => {
            app.canvas.dirty_canvas = true;
            app.canvas.dirty_bgcanvas = true;
        };
        app.canvas.dirty_canvas = true;
        return true;
    };
}

async function scanForNukePort() {
    const START = 54321;
    const END = 54330;
    for (let port = START; port <= END; port++) {
        try {
            const res = await fetch(`/nukelink/pingport?port=${port}`);
            if (res.ok) {
                console.log(`[NukeLink] Found Nuke listener on port ${port}`);
                return port;
            }
        } catch (e) {
            // fetch itself failed, keep scanning
        }
    }
    console.log("[NukeLink] No Nuke listener found in port range");
    return null;
}

function getPathBuilderFingerprint(upstream) {
    const get = (name) => upstream.widgets?.find(w => w.name === name)?.value;
    return JSON.stringify([
        get("name") ?? "",
        get("shot") ?? "",
        get("file_location") ?? "",
        get("bypass_location") ?? false,
        get("sequence_folder") ?? true,
        get("name_pattern") ?? "{shot}_{name}_v{version}",
        String(get("version_number") ?? "").trim(),
        get("frame_delim") ?? ".",
    ]);
}

async function resolvePathBuilderPath(upstream, force = false) {
    const fingerprint = getPathBuilderFingerprint(upstream);

    if (!force && upstream._resolveCache && upstream._resolveCache.fingerprint === fingerprint) {
        return upstream._resolveCache.path;
    }

    const get = (name) => upstream.widgets?.find(w => w.name === name)?.value;

    try {
        const res = await fetch("/nukelink/resolvepath", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name:            get("name") ?? "",
                shot:            get("shot") ?? "",
                file_location:   get("file_location") ?? "",
                bypass_location: get("bypass_location") ?? false,
                sequence_folder: get("sequence_folder") ?? true,
                name_pattern:    get("name_pattern") ?? "{shot}_{name}_v{version}",
                version_number:  String(get("version_number") ?? "").trim(),
                frame_delim:     get("frame_delim") ?? ".",
            }),
        });

        const data = await res.json();

        if (!res.ok) {
            showToast("error", "Resolve Path", data.error ?? `Server error ${res.status}`);
            return null;
        }

        upstream._resolveCache = { fingerprint, path: data.path };
        return data.path;
    } catch (e) {
        console.error("[NukeLink] resolvepath fetch failed:", e);
        showToast("error", "Resolve Path", "Could not reach the NukeLink server.");
        return null;
    }
}

async function resolvePathFromWriteNode(writeNode) {
    if (writeNode._lastFilePath) {
        return writeNode._lastFilePath;
    }

    const fileInput = writeNode.inputs?.find(inp => inp.name === "file_path");
    const isConnected = fileInput && fileInput.link != null;

    if (isConnected) {
        const link = app.graph.links[fileInput.link];
        if (link) {
            const upstream = app.graph.getNodeById(link.origin_id);
            if (upstream?.type === "Path Builder - NukeLink") {
                return await resolvePathBuilderPath(upstream);
            }
        }
    }

    return writeNode.widgets?.find(w => w.name === "file_path")?.value ?? "";
}

async function openInFolder(path, fileType, firstFrame) {
    if (!path) {
        console.warn("[NukeLink] openInFolder: no path provided");
        return;
    }
    try {
        const body = { path };
        if (fileType != null) body.file_type = fileType;
        if (firstFrame != null) body.first_frame = firstFrame;

        const res = await fetch("/nukelink/openinfolder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const text = await res.text();
            console.warn("[NukeLink] openInFolder error:", res.status, text);
            showToast("error", getOpenInFolderLabel(), `Could not open folder: ${text}`);
        }
    } catch (e) {
        console.error("[NukeLink] openInFolder fetch failed:", e);
        showToast("error", getOpenInFolderLabel(), "Could not reach the NukeLink server.");
    }
}

function getOpenInFolderLabel() {
    const platform = navigator.platform?.toLowerCase() ?? "";
    if (platform.includes("mac")) return "Open in Finder";
    if (platform.includes("linux")) return "Open in Files";
    return "Open in Explorer";
}

function showToast(severity, summary, detail, life) {
    app.extensionManager.toast.add({
        severity,
        summary,
        detail,
        life: life ?? (severity === "error" ? 5000 : 3000),
    });
}

const WIDGET_HEIGHT = 22;
const PAD_X = 15;
const GAP = 6;

function createIntWidget(name, label, val) {
    return {
        name,
        type: "int",
        value: Number(val || 0),

        draw(ctx, node, widgetWidth, y, height) {
            const h = height || WIDGET_HEIGHT;
            const w = widgetWidth - PAD_X * 2;
            ctx.fillStyle = LiteGraph.WIDGET_BGCOLOR;
            ctx.strokeStyle = LiteGraph.WIDGET_OUTLINE_COLOR;
            ctx.beginPath();
            ctx.roundRect(PAD_X, y, w, h, h * 0.5);
            ctx.fill();
            ctx.stroke();

            ctx.fillStyle = LiteGraph.WIDGET_SECONDARY_TEXT_COLOR;
            ctx.font = `${Math.max(9, h * 0.65)}px sans-serif`;
            ctx.textAlign = "left";
            ctx.fillText(label, PAD_X + 8, y + h * 0.75);

            ctx.fillStyle = LiteGraph.WIDGET_TEXT_COLOR;
            ctx.textAlign = "right";
            ctx.fillText(String(this.value), PAD_X + w - 18, y + h * 0.75);
        },

        mouse(event, pos, node) {
            if (event.type === "pointerdown") {
                this._maybeClick = true;
                this._dragStart = pos[0];
                this._valueAtDragStart = Number(this.value);
                return true;
            }

            if (event.type === "pointermove") {
                const moved = Math.abs(pos[0] - (this._dragStart || 0)) > 4;
                if (this._maybeClick && moved) {
                    this._maybeClick = false;
                    this._active = true;
                }
                if (this._active) {
                    const delta = Math.round((pos[0] - this._dragStart) / 3);
                    this.value = Number(this._valueAtDragStart + delta);
                    try { app.canvas && app.canvas.draw && app.canvas.draw(true); } catch(e) {}
                    return true;
                }
                return false;
            }

            if (event.type === "pointerup") {
                if (this._maybeClick) {
                    const canvas = app.canvas;
                    canvas.prompt(
                        this.name,
                        this.value,
                        (v) => { this.value = Number(v); },
                        event
                    );
                    this._maybeClick = false;
                    return true;
                }
                this._active = false;
                return true;
            }

            return false;
        },

        serializeValue() {
            try { return Number(this.value || 0); } catch (e) { return 0; }
        },
    };
}

function createDualIntWidget(name, label1, label2, val1, val2, mirrors) {
    mirrors = mirrors || [null, null];
    return {
        name,
        type: "dual_int",
        value: [Number(val1 ?? 1001), Number(val2 ?? 1001)],
        label1,
        label2,
        _active: null,
        _lastClick: 0,

        draw(ctx, node, widgetWidth, y, height) {
            const halfW = (widgetWidth - PAD_X * 2 - GAP) / 2;
            const h = height || WIDGET_HEIGHT;

            const drawHalf = (x, w, label, value, isActive) => {
                ctx.fillStyle = LiteGraph.WIDGET_BGCOLOR;
                ctx.strokeStyle = LiteGraph.WIDGET_OUTLINE_COLOR;
                ctx.beginPath();
                ctx.roundRect(x, y, w, h, h * 0.5);
                ctx.fill();
                ctx.stroke();

                ctx.fillStyle = LiteGraph.WIDGET_SECONDARY_TEXT_COLOR;
                ctx.font = `${Math.max(9, h * 0.65)}px sans-serif`;
                ctx.textAlign = "left";
                ctx.fillText(label, x + 12, y + h * 0.75);

                ctx.fillStyle = LiteGraph.WIDGET_TEXT_COLOR;
                ctx.textAlign = "right";
                ctx.fillText(String(value), x + w - 18, y + h * 0.75);
            };

            drawHalf(PAD_X, halfW, label1, this.value[0], this._active === 0);
            drawHalf(PAD_X + halfW + GAP, halfW, label2, this.value[1], this._active === 1);
        },

        mouse(event, pos, node) {
            const widgetWidth = node.size[0];
            const halfW = (widgetWidth - PAD_X * 2 - GAP) / 2;
            const midpoint = PAD_X + halfW + GAP / 2;
            const side = pos[0] < midpoint ? 0 : 1;

            if (event.type === "pointerdown") {
                this._maybeClick = true;
                this._dragStart = pos[0];
                this._valueAtDragStart = Number(this.value[side]);
                return true;
            }

            if (event.type === "pointermove") {
                const moved = Math.abs(pos[0] - (this._dragStart || 0)) > 4;
                if (this._maybeClick && moved) {
                    this._maybeClick = false;
                    this._active = side;
                }
                if (this._active !== null) {
                    const delta = Math.round((pos[0] - this._dragStart) / 3);
                    this.value[side] = Number(this._valueAtDragStart + delta);
                    if (mirrors[side]) { mirrors[side].value = Number(this.value[side]); }
                    try { app.canvas.draw(true); } catch (e) {}
                    return true;
                }
                return false;
            }

            if (event.type === "pointerup") {
                if (this._maybeClick) {
                    const canvas = app.canvas;
                    canvas.prompt(
                        this["label" + (side + 1)],
                        this.value[side],
                        (v) => {
                            this.value[side] = Number(v);
                            if (mirrors[side]) { mirrors[side].value = Number(this.value[side]); }
                            try { app.canvas.draw(true); } catch (e) {}
                        },
                        event
                    );
                    this._maybeClick = false;
                    return true;
                }
                this._active = null;
                return true;
            }

            return false;
        },

        serialize: false,
        serializeValue() {
            // avoid persisting this widget as the authoritative input
            return null;
        },
    };
}

function addVideoPreview(nodeType) {
    chainCallback(nodeType.prototype, "onNodeCreated", function() {
        const node = this;

        const container = document.createElement("div");
        container.style.cssText = "width:100%;overflow:visible;";

        const previewWidget = node.addDOMWidget("videopreview", "preview", container, {
            serialize: false,
            hideOnZoom: false,
        });

        const INFO_HEIGHT = 18;

        previewWidget.computeSize = function(width) {
            const infoHeight = (!previewWidget.infoEl?.hidden) ? INFO_HEIGHT : 0;
            if (previewWidget.aspectRatio && !previewWidget.parentEl.hidden) {
                let height = (node.size[0] - 20) / previewWidget.aspectRatio + 10;
                if (!(height > 0)) {
                    height = 0;
                }
                previewWidget.computedHeight = height + infoHeight + 10;
                return [width, height + infoHeight];
            }
            return [width, infoHeight];
        };

        previewWidget.aspectRatio = null;
        allowDragFromWidget(previewWidget);

        const parentEl = document.createElement("div");
        parentEl.className = "nukelink_preview";
        parentEl.style.cssText = "width:100%;position:relative;";
        container.appendChild(parentEl);
        previewWidget.parentEl = parentEl;

        const infoEl = document.createElement("div");
        infoEl.style.cssText = "width:100%;text-align:center;font-size:10px;color:#aaa;padding:2px 0;";
        infoEl.hidden = true;
        container.appendChild(infoEl);
        previewWidget.infoEl = infoEl;

        const videoEl = document.createElement("video");
        videoEl.controls = false;
        videoEl.loop = true;
        videoEl.muted = true;
        videoEl.style.cssText = "width:100%;display:block;";
        parentEl.appendChild(videoEl);
        previewWidget.videoEl = videoEl;

        const imgEl = document.createElement("img");
        imgEl.style.cssText = "width:100%;display:none;";
        parentEl.appendChild(imgEl);
        previewWidget.imgEl = imgEl;

        videoEl.addEventListener("loadedmetadata", () => {
            if (videoEl.videoWidth && videoEl.videoHeight) {
                previewWidget.aspectRatio = videoEl.videoWidth / videoEl.videoHeight;
                previewWidget.infoEl.textContent = `${videoEl.videoWidth} x ${videoEl.videoHeight}`;
                previewWidget.infoEl.hidden = false;
            }
            fitHeight(node);
        });

        videoEl.addEventListener("error", () => {
            videoEl.style.display = "none";
            imgEl.style.display = "none";
            fitHeight(node);
        });

        imgEl.addEventListener("load", () => {
            if (imgEl.naturalWidth && imgEl.naturalHeight) {
                previewWidget.aspectRatio = imgEl.naturalWidth / imgEl.naturalHeight;
                previewWidget.infoEl.textContent = `${imgEl.naturalWidth} x ${imgEl.naturalHeight}`;
                previewWidget.infoEl.hidden = false;
            }
            fitHeight(node);
        });

        // Forward pointer/wheel/context events back to the canvas
        container.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            return app.canvas._mousedown_callback(e);
        }, true);
        container.addEventListener("pointerdown", (e) => {
            e.preventDefault();
            return app.canvas._mousedown_callback(e);
        }, true);
        container.addEventListener("mousewheel", (e) => {
            e.preventDefault();
            return app.canvas._mousewheel_callback(e);
        }, true);
        container.addEventListener("pointermove", (e) => {
            e.preventDefault();
            return app.canvas._mousemove_callback(e);
        }, true);
        container.addEventListener("pointerup", (e) => {
            e.preventDefault();
            return app.canvas._mouseup_callback(e);
        }, true);

        // Debounce timer handle
        let _updateTimer = null;

        // Store state on the widget directly, not in .value which gets clobbered
        previewWidget._state = { hidden: false, paused: false, params: {} };

        setTimeout(() => {
            const isWrite = node.type === "Write - NukeLink";
            if (!node._nukeWasConfigured) {
                const showSettingId = isWrite ? "NukeLink.Write.ShowPreviewByDefault" : "NukeLink.Read.ShowPreviewByDefault";
                const playSettingId = isWrite ? "NukeLink.Write.PlayPreviewByDefault" : "NukeLink.Read.PlayPreviewByDefault";
                const hidden = !app.ui.settings.getSettingValue(showSettingId, true);
                const paused = !app.ui.settings.getSettingValue(playSettingId, true);
                previewWidget._state.hidden = hidden;
                previewWidget._state.paused = paused;
                previewWidget.parentEl.hidden = hidden;
            }
        }, 0);

        node.updateParameters = function(params, force) {
            if (!previewWidget._state.params) {
                previewWidget._state.params = {};
            }
            Object.assign(previewWidget._state.params, params);
            if (force) {
                clearTimeout(_updateTimer);
                previewWidget.updateSource();
            } else {
                clearTimeout(_updateTimer);
                _updateTimer = setTimeout(() => previewWidget.updateSource(), 100);
            }
        };

        previewWidget.updateSource = function(force) {
            const params = previewWidget._state.params;
            if (!params || !params.filename) return;
            if (previewWidget._state.hidden && !force) return;

            const isSequence = params.filename.includes("#") || params.filename.includes("%");
            const ts = Date.now();

            parentEl.hidden = previewWidget._state.hidden;

            if (isSequence) {
                const url = new URL("/nukelink/viewvideo", window.location.origin);
                url.searchParams.set("filename", params.filename);
                url.searchParams.set("first_frame", params.first_frame ?? 0);
                url.searchParams.set("last_frame", params.last_frame ?? 0);
                url.searchParams.set("colorspace", params.colorspace ?? "sRGB");
                url.searchParams.set("missing_frames", params.missing_frames ?? "black");
                url.searchParams.set("ts", ts);

                imgEl.style.display = "none";
                imgEl.src = "";
                videoEl.style.display = "block";
                videoEl.autoplay = !previewWidget._state.paused && !previewWidget._state.hidden;
                videoEl.src = url.toString();
                if (!previewWidget._state.paused) {
                    videoEl.play().catch(() => {});
                }
            } else {
                const url = new URL("/nukelink/viewimage", window.location.origin);
                url.searchParams.set("filename", params.filename);
                url.searchParams.set("ts", ts);

                videoEl.style.display = "none";
                videoEl.removeAttribute("src");
                imgEl.style.display = "block";
                imgEl.removeAttribute("hidden");
                parentEl.hidden = previewWidget._state.hidden;
                imgEl.src = url.toString();
                return;
            }

            fitHeight(node);
        };
    });
}

function buildPreviewMenuOptions(node, previewWidget) {
    const videoEl = previewWidget.videoEl;
    const parentEl = previewWidget.parentEl;
    const options = [];

    if (videoEl && videoEl.style.display !== "none" && videoEl.src) {
        options.push({
            content: previewWidget._state.paused ? "Resume preview" : "Pause preview",
            callback: () => {
                if (previewWidget._state.paused) {
                    videoEl.play().catch(() => {});
                    previewWidget._state.paused = false;
                } else {
                    videoEl.pause();
                    previewWidget._state.paused = true;
                }
            },
        });
    }

    options.push({
        content: previewWidget._state.hidden ? "Show preview" : "Hide preview",
        callback: () => {
            const wasHidden = previewWidget._state.hidden;
            previewWidget._state.hidden = !wasHidden;
            parentEl.hidden = previewWidget._state.hidden;
            if (wasHidden) {
                previewWidget.updateSource(true);
            }
            fitHeight(node);
        },
    });

    options.push({
        content: "Re-render preview",
        callback: () => {
            previewWidget._state.hidden = false;
            parentEl.hidden = false;
            previewWidget.updateSource(true);
        },
    });

    return options;
}

function addPreviewOptions(nodeType) {
    chainCallback(nodeType.prototype, "getExtraMenuOptions", function(_, options) {
        const previewWidget = this.widgets?.find(w => w.name === "videopreview");
        if (!previewWidget) return;

        const extraOptions = buildPreviewMenuOptions(this, previewWidget);

        // Re-render (Read variant) also syncs colorspace/missing_frames into params first
        const reRenderIndex = extraOptions.findIndex(o => o.content === "Re-render preview");
        if (reRenderIndex !== -1) {
            extraOptions[reRenderIndex] = {
                content: "Re-render preview",
                callback: () => {
                    const colorspaceWidget = this.widgets?.find(w => w.name === "colorspace");
                    const missingWidget = this.widgets?.find(w => w.name === "missing_frames");
                    if (colorspaceWidget) {
                        previewWidget._state.params.colorspace = colorspaceWidget.value;
                    }
                    if (missingWidget) {
                        previewWidget._state.params.missing_frames = missingWidget.value;
                    }
                    previewWidget._state.hidden = false;
                    previewWidget.parentEl.hidden = false;
                    previewWidget.updateSource(true);
                },
            };
        }

        // Sync - reset all nukelink previews to frame 0
        extraOptions.push({
            content: "Sync preview",
            callback: () => {
                for (const el of document.querySelectorAll(".nukelink_preview video")) {
                    el.currentTime = 0;
                }
            },
        });
        
        extraOptions.push({
            content: getOpenInFolderLabel(),
            callback: () => {
                const fileWidget = this.widgets?.find(w => w.name === "file_path");
                openInFolder(fileWidget?.value ?? "");
            },
        });

        // Prepend to existing options
        options.unshift(...extraOptions, null);
    });
}

function addWriteOptions(nodeType) {
    chainCallback(nodeType.prototype, "getExtraMenuOptions", function(_, options) {
        const previewWidget = this.widgets?.find(w => w.name === "videopreview");
        const extraOptions = [];

        if (previewWidget) {
            extraOptions.push(...buildPreviewMenuOptions(this, previewWidget));
            extraOptions.push(null);
        }

        extraOptions.push({
            content: getOpenInFolderLabel(),
            callback: async () => {
                const path = await resolvePathFromWriteNode(this);
                if (!path) return;
                const fileTypeWidget = this.widgets?.find(w => w.name === "file_type");
                const firstFrameWidget = this.widgets?.find(w => w.name === "first_frame");
                openInFolder(path, fileTypeWidget?.value, firstFrameWidget?.value);
            },
        });

        extraOptions.push({
            content: "Create Read from Write",
            callback: async () => {
                const writeNode = this;
                if (!writeNode._lastFilePath || !writeNode._lastExecutionResult) {
                    showToast("error", "Create Read from Write", "This Write node hasn't executed yet.");
                    return;
                }

                const filePath = await resolvePathFromWriteNode(writeNode);
                if (!filePath) {
                    showToast("error", "Create Read from Write", "Could not resolve file path.");
                    return;
                }

                const missingFrames = app.ui.settings.getSettingValue("NukeLink.Read.MissingFrames", "black");

                const newNode = LiteGraph.createNode("Read - NukeLink");
                if (!newNode) {
                    console.error("[NukeLink] Failed to create Read - NukeLink node");
                    return;
                }
                app.graph.add(newNode);
                newNode.pos = [
                    writeNode.pos[0] + writeNode.size[0] + 50,
                    writeNode.pos[1],
                ];

                nukeLinkApplyRead(newNode, {
                    file_path:      filePath,
                    first_frame:    writeNode._lastExecutionResult.first_frame,
                    last_frame:     writeNode._lastExecutionResult.last_frame,
                    colorspace:     writeNode._lastExecutionResult.colorspace,
                    missing_frames: missingFrames,
                });

                app.graph.setDirtyCanvas(true);
            },
        });

        extraOptions.push({
            content: "Send to Nuke",
            callback: async () => {
                const node = this;
                const fileWidget = node.widgets?.find(w => w.name === "file_path");
                const fileInput = node.inputs?.find(inp => inp.name === "file_path");
                const isConnected = fileInput && fileInput.link != null;

                let filePath = null;
                let upstreamNode = null;
                let isPathBuilder = false;

                if (isConnected) {
                    const link = app.graph.links[fileInput.link];
                    if (link) {
                        upstreamNode = app.graph.getNodeById(link.origin_id);
                        isPathBuilder = upstreamNode?.type === "Path Builder - NukeLink";
                    }
                }

                filePath = await resolvePathFromWriteNode(node);

                if (!filePath) {
                    showToast("error", "Send to Nuke", "Could not resolve file path.");
                    return;
                }

                // Resolve nuke_port
                let nukePort = null;
                if (isPathBuilder && upstreamNode) {
                    const portWidget = upstreamNode.widgets?.find(w => w.name === "nuke_port");
                    if (portWidget?.value) {
                        nukePort = portWidget.value;
                        console.log("[NukeLink] nuke_port from Path Builder widget:", nukePort);
                    }
                }
                if (!nukePort) {
                    nukePort = await scanForNukePort();
                }
                if (!nukePort) {
                    console.warn("[NukeLink] Send to Nuke: no Nuke listener found");
                    return;
                }

                // Read colorspace
                const colorspaceWidget = node.widgets?.find(w => w.name === "colorspace");
                const colorspace = colorspaceWidget?.value ?? "raw";

                console.log("[NukeLink] Sending to Nuke:", { filePath, colorspace, nukePort });

                // POST to server
                try {
                    const body = {
                        file_path: filePath,
                        colorspace: colorspace,
                        nuke_port: nukePort,
                    };
                    if (node._lastExecutionResult) {
                        body.first_frame = node._lastExecutionResult.first_frame;
                        body.last_frame = node._lastExecutionResult.last_frame;
                    }

                    const res = await fetch("/nukelink/sendtonuke", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(body),
                    });
                    const text = await res.text();
                    if (res.ok) {
                        console.log("[NukeLink] Send to Nuke success:", text);
                        showToast("success", "Send to Nuke", "Read node created in Nuke. Switch to Nuke to see the node on the canvas.");
                    } else {
                        console.warn("[NukeLink] Send to Nuke error:", res.status, text);
                        showToast("error", "Send to Nuke", `Server error ${res.status}: ${text}`);
                    }
                } catch (e) {
                    console.error("[NukeLink] Send to Nuke fetch failed:", e);
                    showToast("error", "Send to Nuke", "Could not reach the NukeLink server.");
                }
            },
        });

        options.unshift(...extraOptions, null);
    });
}

function addUpdatePathPreviewOption(nodeType) {
    chainCallback(nodeType.prototype, "getExtraMenuOptions", function(_, options) {
        const node = this;
        options.unshift({
            content: "Update Path Preview",
            callback: () => {
                node.updatePreview(true);
            },
        }, null);
    });
}

function setupNukeRead(node) {
    // Defer setup until after ComfyUI has finished building the node's widget list
    setTimeout(() => {
        // remove managed widgets to avoid duplicates on re-run
        const removeWidget = (name) => {
            for (let i = node.widgets.length - 1; i >= 0; i--) {
                if (node.widgets[i]?.name === name) node.widgets.splice(i, 1);
            }
        };
        
        const wFirstOld = node.widgets.find((w) => w.name === "first_frame");
        const wLastOld  = node.widgets.find((w) => w.name === "last_frame");
        
        let wFirst = wFirstOld;
        let wLast  = wLastOld;
        removeWidget("row_a");
        removeWidget("first_frame");
        removeWidget("last_frame");

        // create scalar widgets but don't insert yet
        if (!wFirst) wFirst = createIntWidget("first_frame", "first_frame", 1001);
        if (!wLast) wLast = createIntWidget("last_frame", "last_frame", 1001);

        // ensure the scalar widgets serialize scalars
        wFirst.serializeValue = () => Number(wFirst.value || 0);
        wLast.serializeValue = () => Number(wLast.value || 0);

        // hide their own draw/mouse so they don't intercept events (but keep them for persistence)
        const hideWidget = (w) => {
            if (w._hiddenByRow) return;
            w.draw = () => {};
            w.mouse = () => false;
            w.computeSize = () => [0, 0];
            w._hiddenByRow = true;
        };

        hideWidget(wFirst);
        hideWidget(wLast);

        const wRowA = node.widgets.find(w => w.name === "_row_a");
        if (wRowA) hideWidget(wRowA);


        // create visible row that mirrors into the scalar widgets
        const row = createDualIntWidget(
            "row_a",
            "first_frame",
            "last_frame",
            Number(wFirst.value ?? 1001),
            Number(wLast.value ?? 1001),
            [wFirst, wLast]
        );

        // insert visible row near the top
        node.widgets.splice(1, 0, row);

        // find the index of the colorspace widget and insert the hidden scalars after it
        let colorspaceIndex = node.widgets.findIndex((w) => w && w.name === "colorspace");
        if (colorspaceIndex < 0) colorspaceIndex = node.widgets.length - 1;
        const insertAt = colorspaceIndex + 1;
        node.widgets.splice(insertAt, 0, wLast);
        node.widgets.splice(insertAt, 0, wFirst);

        // keep node sizing reasonable
        node.size[0] = Math.max(node.size[0] || 300, 350);
        node.size[1] = WIDGET_HEIGHT * 6 + 150;

        // wire frame range changes to preview
        watchValue(wFirst, () => {
            node.updateParameters({ first_frame: wFirst.value }, false);
        });
        watchValue(wLast, () => {
            node.updateParameters({ last_frame: wLast.value }, false);
        });

        // restore serialized values if this node was loaded from a saved graph
        if (node._nukeReadRestore) {
            const r = node._nukeReadRestore;
            if (r.first_frame != null) {
                wFirst.value = Number(r.first_frame);
                row.value[0] = Number(r.first_frame);
            }
            if (r.last_frame != null) {
                wLast.value = Number(r.last_frame);
                row.value[1] = Number(r.last_frame);
            }
            const missingWidget = node.widgets.find(w => w.name === "missing_frames");
            const colorspaceWidget = node.widgets.find(w => w.name === "colorspace");
            if (missingWidget && r.missing_frames != null) missingWidget.value = r.missing_frames;
            if (colorspaceWidget && r.colorspace != null) colorspaceWidget.value = r.colorspace;
            delete node._nukeReadRestore;
        }

        // apply settings defaults to fresh nodes only (not restored from saved graph)
        if (!node._nukeWasConfigured) {
            const missingWidget = node.widgets.find(w => w.name === "missing_frames");
            const colorspaceWidget = node.widgets.find(w => w.name === "colorspace");
            if (missingWidget) {
                missingWidget.value = app.ui.settings.getSettingValue("NukeLink.Read.MissingFrames", "black");
            }
            if (colorspaceWidget) {
                colorspaceWidget.value = app.ui.settings.getSettingValue("NukeLink.Read.Colorspace", "raw");
            }
        }

        // restore serialized preview state if available, overriding settings
        if (node._nukeLinkPreviewRestore) {
            const r = node._nukeLinkPreviewRestore;
            const previewWidget = node.widgets?.find(w => w.name === "videopreview");
            if (previewWidget) {
                if (r.hidden != null) {
                    previewWidget._state.hidden = r.hidden;
                    previewWidget.parentEl.hidden = r.hidden;
                }
                if (r.paused != null) {
                    previewWidget._state.paused = r.paused;
                }
                if (r.params?.filename) {
                    Object.assign(previewWidget._state.params, r.params);
                    node.updateParameters(r.params, true);
                }
            }
            delete node._nukeLinkPreviewRestore;
        }

        // fire with current values so preview initialises on load
        const fileWidget = node.widgets?.find(w => w.name === "file_path");
        const colorspaceWidget = node.widgets?.find(w => w.name === "colorspace");
        const missingWidget = node.widgets?.find(w => w.name === "missing_frames");
        if (fileWidget?.value) {
            node.updateParameters({
                filename: fileWidget.value,
                first_frame: wFirst.value,
                last_frame: wLast.value,
                colorspace: colorspaceWidget?.value ?? "raw",
                missing_frames: missingWidget?.value ?? "black",
            }, true);
        }
    }, 0);
}

function setupNukeWrite(node) {
    setTimeout(() => {
        const getSetting = (id, fallback) => {
            const val = app.ui.settings.getSettingValue(id);
            return (val !== undefined && val !== null) ? val : fallback;
        };

        const defaults = {
            first_frame: Math.round(getSetting("NukeLink.Write.FirstFrame", 1001)),
            file_type:   getSetting("NukeLink.Write.FileType",   "png"),
            bit_depth:   getSetting("NukeLink.Write.BitDepth",   "16f"),
            compression: getSetting("NukeLink.Write.Compression","none"),
            colorspace:  getSetting("NukeLink.Write.Colorspace", "raw"),
        };

        if (!node._nukeWasConfigured) {
            for (const [name, value] of Object.entries(defaults)) {
                const widget = node.widgets?.find(w => w.name === name);
                if (widget) widget.value = value;
            }
        }

        if (!node._nukeWasConfigured) {
            const previewWidget = node.widgets?.find(w => w.name === "videopreview");
            if (previewWidget) {
                const showDefault = app.ui.settings.getSettingValue("NukeLink.Write.ShowPreviewByDefault", true);
                const playDefault = app.ui.settings.getSettingValue("NukeLink.Write.PlayPreviewByDefault", true);
                previewWidget._state.hidden = !showDefault;
                previewWidget.parentEl.hidden = !showDefault;
                previewWidget._state.paused = !playDefault;
            }
        }

        if (node._nukeLinkPreviewRestore) {
            const r = node._nukeLinkPreviewRestore;
            const previewWidget = node.widgets?.find(w => w.name === "videopreview");
            if (previewWidget) {
                if (r.hidden != null) {
                    previewWidget._state.hidden = r.hidden;
                    previewWidget.parentEl.hidden = r.hidden;
                }
                if (r.paused != null) {
                    previewWidget._state.paused = r.paused;
                }
                if (r.params?.filename) {
                    Object.assign(previewWidget._state.params, r.params);
                    node.updateParameters(r.params, true);
                }
            }
            delete node._nukeLinkPreviewRestore;
        }
    }, 0);
}

function setupNukePathBuilder(node) {
    setTimeout(() => {
        if (node._nukeWasConfigured) return;

        const getSetting = (id, fallback) => {
            const val = app.ui.settings.getSettingValue(id);
            return (val !== undefined && val !== null) ? val : fallback;
        };

        const defaults = {
            name:            getSetting("NukeLink.PathBuilder.Name", ""),
            shot:            getSetting("NukeLink.PathBuilder.Shot", ""),
            file_location:   getSetting("NukeLink.PathBuilder.FileLocation", ""),
            bypass_location: getSetting("NukeLink.PathBuilder.BypassLocation", false),
            name_pattern:    getSetting("NukeLink.PathBuilder.NamePattern", "{shot}_{name}_v{version}"),
            sequence_folder: getSetting("NukeLink.PathBuilder.SequenceFolder", true),
            version_number:  getSetting("NukeLink.PathBuilder.VersionNumber", "001"),
            version_iterate: getSetting("NukeLink.PathBuilder.VersionIterate", true),
            frame_delim:     getSetting("NukeLink.PathBuilder.FrameDelim", "."),
        };

        for (const [name, value] of Object.entries(defaults)) {
            const widget = node.widgets?.find(w => w.name === name);
            if (widget) widget.value = value;
        }
    }, 0);
}

app.registerExtension({
    name: "NukeLink",

    settings: [
        {
            id: "NukeLink.Read.ShowPreviewByDefault",
            name: "Show preview by default",
            tooltip: "When disabled, the preview widget will not show or make any server requests until Re-render preview is selected from the right-click menu.",
            type: "boolean",
            defaultValue: true,
        },
        {
            id: "NukeLink.Read.PlayPreviewByDefault",
            name: "Play preview by default",
            tooltip: "When disabled, the preview widget will be visible but video will start paused.",
            type: "boolean",
            defaultValue: true,
        },
        {
            id: "NukeLink.Read.MissingFrames",
            name: "Default missing frames",
            type: "combo",
            options: ["error", "black", "hold", "nearest"],
            defaultValue: "black",
        },
        {
            id: "NukeLink.Read.Colorspace",
            name: "Default colorspace",
            type: "combo",
            options: ["raw", "sRGB", "linear", "ACEScg"],
            defaultValue: "raw",
        },
        {
            id: "NukeLink.Write.ShowPreviewByDefault",
            name: "Show preview by default",
            tooltip: "When disabled, the preview widget will not show or make any server requests until Re-render preview is selected from the right-click menu.",
            type: "boolean",
            defaultValue: true,
        },
        {
            id: "NukeLink.Write.PlayPreviewByDefault",
            name: "Play preview by default",
            tooltip: "When disabled, the preview widget will be visible but video will start paused.",
            type: "boolean",
            defaultValue: true,
        },
        {
            id: "NukeLink.Write.FileType",
            name: "Default file type",
            type: "combo",
            options: ["exr", "tiff", "png", "jpg", "tga", "bmp"],
            defaultValue: "png",
        },
        {
            id: "NukeLink.Write.BitDepth",
            name: "Default bit depth",
            type: "combo",
            options: ["8", "16", "16f", "32f"],
            defaultValue: "16f",
        },
        {
            id: "NukeLink.Write.Compression",
            name: "Default compression",
            type: "combo",
            options: ["none","rle","zip","zips","piz","pxr24","b44","b44a","dwaa","dwab"],
            defaultValue: "none",
        },
        {
            id: "NukeLink.Write.Colorspace",
            name: "Default colorspace",
            type: "combo",
            options: ["raw", "sRGB", "linear", "ACEScg"],
            defaultValue: "raw",
        },
        {
            id: "NukeLink.Write.FirstFrame",
            name: "Default first frame",
            type: "number",
            attrs: { min: 0, step: 1, max: 99999 },
            defaultValue: 1001,
        },
        {
            id: "NukeLink.PathBuilder.FrameDelim",
            name: "Default frame delim",
            type: "text",
            defaultValue: ".",
        },
        {
            id: "NukeLink.PathBuilder.VersionIterate",
            name: "Default version iterate",
            type: "boolean",
            defaultValue: true,
        },
        {
            id: "NukeLink.PathBuilder.VersionNumber",
            name: "Default version number",
            type: "text",
            defaultValue: "001",
        },
        {
            id: "NukeLink.PathBuilder.SequenceFolder",
            name: "Default sequence folder",
            type: "boolean",
            defaultValue: true,
        },
        {
            id: "NukeLink.PathBuilder.NamePattern",
            name: "Default name pattern",
            type: "text",
            defaultValue: "{shot}_{name}_v{version}",
        },
        {
            id: "NukeLink.PathBuilder.BypassLocation",
            name: "Default bypass location",
            type: "boolean",
            defaultValue: false,
        },
        {
            id: "NukeLink.PathBuilder.FileLocation",
            name: "Default file location",
            type: "text",
            defaultValue: "",
        },
        {
            id: "NukeLink.PathBuilder.Shot",
            name: "Default shot",
            type: "text",
            defaultValue: "",
        },
        {
            id: "NukeLink.PathBuilder.Name",
            name: "Default name",
            type: "text",
            defaultValue: "",
        },
    ],

    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "Read - NukeLink") {
            addVideoPreview(nodeType);
            addPreviewOptions(nodeType);

            chainCallback(nodeType.prototype, "onNodeCreated", function() {
                const node = this;

                node.onConfigure = function(data) {
                    const v = data.widgets_values || [];
                    const wRowA = node.widgets?.find(w => w.name === "_row_a");
                    if (wRowA) wRowA.value = "";
                    node._nukeWasConfigured = true;
                    node._nukeReadRestore = {
                        missing_frames: v[3],
                        colorspace:     v[4],
                        first_frame:    v[5],
                        last_frame:     v[6],
                    };
                    node._nukeLinkPreviewRestore = data.properties?.nukelink_preview_state ?? null;
                };

                node.onSerialize = function(data) {
                    const previewWidget = node.widgets?.find(w => w.name === "videopreview");
                    if (!previewWidget) return;
                    if (!data.properties) data.properties = {};
                    data.properties.nukelink_preview_state = {
                        hidden: previewWidget._state.hidden,
                        paused: previewWidget._state.paused,
                    };
                };

                setupNukeRead(this);

                const fileWidget = this.widgets?.find(w => w.name === "file_path");
                if (!fileWidget) return;

                chainCallback(fileWidget, "callback", (value) => {
                    if (!value) return;
                    const colorspaceWidget = node.widgets?.find(w => w.name === "colorspace");
                    const missingWidget = node.widgets?.find(w => w.name === "missing_frames");
                    const wF = node.widgets?.find(w => w.name === "first_frame");
                    const wL = node.widgets?.find(w => w.name === "last_frame");
                    node.updateParameters({
                        filename: value,
                        first_frame: wF?.value ?? 1001,
                        last_frame: wL?.value ?? 1001,
                        colorspace: colorspaceWidget?.value ?? "raw",
                        missing_frames: missingWidget?.value ?? "black",
                    }, true);
                });
            });
        }

        if (nodeData.name === "Path Builder - NukeLink") {
            const origOnDrawForeground = nodeType.prototype.onDrawForeground;
            nodeType.prototype.onDrawForeground = function(ctx) {
                origOnDrawForeground?.apply(this, arguments);
                if (this.flags?.collapsed) return;

                const widget = this.widgets?.find(w => w.name === "version_number");
                if (!widget || widget.last_y == null) return;

                const stripped = String(widget.value ?? "").trim();
                const isValid = /^\d+$/.test(stripped);
                if (isValid) return;

                const H = LiteGraph.NODE_WIDGET_HEIGHT ?? 20;
                const margin = 15;

                ctx.save();
                ctx.fillStyle = "rgba(255, 0, 0, 0.25)";
                ctx.fillRect(margin, widget.last_y, this.size[0] - margin * 2, H);
                ctx.strokeStyle = "rgba(200, 0, 0, 0.9)";
                ctx.lineWidth = 5;
                const radius = H * 0.75;
                ctx.beginPath();
                ctx.roundRect(margin, widget.last_y, this.size[0] - margin * 2, H, radius);
                ctx.stroke();
                ctx.restore();
            };

            chainCallback(nodeType.prototype, "onNodeCreated", function() {
                const node = this;
                node.onConfigure = function(data) {
                    node._nukeWasConfigured = true;
                };
                setupNukePathBuilder(node);
                setTimeout(() => {
                    const portWidget = node.widgets?.find(w => w.name === "nuke_port");
                    if (portWidget) {
                        portWidget.type = "hidden";
                        portWidget.draw = () => {};
                        portWidget.mouse = () => false;
                        portWidget.computeSize = () => [0, -4];
                    }
                }, 0);

                const container = document.createElement("div");
                container.style.cssText = "width:100%;overflow:visible;";

                const previewEl = document.createElement("div");
                previewEl.style.cssText = "width:100%;font-size:10px;font-style:italic;color:#666;padding:6px 10px 12px;box-sizing:border-box;word-break:break-all;";
                previewEl.textContent = "";
                container.appendChild(previewEl);

                const previewWidget = node.addDOMWidget("pathpreview", "preview", container, {
                    serialize: false,
                    hideOnZoom: false,
                });
                previewWidget.computeSize = function(width) {
                    return [width, previewEl.textContent ? 18 : 0];
                };

                node.updatePreview = async function(force = false) {
                    const path = await resolvePathBuilderPath(node, force);
                    previewEl.textContent = path ?? "";
                    previewWidget.computeSize = function(width) {
                        return [width, path ? previewEl.scrollHeight + 8 : 0];
                    };
                    fitHeight(node);
                };

                setTimeout(() => {
                    if (node._nukeWasConfigured) {
                        node.updatePreview();
                    }
                }, 0);
            });

            chainCallback(nodeType.prototype, "onExecuted", function(message) {
                this.updatePreview();

                if (!message) return;
                const versionWidget = this.widgets?.find(w => w.name === "version_number");
                const iterateWidget = this.widgets?.find(w => w.name === "version_iterate");
                if (!versionWidget || !iterateWidget) return;
                if (!iterateWidget.value) return;

                const stripped = (versionWidget.value ?? "").trim();
                if (!stripped.match(/^\d+$/)) return;

                const padWidth = stripped.length;
                const next = parseInt(stripped, 10) + 1;
                versionWidget.value = String(next).padStart(padWidth, "0");
            });

            addUpdatePathPreviewOption(nodeType);
        }

        if (nodeData.name === "Write - NukeLink") {
            addVideoPreview(nodeType);
            addWriteOptions(nodeType);

            chainCallback(nodeType.prototype, "onNodeCreated", function() {
                const node = this;

                node.onConfigure = function(data) {
                    node._nukeWasConfigured = true;
                    node._nukeLinkPreviewRestore = data.properties?.nukelink_preview_state ?? null;
                };

                node.onSerialize = function(data) {
                    const previewWidget = node.widgets?.find(w => w.name === "videopreview");
                    if (!previewWidget) return;
                    if (!data.properties) data.properties = {};
                    data.properties.nukelink_preview_state = {
                        hidden: previewWidget._state.hidden,
                        paused: previewWidget._state.paused,
                        params: previewWidget._state.params ?? {},
                    };
                };

                setupNukeWrite(node);
            });

            chainCallback(nodeType.prototype, "onExecuted", function(message) {
                const errorMsg = message?.nukelink_error?.[0];
                if (errorMsg) {
                    showToast("error", "Write - NukeLink", errorMsg);
                    return;
                }

                const preview = message?.nukelink_preview?.[0];

                if (!preview || !preview.filename) return;

                const params = {
                    filename:      preview.filename,
                    first_frame:   preview.first_frame,
                    last_frame:    preview.last_frame,
                    colorspace:    preview.colorspace,
                    missing_frames: "black",
                };

                const previewWidget = this.widgets?.find(w => w.name === "videopreview");
                if (previewWidget) {
                    Object.assign(previewWidget._state.params, params);
                }

                this._lastFilePath = preview.filename;
                this._lastExecutionResult = {
                    filename:    preview.filename,
                    first_frame: preview.first_frame,
                    last_frame:  preview.last_frame,
                    colorspace:  preview.colorspace,
                };

                this.updateParameters(params, true);
            });
        }
    }
});

// Configure a Read - NukeLink node with data sent from Nuke.
function nukeLinkApplyRead(node, read) {
    node._nukeWasConfigured = true;
    const showPreview = app.ui.settings.getSettingValue("NukeLink.Read.ShowPreviewByDefault", true);
    const playPreview = app.ui.settings.getSettingValue("NukeLink.Read.PlayPreviewByDefault", true);
    node._nukeLinkPreviewRestore = {
        hidden: !showPreview,
        paused: !playPreview,
    };
    node._nukeReadRestore = {
        first_frame:    read.first_frame,
        last_frame:     read.last_frame,
        colorspace:     read.colorspace,
        missing_frames: read.missing_frames,
    };

    const fileWidget = node.widgets?.find(w => w.name === "file_path");
    if (fileWidget) fileWidget.value = read.file_path;

    setTimeout(() => {
        node.updateParameters({
            filename:       read.file_path,
            first_frame:    read.first_frame,
            last_frame:     read.last_frame,
            colorspace:     read.colorspace,
            missing_frames: read.missing_frames,
        }, true);
    }, 0);
}

function nukeLinkSetWidget(node, name, value) {
    const w = node?.widgets?.find(w => w.name === name);
    if (w) w.value = value;
}

// Instantiate a saved workflow's nodes and links into the CURRENT graph
// (additive - nothing is cleared). Returns the created nodes; groups are
// not imported. Nodes whose pack is missing are skipped with a warning.
function nukeLinkInsertTemplate(template, baseX, baseY) {
    const entries = Array.isArray(template?.nodes) ? template.nodes : [];
    if (!entries.length) return [];

    // Offset so the template's bounding-box top-left lands at (baseX, baseY)
    let minX = Infinity, minY = Infinity;
    for (const e of entries) {
        if (Array.isArray(e.pos)) {
            minX = Math.min(minX, e.pos[0]);
            minY = Math.min(minY, e.pos[1]);
        }
    }
    if (!isFinite(minX)) { minX = 0; minY = 0; }
    const dx = baseX - minX;
    const dy = baseY - minY;

    const idMap = new Map();
    const created = [];

    for (const entry of entries) {
        const node = LiteGraph.createNode(entry.type);
        if (!node) {
            console.warn(`[NukeLink] template: node type not installed, skipped: ${entry.type}`);
            continue;
        }
        app.graph.add(node);

        // configure() restores widgets/slots/properties; feed it a copy with
        // the freshly assigned id and stale link references stripped.
        let data = null;
        try { data = JSON.parse(JSON.stringify(entry)); } catch (e) {}
        if (data) {
            data.id = node.id;
            if (Array.isArray(data.inputs))  data.inputs.forEach(inp => { inp.link = null; });
            if (Array.isArray(data.outputs)) data.outputs.forEach(out => { out.links = []; });
            try { node.configure(data); } catch (e) {
                console.warn(`[NukeLink] template: configure failed for ${entry.type}`, e);
            }
        }
        node.pos = [
            (Array.isArray(entry.pos) ? entry.pos[0] : 0) + dx,
            (Array.isArray(entry.pos) ? entry.pos[1] : 0) + dy,
        ];
        idMap.set(entry.id, node);
        created.push(node);
    }

    // Rebuild links: [id, origin_id, origin_slot, target_id, target_slot, type]
    for (const link of template.links || []) {
        const L = Array.isArray(link)
            ? { o: link[1], os: link[2], t: link[3], ts: link[4] }
            : { o: link.origin_id, os: link.origin_slot, t: link.target_id, ts: link.target_slot };
        const src = idMap.get(L.o);
        const dst = idMap.get(L.t);
        if (!src || !dst) continue;
        try { src.connect(L.os, dst, L.ts); } catch (e) {
            console.warn("[NukeLink] template: could not restore link", link, e);
        }
    }

    return created;
}

api.addEventListener("nukelink.receive", ({ detail }) => {
    const reads        = detail.reads || [];
    const fileLocation = detail.file_location || "";
    const namePattern  = detail.name_pattern || "";
    const versionNumber = detail.version_number || "01";
    const frameDelim   = detail.frame_delim || null;

    if (!reads.length) return;

    const canvas = app.canvas;
    const cx = (canvas.canvas.width  / 2 - canvas.ds.offset[0]) / canvas.ds.scale;
    const cy = (canvas.canvas.height / 2 - canvas.ds.offset[1]) / canvas.ds.scale;

    const VERTICAL_OFFSET = 50;
    const totalHeight = reads.length * VERTICAL_OFFSET;
    const startY = cy - totalHeight / 2;

    // Template chosen in the Nuke send dialog (may be absent). The first Read
    // is injected into the template's own Read - NukeLink node; any remaining
    // Reads are created as plain Read nodes beside it.
    let templateNodes = [];
    let tRead = null;
    let tPB   = null;
    if (detail.template_workflow) {
        templateNodes = nukeLinkInsertTemplate(detail.template_workflow, cx, startY);
        tRead = templateNodes.find(n => n.type === "Read - NukeLink") || null;
        tPB   = templateNodes.find(n => n.type === "Path Builder - NukeLink") || null;
        if (templateNodes.length && !tRead) {
            console.warn("[NukeLink] template has no Read - NukeLink node; sending Reads as plain nodes");
        }
        if (tRead) nukeLinkApplyRead(tRead, reads[0]);
    }

    const bareReads = tRead ? reads.slice(1) : reads;
    const bareX = templateNodes.length ? cx - 480 : cx;

    const readNodes = [];

    bareReads.forEach((read, i) => {
        const node = LiteGraph.createNode("Read - NukeLink");
        if (!node) {
            console.error("[NukeLink] Failed to create Read - NukeLink node");
            return;
        }

        app.graph.add(node);
        node.pos = [bareX - node.size[0] / 2, startY + i * VERTICAL_OFFSET];
        nukeLinkApplyRead(node, read);

        readNodes.push(node);
    });

    // Populate the Path Builder with what Nuke sent - either the template's
    // own Path Builder, or a standalone one dropped next to the Read nodes.
    const populatePB = (pb) => {
        nukeLinkSetWidget(pb, "file_location",  fileLocation);
        nukeLinkSetWidget(pb, "version_number", versionNumber);
        nukeLinkSetWidget(pb, "version_iterate", app.ui.settings.getSettingValue("NukeLink.PathBuilder.VersionIterate", true));
        nukeLinkSetWidget(pb, "shot", detail.shot || "");
        if (namePattern) nukeLinkSetWidget(pb, "name_pattern", namePattern);
        if (frameDelim !== null) nukeLinkSetWidget(pb, "frame_delim", frameDelim);
        nukeLinkSetWidget(pb, "nuke_port", detail.nuke_port || "");
    };

    if (tPB) {
        tPB._nukeWasConfigured = true;
        setTimeout(() => {
            populatePB(tPB);
            app.graph.setDirtyCanvas(true);
        }, 0);
        return;
    }

    if (!detail.send_path_builder) {
        app.graph.setDirtyCanvas(true);
        return;
    }
    setTimeout(() => {
        const pb = LiteGraph.createNode("Path Builder - NukeLink");
        if (!pb) {
            console.error("[NukeLink] Failed to create Path Builder - NukeLink node");
            return;
        }

        pb._nukeWasConfigured = true;
        app.graph.add(pb);

        const anchors = readNodes.length ? readNodes : templateNodes;
        if (anchors.length) {
            const rightmost = anchors.reduce((max, n) => {
                return (n.pos[0] + n.size[0]) > (max.pos[0] + max.size[0]) ? n : max;
            }, anchors[0]);
            const centerY = readNodes.length
                ? startY + (bareReads.length - 1) * VERTICAL_OFFSET / 2
                : rightmost.pos[1];
            pb.pos = [rightmost.pos[0] + rightmost.size[0] + 50, centerY - pb.size[1] / 2];
        } else {
            pb.pos = [cx, cy];
        }

        populatePB(pb);

        app.graph.setDirtyCanvas(true);
    }, 0);
});
