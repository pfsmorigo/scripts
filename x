#!/bin/bash

SCREEN_CMD="screen -S pfsmorigo -X screen"

case $1 in
	vimwiki)
		$SCREEN_CMD -t vimwiki 7 vim ~/Dropbox/Wiki/index.wiki
		;;

	mutt)
		cd ~/Downloads
		$SCREEN_CMD -t mutt 8 mutt
		;;

	weechat)
		$SCREEN_CMD -t weechat 9 weechat-curses
		;;

	neb)
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

