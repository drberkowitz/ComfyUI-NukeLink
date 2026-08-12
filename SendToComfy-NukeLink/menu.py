import nuke

import sendToComfyUI

if nuke.GUI:
    sendToComfyUI.start_listener()

    # To assign a keyboard shortcut, add it as a third argument below, e.g.:
    #   nuke.menu('Nuke').addCommand('Edit/Node/Send To ComfyUI', 'sendToComfyUI.send_to_comfyui()', 'Ctrl+Shift+C')
    nuke.menu('Nuke').addCommand('Edit/Node/Send To ComfyUI', 'sendToComfyUI.send_to_comfyui()', '')

    # Tab search menu entry
    nuke.menu('Nodes').addMenu("Other","").addCommand('Send To ComfyUI', 'sendToComfyUI.send_to_comfyui()', '')
