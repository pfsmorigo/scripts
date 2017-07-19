#!/usr/bin/env python

import sys
import telnetlib
import subprocess
import time

# ps = subprocess.Popen("ps -eaf | grep '7[D]aysToDie'", shell=True, stdout=subprocess.PIPE)

# if len(ps.stdout.read()) is 0:
    # sys.exit()

if len(sys.argv) < 2:
    print "You need <command> <host> <port>"
    sys.exit()

host = sys.argv[1]
port = int(sys.argv[2])

tn = telnetlib.Telnet(host, port)
dump = tn.read_all().split(";")
tn.close()

servertime_line = [s for s in dump if "CurrentServerTime" in s]
servertime = int(''.join(servertime_line).split(":")[1])

players_line = [s for s in dump if "CurrentPlayers" in s]
players = int(''.join(players_line).split(":")[1])

day = int((servertime/24000)+1)
week = day%7
hour = int(float((servertime%24000)/1000))
mins = int(float(float(servertime%1000)*60)/1000)

time_next = 4 if (hour < 4 or hour > 22) else 22
left_secs = time.time()+((time_next-hour)*60)+(60-mins)*2.5
left_time = time.strptime(time.ctime(left_secs))
left = time.strftime("%Hh%M", left_time)

#print "%d/%d %dh%02d %s %d %d" % (day, week, hour, mins, left, players)
print "%d/%d %dh%02d %d" % (day, week, hour, mins, players)
