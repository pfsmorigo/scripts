#!/usr/bin/env python3

import logging

sh = logging.StreamHandler()
sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
sh.setLevel(logging.INFO)

fh = logging.FileHandler("/tmp/logfile", "a")
fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
fh.setLevel(logging.DEBUG)

log = logging.getLogger()  # root logger
log.setLevel(logging.DEBUG)
log.addHandler(sh)
log.addHandler(fh)

logging.debug("debug")
logging.info("info")

# for hdlr in log.handlers[:]:  # remove all old handlers
        # log.removeHandler(hdlr)
