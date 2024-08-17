#!/usr/bin/env python3

import argparse
import re
import sys
import subprocess

PRI_5G = 94
PRI_2G = 34
SEC_5G = 92
SEC_2G = 32
MOVING = 93
ONLINE = 35
OFFLINE = 37

def get_dhcp_lease(host):
    result = {}
    command = subprocess.run(["ssh", host, "cat", "/tmp/dhcp.leases"], stdout=subprocess.PIPE)
    string = command.stdout.decode("utf-8")
    for line in string.split("\n"):
        if line:
            line_strip = line.split(" ")
            mac = line_strip[1]
            ipv4 = line_strip[2]
            hostname = line_strip[3]
            result[mac] = {"ipv4": ipv4, "hostname": hostname}
    return result

def get_iw_devs(host):
    result = []
    command = subprocess.run(["ssh", host, "iw", "dev"], stdout=subprocess.PIPE)
    string = command.stdout.decode("utf-8")
    for line in [l for l in string.split("\n") if 'Interface' in l]:
        result.append(line.split()[1])
    return result

def get_iw_info(host, dev):
    result = {}
    station = ""
    command = subprocess.run(["ssh", host, "iw", "dev", dev, "station", "dump"], stdout=subprocess.PIPE)
    string = command.stdout.decode("utf-8")
    for line in string.split("\n"):
        if line.startswith("Station"):
            station = line.split(" ")[1]
            result[station] = {}
        else:
            field = line.split(":")[0].strip()
            if field:
                result[station][field] = line.split(":")[1].strip()
    return result

def load_iw_info(routers):
    result = {}
    for router in routers:
        result[router] = {}
        for dev in get_iw_devs(router):
            result[router][dev] = get_iw_info(router, dev)
    return result

def run_ping(ip, timeout=3):
    status, result = subprocess.getstatusoutput(f'ping -c1 -w{timeout} {ip}')
    matches = re.findall(r"\btime=(\d+(?:\.\d+)?)\s+ms\b", result)
    try:
        return round(float(matches[0]), 1) if status == 0 else ''
    except:
        return '?'

parser = argparse.ArgumentParser(description="OpenWRT status")
parser.add_argument("-p", "--ping", action="store_true", help="Ping all hosts")
parser.add_argument("--on", action="store_true", help="Show only online hosts")
parser.add_argument("--off", action="store_true", help="Show only offline hosts")
parser.add_argument("devices", nargs='+', metavar='DEVICE', help="Device list")

args = parser.parse_args()

dhcp = get_dhcp_lease(args.devices[0])
iw_info = load_iw_info(args.devices)

for mac in sorted(dhcp, key=lambda x: tuple(int(p) for p in dhcp[x]["ipv4"].split('.'))):
    routers = []
    wlans = []

    for router in args.devices:
        for dev in iw_info[router]:
            if mac in iw_info[router][dev]:
                routers.append(router)
                wlans.append(dev)

    hostname = dhcp[mac]["hostname"]
    ipv4 = dhcp[mac]["ipv4"]
    router = ""
    wlan = ""
    rx = ""
    tx = ""
    signal = ""
    ping = ""

    if not routers:
        ping = run_ping(ipv4)
        color = ONLINE if ping else OFFLINE
    else:
        rx = " ".join(iw_info[routers[0]][wlans[0]][mac]["rx bitrate"].split(" ")[:2])[:-6]
        tx = " ".join(iw_info[routers[0]][wlans[0]][mac]["tx bitrate"].split(" ")[:2])[:-6]
        signal = " ".join(iw_info[routers[0]][wlans[0]][mac]["signal"].split(" "))[:-4]
        router = routers[0] if len(routers) == 1 else "both"
        wlan = wlans[0] if len(wlans) == 1 else "both"

        if "both" in [router, wlan]:
            color = MOVING
        elif args.devices[0] in routers:
            color = PRI_5G if "wlan1" not in wlans else PRI_2G
        else:
            color = SEC_5G if "wlan1" not in wlans else SEC_2G

    if ping != '' and not args.ping:
        ping = ''
    elif ping == '' and args.ping:
        ping = run_ping(ipv4)

    print("\033[%dm%-18s %-25s %-11s %5s  %-9s %-5s %7s %7s %-24s\033[0m"
            % (color, mac, hostname, ipv4, ping, router, wlan, rx, tx, signal))

