#!/usr/bin/python

import keyring;

def get_password(service, username):
    return keyring.get_password(service, username)
