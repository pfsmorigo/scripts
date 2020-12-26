#!/usr/bin/env python

import gnomekeyring

def list():
    for keyring in gnomekeyring.list_keyring_names_sync():
        for id in gnomekeyring.list_item_ids_sync(keyring):
            item = gnomekeyring.item_get_info_sync(keyring, id)
            print '[%s] %s = %s' % (
                    keyring, item.get_display_name(), item.get_secret())
        else:
            if len(gnomekeyring.list_item_ids_sync(keyring)) == 0:
                print '[%s] --empty--' % keyring

if __name__ == '__main__':
    list()
