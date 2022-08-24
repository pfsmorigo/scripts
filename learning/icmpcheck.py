#!/usr/bin/env python3

import subprocess
import sys
from smtplib import SMTP

if len(sys.argv) == 1:
    print("You need an domain")
    sys.exit(1)

domain = sys.argv[1]

status = 0
with SMTP(domain) as smtp:
    try:
        status = smtp.noop()[0]
    except:
        status = -1

if status = 250:
    print("Domain is ON")
else:
    print("Domain is OFF (%d)", status)
