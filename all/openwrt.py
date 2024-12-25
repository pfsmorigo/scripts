#!/usr/bin/env python3

import argparse
import re
import sys
import subprocess
from collections import defaultdict

PRI_5G = 94
PRI_2G = 34
SEC_5G = 92
SEC_2G = 32

COLORS = [[94, 34], [92,32], [93, 33]]
MOVING = [91,31]

ONLINE = 35
OFFLINE = 37

def get_dhcp_lease(host):
    result = {}
    command = subprocess.run(['ssh', host, 'cat', '/tmp/dhcp.leases'], stdout=subprocess.PIPE)
    string = command.stdout.decode('utf-8')
    for line in string.split('\n'):
        if line:
            line_strip = line.split(' ')
            mac = line_strip[1]
            ipv4 = line_strip[2]
            hostname = line_strip[3]
            result[mac] = {'ipv4': ipv4, 'hostname': hostname}
    return result

def get_iw_devs(host):
    result = []
    command = subprocess.run(['ssh', host, 'iw', 'dev'], stdout=subprocess.PIPE)
    string = command.stdout.decode('utf-8')
    for line in [l for l in string.split('\n') if 'Interface' in l]:
        result.append(line.split()[1])
    return result

def get_iw_info(host, dev):
    result = {}
    station = ''
    command = subprocess.run(['ssh', host, 'iw', 'dev', dev, 'station', 'dump'], stdout=subprocess.PIPE)
    string = command.stdout.decode('utf-8')
    for line in string.split('\n'):
        if line.startswith('Station'):
            station = line.split(' ')[1]
            result[station] = {}
        else:
            field = line.split(':')[0].strip()
            if field:
                result[station][field] = line.split(':')[1].strip()
    return result

def load_iw_info(routers):
    result = {}
    for router in routers:
        result[router] = {}
        for dev in get_iw_devs(router):
            result[router][freq_translate(dev)] = get_iw_info(router, dev)
    return result

def freq_translate(freq):
    if freq in ['wlan0', 'phy0-ap0']:
        return '5ghz'
    elif freq in ['wlan1', 'phy1-ap0']:
        return '2ghz'
    else:
        return freq

def run_ping(ip, timeout=3):
    status, result = subprocess.getstatusoutput(f'ping -c1 -w{timeout} {ip}')
    matches = re.findall(r'\btime=(\d+(?:\.\d+)?)\s+ms\b', result)
    try:
        return round(float(matches[0]), 1) if status == 0 else ''
    except:
        return '?'

parser = argparse.ArgumentParser(description='OpenWRT status')
parser.add_argument('-p', '--ping', action='store_true', help='Ping all hosts')
parser.add_argument('--on', action='store_true', help='Show only online hosts')
parser.add_argument('--off', action='store_true', help='Show only offline hosts')
parser.add_argument('devices', nargs='+', metavar='DEVICE', help='Device list')

args = parser.parse_args()

dhcp = get_dhcp_lease(args.devices[0])
iw_info = load_iw_info(args.devices)
stats = defaultdict(defaultdict(int))

for mac in sorted(dhcp, key=lambda x: tuple(int(p) for p in dhcp[x]['ipv4'].split('.'))):
    routers = []
    wlans = []

    for router in args.devices:
        for dev in iw_info[router]:
            if mac in iw_info[router][dev]:
                routers.append(router)
                wlans.append(freq_translate(dev))

    hostname = dhcp[mac]['hostname']
    ipv4 = dhcp[mac]['ipv4']
    router = ''
    freq = ''
    rx = ''
    tx = ''
    signal = ''
    ping = ''

    if not routers:
        ping = run_ping(ipv4)
        color = ONLINE if ping else OFFLINE
    else:
        rx = ' '.join(iw_info[routers[0]][wlans[0]][mac]['rx bitrate'].split(' ')[:2])[:-6]
        tx = ' '.join(iw_info[routers[0]][wlans[0]][mac]['tx bitrate'].split(' ')[:2])[:-6]
        signal = ' '.join(iw_info[routers[0]][wlans[0]][mac]['signal'].split(' '))[:-4]
        router = ','.join(list(set(routers)))
        freq = ','.join(list(set(wlans)))

        if len(routers) > 1:
            color = MOVING[0]
        elif len(wlans) > 1:
            color = MOVING[1]
        else:
            color_index = args.devices.index(router)
            color = COLORS[color_index][1 if '5ghz' not in wlans else 0]

    if ping != '' and not args.ping:
        ping = ''
    elif ping == '' and args.ping:
        ping = run_ping(ipv4)

    print(f'\033[{color}m{mac:18}  {hostname:25}  {ipv4:10}  {ping:4}  {router:5}  {freq:4}  {rx:>7}  {tx:>7}  {signal}\033[0m')



