#!/usr/bin/env python

"""
Amazon Fire TV server

RESTful interface for communication over a network via ADB
with Amazon Fire TV devices with ADB Debugging enabled.

From https://developer.amazon.com/public/solutions/devices/fire-tv/docs/connecting-adb-over-network:

Turn on ADB Debugging:
    1. From the main (Launcher) screen, select Settings.
    2. Select System > Developer Options.
    3. Select ADB Debugging.

Find device IP:
    1. From the main (Launcher) screen, select Settings.
    2. Select System > About > Network.
"""

import argparse
import re
from flask import Flask, jsonify, request, abort
from firetv import FireTV

app = Flask(__name__)
devices = {}
valid_device_id = re.compile('^[-\w]+$')
valid_app_id = re.compile('^[a-zA-Z][a-z\.A-Z]+$')


def is_valid_host(host):
    """ Check if host is valid.

    Performs two simple checks:
        - Has host and port separated by ':'.
        - Port is a positive digit.

    :param host: Host in <address>:<port> format.
    :returns: Valid or not.
    """
    parts = host.split(':')
    return not (len(parts) != 2 or not parts[1].isdigit())


def is_valid_device_id(device_id):
    """ Check if device identifier is valid.

    A valid device identifier contains only ascii word characters or dashes.

    :param device_id: Device identifier
    :returns: Valid or not.
    """
    return valid_device_id.match(device_id)

def is_valid_app_id(app_id):
    """ check if app identifier is valid.

    To restrict access a valid app is one with only a-z, A-Z, and '.'.
    It is possible to make this less restrictive using the regex above.

    :param app_id: Application identifier
    :returns: Valid or not
    """
    return valid_app_id.match(app_id)

def add(device_id, host):
    """ Add a device.

    Creates FireTV instance associated with device identifier.

    :param device_id: Device identifier.
    :param host: Host in <address>:<port> format.
    :returns: Added successfully or not.
    """
    valid = is_valid_device_id(device_id) and is_valid_host(host)
    if valid:
        devices[device_id] = FireTV(str(host))
    return valid


@app.route('/devices/add', methods=['POST'])
def add_device():
    """ Add a device via HTTP POST.

    POST JSON in the following format ::

        {
            "device_id": "<your_device_id>",
            "host": "<address>:<port>"
        }

    """
    req = request.get_json()
    success = False
    if 'device_id' in req and 'host' in req:
        success = add(req['device_id'], req['host'])
    return jsonify(success=success)


@app.route('/devices/list', methods=['GET'])
def list_devices():
    """ List devices via HTTP GET. """
    output = {}
    for device_id, device in devices.items():
        output[device_id] = {
            'host': device.host,
            'state': device.state
        }
    return jsonify(devices=output)


@app.route('/devices/state/<device_id>', methods=['GET'])
def device_state(device_id):
    """ Get device state via HTTP GET. """
    if device_id not in devices:
        return jsonify(success=False)
    return jsonify(state=devices[device_id].state)

@app.route('/devices/<device_id>/apps/running', methods=['GET'])
def running_apps(device_id):
    """ Get running apps via HTTP GET. """
    if not is_valid_device_id(device_id):
        abort(403)
    if device_id not in devices:
        abort(404)
    return jsonify(running_apps=devices[device_id].running_apps())

@app.route('/devices/<device_id>/apps/state/<app_id>', methods=['GET'])
def get_app_state(device_id, app_id):
    """ Get the state of the requested app """
    if not is_valid_app_id(app_id):
        abort(403)
    if not is_valid_device_id(device_id):
        abort(403)
    if device_id not in devices:
        abort(404)
    return jsonify(status=devices[device_id].app_state(app_id))

@app.route('/devices/action/<device_id>/<action_id>', methods=['GET'])
def device_action(device_id, action_id):
    """ Initiate device action via HTTP GET. """
    success = False
    if device_id in devices:
        input_cmd = getattr(devices[device_id], action_id, None)
        if callable(input_cmd):
            input_cmd()
            success = True
    return jsonify(success=success)


@app.route('/devices/connect/<device_id>', methods=['GET'])
def device_connect(device_id):
    """ Force a connection attempt via HTTP GET. """
    success = False
    if device_id in devices:
        devices[device_id].connect()
        success = True
    return jsonify(success=success)


def main():
    """ Set up the server. """
    parser = argparse.ArgumentParser(description='AFTV Server')
    parser.add_argument('-p', '--port', type=int, help='listen port', default=5556)
    parser.add_argument('-d', '--default', help='default Amazon Fire TV host', nargs='?')
    args = parser.parse_args()
    if args.default and not add('default', args.default):
        exit('invalid hostname')
    app.run(host='0.0.0.0', port=args.port)


if __name__ == '__main__':
    main()
