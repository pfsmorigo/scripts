#!/bin/bash

case $1 in
	vimwiki)
		screen -t vimwiki 7 vim ~/Dropbox/Wiki/index.wiki
		;;

	mutt)
		cd ~/Downloads
		screen -t mutt 8 mutt
		;;

	weechat)
		screen -t weechat 9 weechat-curses
		;;

	neb)
		screen -t neb 10 ssh -L 10000:127.0.0.1:10000 neb
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

