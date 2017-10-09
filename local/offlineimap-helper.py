#!/usr/bin/python

import commands

def get_password(name):
    return commands.getoutput("pass %s" % (name))
