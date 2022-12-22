#!/bin/bash

# Not orthodox at all way to clean other search engines from google chrome!

SLEEP=3
COUNTER=$1

test -z "$COUNTER" && echo "Need a counter!" && exit 1

echo "Leave the mouse over the hamburger..."
sleep $SLEEP
eval $(xdotool getmouselocation --shell)
HAMBURGER_POS="$X $Y"
xdotool click 1

echo "Leave the mouse over the 'Remove from list'" sleep $SLEEP
sleep $SLEEP
eval $(xdotool getmouselocation --shell)
REMOVE_FROM_LIST_POS="$X $Y"
xdotool click 1

while true; do
	echo $COUNTER
	xdotool mousemove $HAMBURGER_POS
	xdotool click 1
	xdotool mousemove $REMOVE_FROM_LIST_POS
	xdotool click 1
	COUNTER=$((COUNTER - 1))
	test "$COUNTER" -eq 0 && exit
done
