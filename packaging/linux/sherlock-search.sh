#!/bin/sh
# /usr/bin/sherlock-search from the RPM and .deb packages.
# Packaged as "sherlock-search" because Debian and Ubuntu already ship an
# unrelated "sherlock" package (a username-search tool) with /usr/bin/sherlock.
# The app lives in /usr/share/sherlock-search so its module cannot clash either.
export PYTHONPATH="/usr/share/sherlock-search${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m sherlock "$@"
