#!/usr/bin/env python3

import subprocess
from i3ipc import Connection, Event

def get_key(number):
    if number > 10:
        return "F%d" % (number - 19)
    else:
        return "%d" % number

def update_keys(i3conn, e):
    workspaces = i3conn.get_tree().workspaces()
    focused = int(i3conn.get_tree().find_focused().workspace().name.split(":")[0])
    output = "a 999999\\n"
    for workspace in workspaces:
        number = int(workspace.name.split(":")[0])
        output += "k %s " % get_key(number)
        if workspace.urgent:
            output += "ff0000\\n"
        if number == focused:
            output += "0000ff\\n"
        else:
            output += "00ff00\\n"
    output += "c"
    p1 = subprocess.Popen(["echo", "-e", output], stdout=subprocess.PIPE)
    p2 = subprocess.Popen(["/usr/bin/g810-led", "-pp"], stdin=p1.stdout, stdout=subprocess.PIPE)
    p2.communicate()

i3 = Connection()
i3.on(Event.WORKSPACE_FOCUS, update_keys)
i3.on('window::urgent', update_keys)
i3.main()
