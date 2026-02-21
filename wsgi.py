"""WSGI entrypoint for production servers (gunicorn/uwsgi/etc.)."""

from flask_app import app

application = app
