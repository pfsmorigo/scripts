#!/usr/bin/python

import urllib2
import json
#from pprint import pprint

response = urllib2.urlopen('http://developers.agenciaideias.com.br/cotacoes/json')
data = json.load(response)
#pprint(data)

bovespa = data['bovespa']['cotacao']+" ("+data['bovespa']['variacao']+")"
dolar = data['dolar']['cotacao']+" ("+data['dolar']['variacao']+")"
euro = data['euro']['cotacao']+" ("+data['euro']['variacao']+")"

print "Bovespa: %s, US$ %s, EURO %s" % (bovespa, dolar, euro)
