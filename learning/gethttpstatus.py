#!/usr/bin/env python3

import sys
import requests
import socket
from geoip import geolite2

if len(sys.argv) == 1:
    print("Preciso de uma URL")
    sys.exit(1)

hostname = sys.argv[1]

for protocol in ['http', 'https']:
    try:
        r = requests.head(protocol + "://" + url)
        print("server: {}://{}".format(protocol, url))
        print("status: {}".format(r.status_code))
    except requests.ConnectionError:
        print("failed to connect")

match = geolite2.lookup(socket.gethostbyname(hostname))
if match is not None:
    print('geoipserver: {}, {}'.format(match.country, match.continent))
