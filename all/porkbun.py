#!/usr/bin/env python3

import logging
import os
import sys
import requests
import argparse

API_URL = 'https://porkbun.com/api/json/v3'
CERTIFICATE_PATH = '/etc/ssl/letsencrypt'
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(message)s'

def post_data(path, payload={}):
    url = f'{API_URL}/{path}'
    json = {'apikey': args.api_key, 'secretapikey': args.secret_key}
    json.update(payload)
    logging.debug(f'URL: {url}')
    logging.debug(f'Payload: {json}')
    r = requests.post(url, json=json)
    data = r.json()
    logging.debug(f'Result: {data}')
    if data['status'] == 'ERROR':
        logging.error(data['message'])
        sys.exit(1)
    return data

def get_new_ips():
    logging.info('Get current IPs...')
    ipv4 = requests.get('https://api.ipify.org?format=json').json()['ip']
    ipv6 = requests.get('https://api64.ipify.org?format=json').json()['ip']
    logging.info(f'Current IPs: {ipv4} / {ipv6}')
    return [ipv4, ipv6]

def get_old_ips(domain, record):
    logging.info(f'Get IP set in porkbun for {domain} {record}...')
    ipv4 = post_data(f'dns/retrieveByNameType/{domain}/A/{record}')['records'][0]['content']
    ipv6 = post_data(f'dns/retrieveByNameType/{domain}/AAAA/{record}')['records'][0]['content']
    logging.info(f'Porkbun IPs: {ipv4} / {ipv6}')
    return [ipv4, ipv6]

def get_certificate(domain):
    logging.info(f"Downloading SSL bundle for '{domain}'...")
    data = post_data(f'ssl/retrieve/{domain}')

    for filename, field in [('fullchain.pem', 'certificatechain'), ('privkey.pem', 'privatekey')]:
       logging.info(f'Saving certificate to "{CERTIFICATE_PATH}/{filename}"...')
       with open(f'{CERTIFICATE_PATH}/{filename}', 'w') as f:
           f.write(data[field])

def update_dns(domain, record, force=False):
    logging.info(f"Updating DNS if necessary...")
    old = get_old_ips(domain, record)
    new = get_new_ips()
    if old != new or force:
        for count, value in enumerate(new):
            domain_type = 'A' if not count else 'AAAA'
            payload = {'content': value, 'ttl': '600'}
            post_data(f'dns/editByNameType/{domain}/{domain_type}/{record}', payload)

if __name__ == "__main__":
    parser= argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="count", default=1, help="Verbosity")
    parser.add_argument('domain')
    parser.add_argument('record')
    parser.add_argument('api_key')
    parser.add_argument('secret_key')
    args = parser.parse_args()

    if args.verbose:
        verbose = 40 - (10 * args.verbose) if args.verbose > 0 else 0
        logging.basicConfig(format="%(levelname)s: %(message)s", level=verbose)

    get_certificate(args.domain)
    update_dns(args.domain, args.record)
