#!/usr/bin/env python3

import logging
import os
import sys
import requests
import argparse
import subprocess
import datetime

LOG_FORMAT = '%(asctime)s [%(levelname)s] %(message)s'
API_URL = 'https://porkbun.com/api/json/v3'
CERTIFICATE_PATH = '/etc/ssl/letsencrypt'
CERTIFICATES = ["certificatechain", "intermediatecertificate", "publickey", "privatekey"]
MINIMAL_DAYS = 15

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
    return {'v4': ipv4, 'v6': ipv6}

def get_old_ips(domain, record):
    logging.info(f'Get IP set in porkbun for {domain} {record}...')
    ipv4 = post_data(f'dns/retrieveByNameType/{domain}/A/{record}')['records'][0]['content']
    ipv6 = post_data(f'dns/retrieveByNameType/{domain}/AAAA/{record}')['records'][0]['content']
    logging.info(f'Porkbun IPs: {ipv4} / {ipv6}')
    return {'v4': ipv4, 'v6': ipv6}

def get_certificate(domain):
    not_after = subprocess.check_output(['openssl', 'x509', '-enddate', '-noout', '-in',
        f'{args.ssl_dir}/fullchain.pem']).decode("utf-8")
    not_after = datetime.datetime.strptime(not_after, 'notAfter=%b %d %H:%M:%S %Y %Z\n')
    days = (not_after - datetime.datetime.now()).days
    logging.info(f'Certificate valid for {days} days...')

    if days > MINIMAL_DAYS:
        return

    logging.info(f"Downloading SSL bundle for '{domain}'...")
    data = post_data(f'ssl/retrieve/{domain}')
    fullchain = ''

    for certificate in CERTIFICATES:
       logging.info(f'Saving certificate to "{args.ssl_dir}/{certificate}.pem"...')
       with open(f'{args.ssl_dir}/{certificate}.pem', 'w') as f:
           f.write(data[certificate])
           if certificate != 'publickey':
               fullchain += f'{data[certificate]}\n'

    logging.info(f'Creating fullchain certificate...')
    with open(f'{args.ssl_dir}/fullchain.pem', 'w') as f:
        f.write(fullchain.replace('\n\n','\n'))

def update_dns(domain, record, force=False):
    logging.info(f'Updating DNS if necessary...')
    old = get_old_ips(domain, record)
    new = get_new_ips()

    for ip in ['v4', 'v6']:
        if old[ip] != new[ip] or force:
            logging.info(f'IP{ip} changed...')
            domain_type = 'A' if ip == 'v4' else 'AAAA'
            payload = {'content': new[ip], 'ttl': '600'}
            post_data(f'dns/editByNameType/{domain}/{domain_type}/{record}', payload)

if __name__ == '__main__':
    parser= argparse.ArgumentParser()
    parser.add_argument('--verbose', '-v', action='count', default=1, help='verbosity')
    parser.add_argument('--cert', '-c', action='store_true', help='only install certificates')
    parser.add_argument('--dns', '-d', action='store_true', help='only update DNS')
    parser.add_argument('--ssl-dir', default=CERTIFICATE_PATH, help='certificates install path')

    parser.add_argument('domain')
    parser.add_argument('record')
    parser.add_argument('api_key')
    parser.add_argument('secret_key')
    args = parser.parse_args()

    if args.verbose:
        verbose = 40 - (10 * args.verbose) if args.verbose > 0 else 0
        logging.basicConfig(format='%(levelname)s: %(message)s', level=verbose)

    if not args.dns:
        get_certificate(args.domain)
    if not args.cert:
        update_dns(args.domain, args.record)
