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
import yaml
import logging
from flask import Flask, jsonify, request, abort
from firetv import FireTV


app = Flask(__name__)
devices = {}
config_data = None
valid_device_id = re.compile('^[-\w]+$')
valid_app_id = re.compile('^[A-Za-z0-9\.]+$')


def is_valid_host(host):
    """ Check if host is valid.

    Performs two simple checks:
        - Has host and port separated by ':'.
        - Port is a positive digit.

    :param host: Host in <address>:<port> format.
    :returns: Valid or not.
    """
    parts = host.split(':')
    return len(parts) == 2 or parts[1].isdigit()


def is_valid_device_id(device_id):
    """ Check if device identifier is valid.

    A valid device identifier contains only ascii word characters or dashes.

    :param device_id: Device identifier
    :returns: Valid or not.
    """
    valid = valid_device_id.match(device_id)
    if not valid:
        logging.error("A valid device identifier contains "
                      "only ascii word characters or dashes. "
                      "Device '%s' not added.", device_id)
    return valid


def is_valid_app_id(app_id):
    """ check if app identifier is valid.

    To restrict access a valid app is one with only a-z, A-Z, and '.'.
    It is possible to make this less restrictive using the regex above.

    :param app_id: Application identifier
    :returns: Valid or not
    """
    return valid_app_id.match(app_id)

def add(device_id, host, adbkey=''):
    """ Add a device.

    Creates FireTV instance associated with device identifier.

    :param device_id: Device identifier.
    :param host: Host in <address>:<port> format.
    :param adbkey: The path to the "adbkey" file
    :returns: Added successfully or not.
    """
    valid = is_valid_device_id(device_id) and is_valid_host(host)
    if valid:
        devices[device_id] = FireTV(str(host), str(adbkey))
    return valid


@app.route('/devices/add', methods=['POST'])
def add_device():
    """ Add a device via HTTP POST.

    POST JSON in the following format ::

        {
            "device_id": "<your_device_id>",
            "host": "<address>:<port>",
            "adbkey": "<path to the adbkey file>"
        }

    """
    req = request.get_json()
    success = False
    if 'device_id' in req and 'host' in req:
        success = add(req['device_id'], req['host'], req.get('adbkey', ''))
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

@app.route('/devices/<device_id>/apps/current', methods=['GET'])
def current_app(device_id):
    """ Get currently running app. """
    if not is_valid_device_id(device_id):
        abort(403)
    if device_id not in devices:
        abort(404)

    current = devices[device_id].current_app
    if current is None:
        abort(404)

    return jsonify(current_app=current)

@app.route('/devices/<device_id>/apps/running', methods=['GET'])
def running_apps(device_id):
    """ Get running apps via HTTP GET. """
    if not is_valid_device_id(device_id):
        abort(403)
    if device_id not in devices:
        abort(404)
    return jsonify(running_apps=devices[device_id].running_apps)

@app.route('/devices/<device_id>/apps/state/<app_id>', methods=['GET'])
def get_app_state(device_id, app_id):
    """ Get the state of the requested app """
    if not is_valid_app_id(app_id):
        abort(403)
    if not is_valid_device_id(device_id):
        abort(403)
    if device_id not in devices:
        abort(404)
    app_state = devices[device_id].app_state(app_id)
    return jsonify(state=app_state, status=app_state)

@app.route('/devices/<device_id>/apps/<app_id>/state', methods=['GET'])
def get_app_state_alt(device_id, app_id):
    return get_app_state(device_id, app_id)

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

@app.route('/devices/<device_id>/apps/<app_id>/start', methods=['GET'])
def app_start(device_id, app_id):
    """ Starts an app with corresponding package name"""
    if not is_valid_app_id(app_id):
        abort(403)
    if not is_valid_device_id(device_id):
        abort(403)
    if device_id not in devices:
        abort(404)

    success = devices[device_id].launch_app(app_id)
    return jsonify(success=success)

@app.route('/devices/<device_id>/apps/<app_id>/stop', methods=['GET'])
def app_stop(device_id, app_id):
    """ stops an app with corresponding package name"""
    if not is_valid_app_id(app_id):
        abort(403)
    if not is_valid_device_id(device_id):
        abort(403)
    if device_id not in devices:
        abort(404)

    success = devices[device_id].stop_app(app_id)
    return jsonify(success=success)

@app.route('/devices/connect/<device_id>', methods=['GET'])
def device_connect(device_id):
    """ Force a connection attempt via HTTP GET. """
    success = False
    if device_id in devices:
        devices[device_id].connect()
        success = True
    return jsonify(success=success)


def _parse_config(config_file_path):
    """ Parse Config File from yaml file. """
    config_file = open(config_file_path, 'r')
    config = yaml.load(config_file)
    config_file.close()
    return config

def _add_devices_from_config(args):
    """ Add devices from config. """
    config = _parse_config(args.config)
    for device in config['devices']:
        if args.default:
            if device == "default":
                raise ValueError('devicename "default" in config is not allowed if default param is set')
            if config['devices'][device]['host'] == args.default:
                raise ValueError('host set in default param must not be defined in config')
        add(device, config['devices'][device]['host'], config['devices'][device].get('adbkey', ''))

def main():
    """ Set up the server. """
    parser = argparse.ArgumentParser(description='AFTV Server')
    parser.add_argument('-p', '--port', type=int, help='listen port', default=5556)
    parser.add_argument('-d', '--default', help='default Amazon Fire TV host', nargs='?')
    parser.add_argument('-c', '--config', type=str, help='Path to config file')
    args = parser.parse_args()

    if args.config:
        _add_devices_from_config(args)

    if args.default and not add('default', args.default):
        exit('invalid hostname')
    app.run(host='0.0.0.0', port=args.port)


if __name__ == '__main__':
    main()
