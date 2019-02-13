#!/usr/bin/env python

"""
Communicate with an Amazon Fire TV device via ADB over a network.

ADB Debugging must be enabled.
"""

import logging
import re
from socket import error as socket_error
import sys
import threading

from adb import adb_commands
from adb.sign_pythonrsa import PythonRSASigner
from adb.adb_protocol import InvalidChecksumError
from adb_messenger.client import Client as AdbClient


Signer = PythonRSASigner.FromRSAKeyPath

if sys.version_info[0] > 2 and sys.version_info[1] > 1:
    LOCK_KWARGS = {'timeout': 3}
else:
    LOCK_KWARGS = {}

# Matches window windows output for app & activity name gathering
WINDOW_REGEX = re.compile(r"Window\{(?P<id>.+?) (?P<user>.+) (?P<package>.+?)(?:\/(?P<activity>.+?))?\}$", re.MULTILINE)

# ADB shell commands for getting the `screen_on`, `awake`, `wake_lock`,
# `wake_lock_size`, `current_app`, and `running_apps` properties
SCREEN_ON_CMD = "dumpsys power | grep 'Display Power' | grep -q 'state=ON'"
AWAKE_CMD = "dumpsys power | grep mWakefulness | grep -q Awake"
WAKE_LOCK_CMD = "dumpsys power | grep Locks | grep -q 'size=0'"
WAKE_LOCK_SIZE_CMD = "dumpsys power | grep Locks | grep 'size='"
CURRENT_APP_CMD = "dumpsys window windows | grep mCurrentFocus"
RUNNING_APPS_CMD = "ps | grep u0_a"

# echo '1' if the previous shell command was successful
SUCCESS1 = r" && echo -e '1\c' "

# echo '1' if the previous shell command was successful, echo '0' if it was not
SUCCESS1_FAILURE0 = r" && echo -e '1\c' || echo -e '0\c' "

# ADB key event codes.
HOME = 3
VOLUME_UP = 24
VOLUME_DOWN = 25
POWER = 26
SLEEP = 223
PLAY_PAUSE = 85
NEXT = 87
PREVIOUS = 88
PLAY = 126
PAUSE = 127
UP = 19
DOWN = 20
LEFT = 21
RIGHT = 22
ENTER = 66
SPACE = 62
BACK = 4
MENU = 1
KEY_0 = 7
KEY_1 = 8
KEY_2 = 9
KEY_3 = 10
KEY_4 = 11
KEY_5 = 12
KEY_6 = 13
KEY_7 = 14
KEY_8 = 15
KEY_9 = 16
KEY_A = 29
KEY_B = 30
KEY_C = 31
KEY_D = 32
KEY_E = 33
KEY_F = 34
KEY_G = 35
KEY_H = 36
KEY_I = 37
KEY_J = 38
KEY_K = 39
KEY_L = 40
KEY_M = 41
KEY_N = 42
KEY_O = 43
KEY_P = 44
KEY_Q = 45
KEY_R = 46
KEY_S = 47
KEY_T = 48
KEY_U = 49
KEY_V = 50
KEY_W = 51
KEY_X = 52
KEY_Y = 53
KEY_Z = 54

# Select key codes for use by a Home Assistant service.
KEYS = {'POWER': POWER,
        'SLEEP': SLEEP,
        'HOME': HOME,
        'ENTER': ENTER,
        'BACK': BACK,
        'MENU': MENU,
        'UP': UP,
        'DOWN': DOWN,
        'LEFT': LEFT,
        'RIGHT': RIGHT}

# Fire TV states.
STATE_ON = 'on'
STATE_IDLE = 'idle'
STATE_OFF = 'off'
STATE_PLAYING = 'playing'
STATE_PAUSED = 'paused'
STATE_STANDBY = 'standby'
STATE_UNKNOWN = 'unknown'

PACKAGE_LAUNCHER = "com.amazon.tv.launcher"
PACKAGE_SETTINGS = "com.amazon.tv.settings"
INTENT_LAUNCH = "android.intent.category.LAUNCHER"
INTENT_HOME = "android.intent.category.HOME"


class FireTV:
    """Represents an Amazon Fire TV device."""

    def __init__(self, host, adbkey='', adb_server_ip='', adb_server_port=5037):
        """Initialize FireTV object.

        :param host: Host in format <address>:port.
        :param adbkey: The path to the "adbkey" file
        :param adb_server_ip: the IP address for the ADB server
        :param adb_server_port: the port for the ADB server
        """
        self.host = host
        self.adbkey = adbkey
        self.adb_server_ip = adb_server_ip
        self.adb_server_port = adb_server_port

        # keep track of whether the ADB connection is intact
        self._available = False

        # use a lock to make sure that ADB commands don't overlap
        self._adb_lock = threading.Lock()

        # the attributes used for sending ADB commands; filled in in `self.connect()`
        self._adb = None  # python-adb
        self._adb_client = None  # pure-python-adb
        self._adb_device = None  # pure-python-adb

        # the methods used for sending ADB commands
        if not self.adb_server_ip:
            # python-adb
            self.adb_shell = self._adb_shell_python_adb
            self.adb_streaming_shell = self._adb_streaming_shell_python_adb
        else:
            # pure-python-adb
            self.adb_shell = self._adb_shell_pure_python_adb
            self.adb_streaming_shell = self._adb_streaming_shell_pure_python_adb

        # establish the ADB connection
        self.connect()

    # ======================================================================= #
    #                                                                         #
    #                               ADB methods                               #
    #                                                                         #
    # ======================================================================= #
    def _adb_shell_python_adb(self, cmd):
        if not self.available:
            return None

        if self._adb_lock.acquire(**LOCK_KWARGS):
            try:
                return self._adb.Shell(cmd)
            finally:
                self._adb_lock.release()

    def _adb_shell_pure_python_adb(self, cmd):
        if not self._available:
            return None

        if self._adb_lock.acquire(**LOCK_KWARGS):
            try:
                return self._adb_device.shell(cmd)
            finally:
                self._adb_lock.release()

    def _adb_streaming_shell_python_adb(self, cmd):
        if not self.available:
            return []

        if self._adb_lock.acquire(**LOCK_KWARGS):
            try:
                return self._adb.StreamingShell(cmd)
            finally:
                self._adb_lock.release()

    def _adb_streaming_shell_pure_python_adb(self, cmd):
        if not self._available:
            return None

        # this is not yet implemented
        if self._adb_lock.acquire(**LOCK_KWARGS):
            try:
                return []
            finally:
                self._adb_lock.release()

    def _dump(self, service, grep=None):
        """Perform a service dump.

        :param service: Service to dump.
        :param grep: Grep for this string.
        :returns: Dump, optionally grepped.
        """
        if grep:
            return self.adb_shell('dumpsys {0} | grep "{1}"'.format(service, grep))
        return self.adb_shell('dumpsys {0}'.format(service))

    def _dump_has(self, service, grep, search):
        """Check if a dump has particular content.

        :param service: Service to dump.
        :param grep: Grep for this string.
        :param search: Check for this substring.
        :returns: Found or not.
        """
        dump_grep = self._dump(service, grep=grep)

        if not dump_grep:
            return False

        return dump_grep.strip().find(search) > -1

    def _key(self, key):
        """Send a key event to device.

        :param key: Key constant.
        """
        self.adb_shell('input keyevent {0}'.format(key))

    def _ps(self, search=''):
        """Perform a ps command with optional filtering.

        :param search: Check for this substring.
        :returns: List of matching fields
        """
        if not self.available:
            return
        result = []
        ps = self.adb_streaming_shell('ps')
        try:
            for bad_line in ps:
                # The splitting of the StreamingShell doesn't always work
                # this is to ensure that we get only one line
                for line in bad_line.splitlines():
                    if search in line:
                        result.append(line.strip().rsplit(' ', 1)[-1])
            return result
        except InvalidChecksumError as e:
            print(e)
            self.connect()
            raise IOError

    def _send_intent(self, pkg, intent, count=1):

        cmd = 'monkey -p {} -c {} {}; echo $?'.format(pkg, intent, count)
        logging.debug("Sending an intent %s to %s (count: %s)", intent, pkg, count)

        # adb shell outputs in weird format, so we cut it into lines,
        # separate the retcode and return info to the user
        res = self.adb_shell(cmd)
        if res is None:
            return {}

        res = res.strip().split("\r\n")
        retcode = res[-1]
        output = "\n".join(res[:-1])

        return {"retcode": retcode, "output": output}

    def connect(self):
        """Connect to an Amazon Fire TV device.

        Will attempt to establish ADB connection to the given host.
        Failure sets state to UNKNOWN and disables sending actions.

        :returns: True if successful, False otherwise
        """
        self._adb_lock.acquire(**LOCK_KWARGS)
        try:
            if not self.adb_server_ip:
                # python-adb
                try:
                    if self.adbkey:
                        signer = Signer(self.adbkey)

                        # Connect to the device
                        self._adb = adb_commands.AdbCommands().ConnectDevice(serial=self.host, rsa_keys=[signer], default_timeout_ms=9000)
                    else:
                        self._adb = adb_commands.AdbCommands().ConnectDevice(serial=self.host, default_timeout_ms=9000)

                    # ADB connection successfully established
                    self._available = True

                except socket_error as serr:
                    self._adb = None
                    if self._available:
                        self._available = False
                        if serr.strerror is None:
                            serr.strerror = "Timed out trying to connect to ADB device."
                        logging.warning("Couldn't connect to host: %s, error: %s", self.host, serr.strerror)

                finally:
                    return self._available

            else:
                # pure-python-adb
                try:
                    self._adb_client = AdbClient(host=self.adb_server_ip, port=self.adb_server_port)
                    self._adb_device = self._adb_client.device(self.host)
                    self._available = bool(self._adb_device)

                except:
                    self._available = False

                finally:
                    return self._available

        finally:
            self._adb_lock.release()

    # ======================================================================= #
    #                                                                         #
    #                          Home Assistant Update                          #
    #                                                                         #
    # ======================================================================= #
    def update(self, get_running_apps=True):
        """Get the state of the device, the current app, and the running apps.

        :param get_running_apps: whether or not to get the ``running_apps`` property
        :return state: the state of the device
        :return current_app: the current app
        :return running_apps: the running apps
        """
        # The `screen_on`, `awake`, `wake_lock_size`, `current_app`, and `running_apps` properties.
        screen_on, awake, wake_lock_size, _current_app, running_apps = self.get_properties(get_running_apps=get_running_apps, lazy=True)

        # Check if device is off.
        if not screen_on:
            state = STATE_OFF
            current_app = None
            running_apps = None

        # Check if screen saver is on.
        elif not awake:
            state = STATE_IDLE
            current_app = None
            running_apps = None

        else:
            # Get the current app.
            if isinstance(_current_app, dict) and 'package' in _current_app:
                current_app = _current_app['package']
            else:
                current_app = None

            # Get the running apps.
            if running_apps is None and current_app:
                running_apps = [current_app]

            # Get the state.
            # TODO: determine the state differently based on the `current_app`.
            if current_app in [PACKAGE_LAUNCHER, PACKAGE_SETTINGS]:
                state = STATE_STANDBY

            # Check if `wake_lock_size` is 1 (device is playing).
            elif wake_lock_size == 1:
                state = STATE_PLAYING

            # Otherwise, device is paused.
            else:
                state = STATE_PAUSED

        return state, current_app, running_apps

    # ======================================================================= #
    #                                                                         #
    #                              App methods                                #
    #                                                                         #
    # ======================================================================= #
    def app_state(self, app):
        """Informs if application is running."""
        if not self.available or not self.screen_on:
            return STATE_OFF
        if self.current_app["package"] == app:
            return STATE_ON
        return STATE_OFF

    def launch_app(self, app):
        """Launch an app."""
        return self._send_intent(app, INTENT_LAUNCH)

    def stop_app(self, app):
        """Stop an app (really, it just returns to the home screen)."""
        return self._send_intent(PACKAGE_LAUNCHER, INTENT_HOME)

    # ======================================================================= #
    #                                                                         #
    #                               properties                                #
    #                                                                         #
    # ======================================================================= #
    @property
    def state(self):
        """Compute and return the device state.

        :returns: Device state.
        """
        # Check if device is disconnected.
        if not self.available:
            return STATE_UNKNOWN
        # Check if device is off.
        if not self.screen_on:
            return STATE_OFF
        # Check if screen saver is on.
        if not self.awake:
            return STATE_IDLE
        # Check if the launcher is active.
        if self.launcher or self.settings:
            return STATE_STANDBY
        # Check for a wake lock (device is playing).
        if self.wake_lock:
            return STATE_PLAYING
        # Otherwise, device is paused.
        return STATE_PAUSED

    @property
    def available(self):
        """Check whether the ADB connection is intact."""
        if not self.adb_server_ip:
            # python-adb
            return bool(self._adb)

        # pure-python-adb
        try:
            # make sure the server is available
            adb_devices = self._adb_client.devices()

            # make sure the device is available
            try:
                # case 1: the device is currently available
                if any([self.host in dev.get_serial_no() for dev in adb_devices]):
                    if not self._available:
                        self._available = True
                    return True

                # case 2: the device is not currently available
                if self._available:
                    logging.error('ADB server is not connected to the device.')
                    self._available = False
                return False

            except RuntimeError:
                if self._available:
                    logging.error('ADB device is unavailable; encountered an error when searching for device.')
                    self._available = False
                return False

        except RuntimeError:
            if self._available:
                logging.error('ADB server is unavailable.')
                self._available = False
            return False

    @property
    def running_apps(self):
        """Return a list of running user applications."""
        ps = self.adb_shell(RUNNING_APPS_CMD)
        if ps:
            return [line.strip().rsplit(' ', 1)[-1] for line in ps.splitlines() if line.strip()]
        return []

    @property
    def current_app(self):
        """Return the current app."""
        current_focus = self.adb_shell(CURRENT_APP_CMD)
        if current_focus is None:
            return None

        current_focus = current_focus.replace("\r", "")
        matches = WINDOW_REGEX.search(current_focus)

        # case 1: current app was successfully found
        if matches:
            (pkg, activity) = matches.group("package", "activity")
            return {"package": pkg, "activity": activity}

        # case 2: current app could not be found
        logging.warning("Couldn't get current app, reply was %s", current_focus)
        return None

    @property
    def screen_on(self):
        """Check if the screen is on."""
        return self.adb_shell(SCREEN_ON_CMD + SUCCESS1_FAILURE0) == '1'

    @property
    def awake(self):
        """Check if the device is awake (screensaver is not running)."""
        return self.adb_shell(AWAKE_CMD + SUCCESS1_FAILURE0) == '1'

    @property
    def wake_lock(self):
        """Check for wake locks (device is playing)."""
        return self.adb_shell(WAKE_LOCK_CMD + SUCCESS1_FAILURE0) == '1'

    @property
    def wake_lock_size(self):
        """Get the size of the current wake lock."""
        output = self.adb_shell(WAKE_LOCK_SIZE_CMD)
        if not output:
            return None
        return int(output.split("=")[1].strip())

    @property
    def launcher(self):
        """Check if the active application is the Amazon TV launcher."""
        return self.current_app["package"] == PACKAGE_LAUNCHER

    @property
    def settings(self):
        """Check if the active application is the Amazon menu."""
        return self.current_app["package"] == PACKAGE_SETTINGS

    def get_properties(self, get_running_apps=True, lazy=False):
        """Get the ``screen_on``, ``awake``, ``wake_lock_size``, ``current_app``, and ``running_apps`` properties."""
        if get_running_apps:
            output = self.adb_shell(SCREEN_ON_CMD + (SUCCESS1 if lazy else SUCCESS1_FAILURE0) + " && " +
                                    AWAKE_CMD + (SUCCESS1 if lazy else SUCCESS1_FAILURE0) + " && " +
                                    WAKE_LOCK_SIZE_CMD + " &&" +
                                    CURRENT_APP_CMD + " && " +
                                    RUNNING_APPS_CMD)
        else:
            output = self.adb_shell(SCREEN_ON_CMD + (SUCCESS1 if lazy else SUCCESS1_FAILURE0) + " && " +
                                    AWAKE_CMD + (SUCCESS1 if lazy else SUCCESS1_FAILURE0) + " && " +
                                    WAKE_LOCK_SIZE_CMD + " &&" +
                                    CURRENT_APP_CMD)

        # ADB command was unsuccessful
        if output is None:
            return None, None, None, None, None

        # `screen_on` property
        if not output:
            return False, False, -1, None, None
        screen_on = output[0] == '1'

        # `awake` property
        if len(output) < 2:
            return screen_on, False, -1, None, None
        awake = output[1] == '1'

        lines = output.strip().splitlines()

        # `wake_lock_size` property
        if len(lines[0]) < 3:
            return screen_on, awake, -1, None, None
        wake_lock_size = int(lines[0].split("=")[1].strip())

        # `current_app` property
        if len(lines) < 2:
            return screen_on, awake, wake_lock_size, None, None

        matches = WINDOW_REGEX.search(lines[1])
        if matches:
            # case 1: current app was successfully found
            (pkg, activity) = matches.group("package", "activity")
            current_app = {"package": pkg, "activity": activity}
        else:
            # case 2: current app could not be found
            logging.warning("Couldn't get current app, reply was %s", lines[1])
            current_app = None

        # `running_apps` property
        if not get_running_apps or len(lines) < 3:
            return screen_on, awake, wake_lock_size, current_app, None

        running_apps = [line.strip().rsplit(' ', 1)[-1] for line in lines[2:] if line.strip()]

        return screen_on, awake, wake_lock_size, current_app, running_apps

    # ======================================================================= #
    #                                                                         #
    #                           turn on/off methods                           #
    #                                                                         #
    # ======================================================================= #
    def turn_on(self):
        """Send power action if device is off."""
        self.adb_shell(SCREEN_ON_CMD + " || (input keyevent {0} && input keyevent {1})".format(POWER, HOME))

    def turn_off(self):
        """Send power action if device is not off."""
        self.adb_shell(SCREEN_ON_CMD + " && input keyevent {0}".format(SLEEP))

    # ======================================================================= #
    #                                                                         #
    #                      "key" methods: basic commands                      #
    #                                                                         #
    # ======================================================================= #
    def power(self):
        """Send power action."""
        self._key(POWER)

    def sleep(self):
        """Send sleep action."""
        self._key(SLEEP)

    def home(self):
        """Send home action."""
        self._key(HOME)

    def up(self):
        """Send up action."""
        self._key(UP)

    def down(self):
        """Send down action."""
        self._key(DOWN)

    def left(self):
        """Send left action."""
        self._key(LEFT)

    def right(self):
        """Send right action."""
        self._key(RIGHT)

    def enter(self):
        """Send enter action."""
        self._key(ENTER)

    def back(self):
        """Send back action."""
        self._key(BACK)

    def space(self):
        """Send space keypress."""
        self._key(SPACE)

    def menu(self):
        """Send menu action."""
        self._key(MENU)

    def volume_up(self):
        """Send volume up action."""
        self._key(VOLUME_UP)

    def volume_down(self):
        """Send volume down action."""
        self._key(VOLUME_DOWN)

    # ======================================================================= #
    #                                                                         #
    #                      "key" methods: media commands                      #
    #                                                                         #
    # ======================================================================= #
    def media_play_pause(self):
        """Send media play/pause action."""
        self._key(PLAY_PAUSE)

    def media_play(self):
        """Send media play action."""
        self._key(PLAY)

    def media_pause(self):
        """Send media pause action."""
        self._key(PAUSE)

    def media_next(self):
        """Send media next action (results in fast-forward)."""
        self._key(NEXT)

    def media_previous(self):
        """Send media previous action (results in rewind)."""
        self._key(PREVIOUS)

    # ======================================================================= #
    #                                                                         #
    #                       "key" methods: key commands                       #
    #                                                                         #
    # ======================================================================= #
    def key_0(self):
        """Send 0 keypress."""
        self._key(KEY_0)

    def key_1(self):
        """Send 1 keypress."""
        self._key(KEY_1)

    def key_2(self):
        """Send 2 keypress."""
        self._key(KEY_2)

    def key_3(self):
        """Send 3 keypress."""
        self._key(KEY_3)

    def key_4(self):
        """Send 4 keypress."""
        self._key(KEY_4)

    def key_5(self):
        """Send 5 keypress."""
        self._key(KEY_5)

    def key_6(self):
        """Send 6 keypress."""
        self._key(KEY_6)

    def key_7(self):
        """Send 7 keypress."""
        self._key(KEY_7)

    def key_8(self):
        """Send 8 keypress."""
        self._key(KEY_8)

    def key_9(self):
        """Send 9 keypress."""
        self._key(KEY_9)

    def key_a(self):
        """Send a keypress."""
        self._key(KEY_A)

    def key_b(self):
        """Send b keypress."""
        self._key(KEY_B)

    def key_c(self):
        """Send c keypress."""
        self._key(KEY_C)

    def key_d(self):
        """Send d keypress."""
        self._key(KEY_D)

    def key_e(self):
        """Send e keypress."""
        self._key(KEY_E)

    def key_f(self):
        """Send f keypress."""
        self._key(KEY_F)

    def key_g(self):
        """Send g keypress."""
        self._key(KEY_G)

    def key_h(self):
        """Send h keypress."""
        self._key(KEY_H)

    def key_i(self):
        """Send i keypress."""
        self._key(KEY_I)

    def key_j(self):
        """Send j keypress."""
        self._key(KEY_J)

    def key_k(self):
        """Send k keypress."""
        self._key(KEY_K)

    def key_l(self):
        """Send l keypress."""
        self._key(KEY_L)

    def key_m(self):
        """Send m keypress."""
        self._key(KEY_M)

    def key_n(self):
        """Send n keypress."""
        self._key(KEY_N)

    def key_o(self):
        """Send o keypress."""
        self._key(KEY_O)

    def key_p(self):
        """Send p keypress."""
        self._key(KEY_P)

    def key_q(self):
        """Send q keypress."""
        self._key(KEY_Q)

    def key_r(self):
        """Send r keypress."""
        self._key(KEY_R)

    def key_s(self):
        """Send s keypress."""
        self._key(KEY_S)

    def key_t(self):
        """Send t keypress."""
        self._key(KEY_T)

    def key_u(self):
        """Send u keypress."""
        self._key(KEY_U)

    def key_v(self):
        """Send v keypress."""
        self._key(KEY_V)

    def key_w(self):
        """Send w keypress."""
        self._key(KEY_W)

    def key_x(self):
        """Send x keypress."""
        self._key(KEY_X)

    def key_y(self):
        """Send y keypress."""
        self._key(KEY_Y)

    def key_z(self):
        """Send z keypress."""
        self._key(KEY_Z)
