#!/usr/bin/env python3

import subprocess
from i3ipc import Connection, Event

import time
from threading import Thread

import psutil

from colour import Color

import os

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

    keys_all = "ff9999" if is_screensaver_active() else "999999"
    keys_alarm = "k pause_break "
    keys_alarm += "ff0000" if alarm is True else "0000ff"
    output = "a %s\\n%s\\n%s\\n%s\\nc" % (keys_all, keys_i3, keys_cpu, keys_alarm)
    # print(output)

    p1 = subprocess.Popen(["echo", "-e", output], stdout=subprocess.PIPE)
    p2 = subprocess.Popen(["/usr/bin/g810-led", "-pp"], stdin=p1.stdout, stdout=subprocess.PIPE)
    p2.communicate()

def keyboard_is_present():
    return os.path.exists("/dev/input/by-id/usb-Logitech_G512_SE_065938723531-event-kbd")

if keyboard_is_present():
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
