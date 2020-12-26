#!/usr/bin/env python

import socket
import subprocess
import sys
import telnetlib
import time

if len(sys.argv) < 2:
    print "You need <command> <host> <port>"
    sys.exit()

host = sys.argv[1]
port = int(sys.argv[2])

try:
    tn = telnetlib.Telnet(host, port, 5)
    dump = tn.read_all().split(";")
    tn.close()
except socket.timeout:
    print "Server Timeout"
    sys.exit(1)

servertime_line = [s for s in dump if "CurrentServerTime" in s]
servertime = int(''.join(servertime_line).split(":")[1])

players_line = [s for s in dump if "CurrentPlayers" in s]
players = int(''.join(players_line).split(":")[1])

day = (servertime/24000)+1
week = day%7
store = (day-1)%3
hour = int(float((servertime%24000)/1000))
mins = int(float(float(servertime%1000)*60)/1000)

time_next = 4 if (hour < 4 or hour >= 22) else 22
time_next += 24 if (time_next < hour) else 0
left = ((((time_next-hour)*60)-mins)/60.)*2.5

print "%d-%d-%d %dh%02d(%.0f) %d" % (day, week, store, hour, mins, left, players)
