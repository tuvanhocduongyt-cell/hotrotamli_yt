"""Threaded workers keep the standard-library SSL stack unpatched."""
import os

bind = '0.0.0.0:' + os.environ.get('PORT', '5000')
worker_class = 'gthread'
workers = 2
threads = 4
timeout = 240
preload_app = False
