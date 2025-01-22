#!/usr/bin/env python3

import json
import os
import subprocess
import sys

BLOCK_START = '# Dynamic Hosts'
HOST_FILE = '/etc/hosts'

def update_hosts(hosts):
    with open(HOST_FILE) as f:
        lines = f.read().splitlines()

    with open(HOST_FILE,'wt') as f:
        for line in lines:
            if line != BLOCK_START:
                f.write(f'{line}\n')
                continue

        f.write(f'\n{BLOCK_START}\n')
        for host in hosts:
            f.write(f'{hosts[host]}\t{host}\n')

def __exec(command):
    return subprocess.run(command.split(' '),
            stdout=subprocess.PIPE).stdout.decode('utf-8')

hosts = {}
for node in json.loads(__exec('lxc list --format=json')):
    if node['state']['status'] == 'Running':
        hostname = node['name']
        for net in node['state']['network']['eth0']['addresses']:
            if net['family'] == 'inet' and net['scope'] == 'global':
                    ip = net['address']
                    hosts[hostname+'.lxd'] = ip
                    break

update_hosts(hosts)
