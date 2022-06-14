#!/usr/bin/env python3

import json
import os
import subprocess
import sys

class Proxy:
    def lxd(self, host, port):
        for node in json.loads(self.__exec("lxc list --format=json")):
            if node["name"] == host:
                for net in node["state"]["network"]["eth0"]["addresses"]:
                    if net["family"] == "inet" and net["scope"] == "global":
                        return net["address"]
        return None

    def mp(self, host, port):
	# multipass list --format csv | grep  $HOST | cut -d, -f3
        pass

    def virsh(self, host, port):
	# virsh --connect qemu:///system domifaddr $HOST | awk -F'[ /]+' '{if (NR>2 && $5) print $5}' | tail -1
        pass

    def __exec(self, command):
        return subprocess.run(command.split(" "),
                stdout=subprocess.PIPE).stdout.decode('utf-8')

proxy = Proxy()
host, domain = tuple(sys.argv[1].split("."))
port = sys.argv[2]
ip = getattr(proxy, domain)(host, port)
os.system(f"nc {ip} {port}")
