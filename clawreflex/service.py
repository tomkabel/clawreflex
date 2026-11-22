#!/usr/bin/env python3
"""Deprecated CLI alias. The sole server and engine live in server.py."""
if __package__:
    from .server import main
else:
    from server import main

if __name__ == '__main__':
    raise SystemExit(main())
