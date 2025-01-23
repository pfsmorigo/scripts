#!/usr/bin/env python3

import sys
import pprint

DISPLAYS = ["DP-1", "HDMI-1", "eDP-1"]
RES_1080P = [1920, 1080]
RES_1440P = [2560, 1440]
RES_2160P = [3840, 2160]

options = {
        "Only primary": {"eDP-1": RES_1080P},
        "Only secondary (1080p)": {"HDMI-1": RES_1080P},
        "Only secondary (1440p)": {"HDMI-1": RES_1440P},
        "Only secondary (2160p)": {"HDMI-1": RES_2160P},
        "Above (1080p)": {"eDP-1": RES_1080P, "HDMI-1": res_1080p},
        "Above (1440p)": {"eDP-1": RES_1080P, "HDMI-1": RES_1440P},
        "Above (2160p)": {"eDP-1": RES_1080P, "HDMI-1": RES_2160P},
        }

def set_display(string):
    if string not in options:
        print(f"Option '{string}' not available!", file=sys.stderr)
        sys.exit(1)

    option = options[string]
    command = "xrandr"
    for display in DISPLAYS:
        command += f" --output {display}"
        command += f" --mode {'x'.join(map(str, option[display]))}" \
                if display in option else " --off"

    print(command)

if len(sys.argv) == 1:
    for option in options:
        print(option)
else:
    set_display(" ".join(sys.argv[1:]))
