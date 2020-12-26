#!/usr/bin/env python3

import subprocess
from i3ipc import Connection, Event

import time
from threading import Thread

import psutil

from colour import Color

import os
import sys

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

def monitor_cpu():
    global keys_cpu
    while True:
        new_keys_cpu = ""

        cpus = psutil.cpu_percent(interval=0.5, percpu=True)

        for i in range(len(cpus)):
            new_keys_cpu += "k num%d %s\\n" % (i + 1, get_color(cpus[i]))

        overall = sum(cpus) / len(cpus)
        new_keys_cpu += "k num9 %s\\n" % get_color(overall)

        keys_cpu = new_keys_cpu
        update_keys()
        check_alarms()

def check_alarms():
    global alarm
    # alarm = False if alarm else True

def is_screensaver_active():
    result = subprocess.run(['/usr/bin/xfce4-screensaver-command', '-q'], stdout=subprocess.PIPE)
    return False if b"The screensaver is inactive" in result.stdout else True

def is_syncthing_active():
    result = subprocess.run(['/usr/bin/pgrep', 'syncthing'], stdout=subprocess.PIPE)
    return False if len(result.stdout.strip()) == 0 else True

def get_color(percentage):
    global colors
    shift = 30
    value = percentage + shift
    value = value if value < 100 else 100
    return colors[int(value)].hex_l[1:]

def update_keys():
    global keys_i3
    global keys_cpu
    global alarm

    # All keys color / i3 / cpu usage
    output = "a ff9999" if is_screensaver_active() else "a 999999"
    output += "\\n%s\\n%s" % (keys_i3, keys_cpu)

    # Alarm
    output += "\\nk pause_break "
    output += "ff0000" if alarm is True else "0000ff"

    # Syncthing
    output += "\\nk s "
    output += "0000ff" if is_syncthing_active() is True else "ff0000"

    # Commit
    output += "\\nc\\n"
    # print(output)

    p1 = subprocess.Popen(["echo", "-e", output], stdout=subprocess.PIPE)
    p2 = subprocess.Popen(["/usr/bin/g810-led", "-pp"], stdin=p1.stdout, stdout=subprocess.PIPE)
    p2.communicate()

def is_keyboard_present():
    #return os.path.exists("/dev/input/by-id/usb-Logitech_G512_SE_065938723531-event-kbd")
    return os.path.exists("/dev/input/by-id/usb-Logitech_G512_RGB_MECHANICAL_GAMING_KEYBOARD_097A38553232-event-kbd")

def is_process_running():
    curpid = os.getpid()
    for p in psutil.process_iter():
        if p.pid != curpid \
                and len(p.cmdline()) > 1 \
                and p.cmdline()[0] == "python3" \
                and p.cmdline()[1].endswith("/keyboardleds.py"):
            print("Process already running (%s)" % p.pid)
            return True
    return False

if not is_process_running() and is_keyboard_present():
    keys_i3 = ""
    keys_cpu = ""
    alarm = False

    red = Color("green")
    colors = list(red.range_to(Color("red"), 101))

    t = Thread(target=monitor_cpu)
    t.start()

    i3 = Connection()
    i3.on(Event.WORKSPACE_FOCUS, update_i3_keys)
    i3.on('window::urgent', update_i3_keys)
    i3.main()
