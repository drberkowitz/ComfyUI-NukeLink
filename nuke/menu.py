import nuke

# Change the path below to wherever you want to keep 'sendToComfyUI.py' and ideally put this line of code in your init.py nuke file if you can.
# Here the 'sendToComfyUI.py' file is in a subfolder called 'python' in the same directory as this menu.py file.  You can also put it in your .nuke folder or any other location you want, just make sure to change the path below to match.
nuke.pluginAddPath( './python/' )

import sendToComfyUI

sendToComfyUI.start_listener()

# Add the menu entry to your custom tools/gizmo menu if you want
nodesMenu = nuke.menu('Nodes').addMenu("SendToComfyUI","")
nodesMenu.addCommand("Send To ComfyUI", "sendToComfyUI.send_to_comfyui()", "")