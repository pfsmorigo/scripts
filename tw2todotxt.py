#!/bin/python

#import os
#import json
#from pprint import pprint

#list = os.popen('task status:pending export').read()

##json_data=open('json_data')
##data = json.load(list)
##pprint(data)
##json_data.close()

#data = []
#for line in list:
    #data.append(json.loads(line))

##print list


#import json

#data = [ { 'a':'A', 'b':(2, 4), 'c':3.0 } ]
#data_string = json.dumps(data)
#print 'ENCODED:', data_string

#decoded = json.loads(data_string)
#print 'DECODED:', decoded

#print 'ORIGINAL:', type(data[0]['b'])
#print 'DECODED :', type(decoded[0]['b'])




import json

data = []
with open('file') as f:
    for line in f:
        data.append(json.loads(line))
