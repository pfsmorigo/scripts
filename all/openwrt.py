#!/usr/bin/env python3

import subprocess

ROUTERS = ["brno", "extender"]
# ROUTERS = ["router"]
WLANS = ["wlan0", "wlan1"]

PRI_5G = 94
PRI_2G = 34
SEC_5G = 92
SEC_2G = 32
MOVING = 93

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

def get_iw_info(host, wlan):
    result = {}
    station = ""

    command = subprocess.run(["ssh", host, "iw", "dev", wlan, "station", "dump"], stdout=subprocess.PIPE)
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

dhcp = get_dhcp_lease("brno")

iw_info = {}
for router in ROUTERS:
    iw_info[router] = {}
    for wlan in WLANS:
        iw_info[router][wlan] = get_iw_info(router, wlan)

for mac in sorted(dhcp, key=lambda x: tuple(int(p) for p in dhcp[x]["ipv4"].split('.'))):
    routers = []
    wlans = []

    for router in ROUTERS:
        for wlan in WLANS:
            if mac in iw_info[router][wlan]:
                routers.append(router)
                wlans.append(wlan)

    hostname = dhcp[mac]["hostname"]
    ipv4 = dhcp[mac]["ipv4"]
    router = ""
    wlan = ""
    rx = ""
    tx = ""
    signal = ""

    if not routers:
        color = 37
    else:
        rx = " ".join(iw_info[routers[0]][wlans[0]][mac]["rx bitrate"].split(" ")[:2])[:-6]
        tx = " ".join(iw_info[routers[0]][wlans[0]][mac]["tx bitrate"].split(" ")[:2])[:-6]
        signal = " ".join(iw_info[routers[0]][wlans[0]][mac]["signal"].split(" "))[:-4]
        router = routers[0] if len(routers) == 1 else "both"
        wlan = wlans[0] if len(wlans) == 1 else "both"

        if "both" in [router, wlan]:
            color = MOVING
        elif "extender" not in routers:
            color = PRI_5G if "wlan1" not in wlans else PRI_2G
        else:
            color = SEC_5G if "wlan1" not in wlans else SEC_2G

    print("\033[%dm%-18s %-25s %-11s %-9s %-5s %7s %7s %-24s\033[0m"
            % (color, mac, hostname, ipv4, router, wlan, rx, tx, signal))

