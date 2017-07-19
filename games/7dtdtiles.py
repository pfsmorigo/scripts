#!/bin/python

total=41

print "total: %s" % (total)
print "      1234567890123456789012345678901234567890"

line = '+'
for num in range(0, total - 2):
    line += '-'
line += '+'

print "     %s" % line

for tries in range(2, total):
    if ((total - 1) % tries):
        continue

    light = ''
    for num in range(0, total + 1):
        if num % tries:
            light += ' '
        else:
            light += 'x'
    print "%4d %s" % (tries, light)




