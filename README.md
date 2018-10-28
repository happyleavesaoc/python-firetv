# python-firetv

`firetv` is a Python 2 and 3 package that provides state information and some control of an Amazon Fire TV device over a network. This is achieved via ADB, so therefore requires [ADB Debugging](https://developer.amazon.com/public/solutions/devices/fire-tv/docs/connecting-adb-over-network) to be turned on. It includes `firetv-server`, an HTTP server to facilitate RESTful access to configured devices.

## Installation

Install the following ADB dependencies via your package manager:

with `apt-get`: `swig libssl-dev python-dev libusb-1.0-0`

with `yum`: `swig openssl-devel python-devel libusbx-devel`

Install the package using the command:

`pip install firetv`

If you want the HTTP server component installed as a script, use:

`pip install firetv[firetv-server]`

Consider installing `adb` directly from the git repository. It contains bugfixes not in the pip-packaged version:

`pip install git+git://github.com/google/python-adb.git@master`

## Server

To run the server when installed as a script:

`firetv-server`

If you want to set a default Amazon Fire TV device:

`firetv-server -d X.X.X.X:5555`

If you want to run on a port other than `5556`:

`firetv-server -p XXXX`

### systemd

Copy the `firetv.service` file to `/etc/systemd/system/`. Modify the `ExecStart` path and arguments as necessary.

```bash
systemctl enable firetv.service  # Enable on boot
systemctl start firetv.service   # Start server
systemctl stop firetv.service    # Stop server
```

### Persistence
To store multiple Amazon Fire TV devices persistent, you can load a yaml config file:
`firetv-server -c some/config/file.yaml`

The config file has to be in the following format:
```yaml
devices:
  sleepingroom:
    host: 192.168.0.13:5555
  livingroom:
    host: 192.168.0.16:5555
```

*Note: If you use -d and -c option together you must not name one of the devices in config file `default` or give one of the devices the same host as in -d option.*

### Routes

All routes return JSON.

- `GET /devices/list` (list all registered devices and state)
- `GET /devices/connect/<device_id>` (force connection attempt)
- `GET /devices/state/<device_id>` (return state)
- `GET /devices/action/<device_id>/<action_id>` (request action)
- `GET /devices/<device_id>/apps/running` (return running user apps)
- `GET /devices/<device_id>/apps/<app_id>/start` (start an app)
- `GET /devices/<device_id>/apps/<app_id>/stop` (stop an app)
- `GET /devices/<device_id>/apps/<app_id>/state` (check app state)
- `GET /devices/<device_id>/apps/state/<app_id>` (check app state, deprecated format)
- `POST /devices/add` (see below)

#### Add A Device

If you use the `-d` option, the specified device is added automatically with the device identifier `default`. If you want to add further devices, or don't want to use the command line option for the initial device, use the `POST /devices/add` route. The device identifier can be any string meaningful to you, matching [`[-\w]`](https://docs.python.org/2/library/re.html) (any alphanumeric character, plus `-`).

POST JSON in the following format with the HTTP header `Content-Type: application/json`:
```json
{
  "device_id": "<your_device_id>",
  "host": "<address>:<port>"
}
```

## Features

`firetv` can detect device state and issue a number of actions. It can also get the running state of user apps.

### Detected States

- `off` (TV screen is dark)
- `standby` (standard UI is active - not apps)
- `idle` (screen saver is active)
- `play` (video is playing)
- `pause` (video is paused)
- `disconnected` (can't communicate with device)

### Actions

- `turn_on` (turn on the device, showing the UI on screen)
- `turn_off` (turn off the device, screen goes dark)
- `home` (emulate Home button)
- `media_play_pause` (emulate Play/Pause button)
- `media_play` (simulate Play button)
- `media_pause` (simulate Pause button)
- `media_next` (emulate Fast-Forward button)
- `media_previous` (emulate Rewind button)
- `volume_up` (raise volume)
- `volume_down` (lower volume)

### Apps

- `GET /devices/<device_id>/apps/running`
- `/devices/<device_id>/apps/state/<app_id>`
- `/devices/<device_id>/apps/<app_id>/state`

app_id can be anything from a single word, e.g. 'netflix' or the full package name, e.g. com.netflix.ninja

You can start or stop an app with the following commands:

- `GET /devices/<device_id>/apps/<app_id>/start` 
- `GET /devices/<device_id>/apps/<app_id>/stop` 

app_id must be a package name, e.g. org.xbmc.kodi or com.netflix.ninja

## Contribution

This package does not fully exploit the potential of ADB access to Amazon Fire TV devices, and lacks some robustness. Contributions are welcome.
