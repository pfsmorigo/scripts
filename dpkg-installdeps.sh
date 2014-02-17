#!/bin/bash

PACKAGES=$(dpkg-buildpackage 2>&1 | grep "Unmet build dependencies:" | cut -d " " -f 5- | sed 's/([^)]*)//g;s/  */ /g')

for PACKAGE in $PACKAGES; do
	echo -e "\n\n==================== $PACKAGE ===================="
	apt-get install -y $PACKAGE
done

