#!/usr/bin/env python3

import pprint

def merge_lists_from_dicts():
    data = {'one': [1, 2, 3], 'two': [3, 4, 5]}

    a = {', '.join(data): [*data.values()]}
    b = {', '.join(data): [x for x in data.values()]}
    c = {', '.join(data): [x for n in [*data.values()] for x in n]}
    print(a)
    print(b)
    print(c)

merge_lists_from_dicts()

