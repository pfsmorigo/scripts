#!/bin/bash

SCREEN_CMD="screen -S pfsmorigo -X screen"

check() {
	PROC=$1
	[ -n "$2" ] && PROC=$2 || PROC=$1
	if [ -n "$(ps -x | grep $PROC | grep -v "grep\|$$")" ]; then
		notify-send "$1 already on!"
		exit 1
	fi
}

case $1 in
	v|vimwiki)
		check vimwiki "Wiki/index.wiki"
		$SCREEN_CMD -t vimwiki 7 vim ~/Dropbox/Wiki/index.wiki
		;;

	m|mutt)
		check mutt
		cd ~/Downloads
		$SCREEN_CMD -t mutt 8 mutt
		;;

	w|weechat)
		check weechat
		$SCREEN_CMD -t weechat 9 weechat-curses
		;;

	n|neb)
		$SCREEN_CMD -t neb 10 ssh -L 10000:127.0.0.1:10000 neb
		;;

	all)
		$0 vimwiki
		$0 mutt
		$0 weechat
		;;

	*)
		echo "error!"
		;;
esac

