#!/usr/bin/env python

import re
import sys

def convert(string):
    string = string.replace("\x1B[30m", "<span class=\"black\">")
    string = string.replace("\x1B[31m", "<span class=\"red\">")
    string = string.replace("\x1B[32m", "<span class=\"green\">")
    string = string.replace("\x1B[33m", "<span class=\"brown\">")
    string = string.replace("\x1B[34m", "<span class=\"blue\">")
    string = string.replace("\x1B[35m", "<span class=\"purple\">")
    string = string.replace("\x1B[36m", "<span class=\"cyan\">")
    string = string.replace("\x1B[37m", "<span class=\"gray\">")
    string = string.replace("\x1B[1m",  "<span class=\"white\">")
    string = string.replace("\x1B[0m", "</span>")
    return string

with open(sys.argv[1], 'r') as f:
    for line in f:
        print "%s" % convert(line),
    f.close()
