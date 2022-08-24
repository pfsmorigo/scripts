#!/usr/bin/env python3

import subprocess
import sys

if len(sys.argv) == 1:
    print("You need an IP address")
    sys.exit(1)

ip = sys.argv[1]
out = subprocess.Popen(['ping', '-c', '1', ip], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

ttl=0
for line in out.stdout.readlines():
    for word in str(line).split(" "):
        if "ttl=" in word:
            ttl = int(word.split("=")[1])

if ttl == 64:
    print("Linux or FreeBSD")
elif ttl == 128:
    print("Windows")
elif ttl == 255:
    print("iOS")
else:
    print("Another (%d)" % ttl)
