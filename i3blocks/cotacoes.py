#!/usr/bin/python

import urllib2
import json
import sys
#from pprint import pprint

response = urllib2.urlopen('http://developers.agenciaideias.com.br/cotacoes/json')
data = json.load(response)
#pprint(data)

if len(sys.argv) == 1:
    print 'need: dolar, euro or bovespa'
else:
    print data[sys.argv[1]]['cotacao']+' ('+data[sys.argv[1]]['variacao']+')'
