#!/usr/bin/env python3

import subprocess
from i3ipc import Connection, Event

import time
from threading import Thread

import psutil

from colour import Color

def update_i3_keys(i3conn, e):
    global keys_i3
    new_keys_i3 = ""
    workspaces = i3conn.get_tree().workspaces()
    focused = int(i3conn.get_tree().find_focused().workspace().name.split(":")[0])
    for workspace in workspaces:
        number = int(workspace.name.split(":")[0])
        new_keys_i3 += "k %s " % workspace2key(number)
        if workspace.urgent:
            new_keys_i3 += "ff0000\\n"
        if number == focused:
            new_keys_i3 += "0000ff\\n"
        else:
            new_keys_i3 += "00ff00\\n"
    keys_i3 = new_keys_i3
    update_keys()

def workspace2key(number):
    if number > 10:
        return "F%d" % (number - 19)
    else:
        return "%d" % number

def monitor_cpu(colors):
    global keys_cpu
    while True:
        new_keys_cpu = ""
        cpus = psutil.cpu_percent(interval=0.5, percpu=True)
        overall = sum(cpus) / len(cpus)
        for i in range(len(cpus)):
            new_keys_cpu += "k num%d %s\\n" % (i + 1, colors[int(cpus[i])].hex_l[1:])
        new_keys_cpu += "k num9 %s\\n" % colors[int(overall)].hex_l[1:]
        keys_cpu = new_keys_cpu
        update_keys()

def update_keys():
    global keys_i3
    global keys_cpu

    output = "a 999999\\n%s\\n%s\\nc" % (keys_i3, keys_cpu)

    p1 = subprocess.Popen(["echo", "-e", output], stdout=subprocess.PIPE)
    p2 = subprocess.Popen(["/usr/bin/g810-led", "-pp"], stdin=p1.stdout, stdout=subprocess.PIPE)
    p2.communicate()

keys_i3 = ""
keys_cpu = ""

red = Color("green")
colors = list(red.range_to(Color("red"), 101))

t = Thread(target=monitor_cpu, args=(colors,))
t.start()

i3 = Connection()
i3.on(Event.WORKSPACE_FOCUS, update_i3_keys)
i3.on('window::urgent', update_i3_keys)
i3.main()
