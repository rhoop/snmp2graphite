#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
# Richard Hoop - wrhoop@gmail.com
#

import sys
import argparse
import logging
import glob
import json
import netsnmp
import socket
import time
import signal
import threading
from raven import Client

# ====( headers )==== #
import pprint
pprint = pprint.pprint

from daemon import Daemon

# ====( arguments )==== #


parser = argparse.ArgumentParser(description="Graphite Metric Daemon")

parser.add_argument(
    "-d",
    "--debug",
    action="store_true",
    default=False,
    help="Enable logging up to DEBUG logging")

parser.add_argument(
    "-l",
    "--log",
    action="store_true",
    default=True,
    help="Send all output to log")


# Daemon Commands
daemongroup = parser.add_mutually_exclusive_group(required=True)

daemongroup.add_argument(
    "--start",
    action="store_true",
    help="Start the Daemon")

daemongroup.add_argument(
    "--stop",
    action="store_true",
    help="Stop The daemon")

daemongroup.add_argument(
    "--reload",
    action="store_true",
    help="Reload the daemon")

daemongroup.add_argument(
    "--cli",
    action="store_true",
    help="Run in CLI mode")


# Set our local args
args = parser.parse_args()

if args.log and not args.cli:

    logging.basicConfig(
        format='%(levelno)s %(process)d %(asctime)s.%(msecs)d'
        ' (%(module)s::%(funcName)s[#%(lineno)d]) => %(message)s',
        datefmt='%H:%M:%S',
        filename='/var/log/snmp2graphite.log')
else:

    logging.basicConfig(
        format='%(levelno)s %(process)d %(asctime)s.%(msecs)d'
        ' (%(module)s::%(funcName)s[#%(lineno)d]) => %(message)s',
        datefmt='%H:%M:%S')

logger = logging.getLogger()
logger.setLevel(logging.INFO)

if args.debug:
    logger.setLevel(logging.DEBUG)


# ====( defaults )==== #
graphite = {
    "port": 2023,
    "server": ""
}


class Transformation(object):

    """docstring for Transformation"""

    deltas = {}

    @staticmethod
    def byteToMegabyte(cls, value):
        return (float(value) / 1024) / 1024

    @staticmethod
    def byteToGigabyte(cls, value):
        return float(cls.byteToMegabyte(cls, value) / 1024)

    @staticmethod
    def bitToGigabyte(cls, value):
        return (float(value) / 1024) / 1024 / 1024

    @staticmethod
    def bitToGigabit(cls, value):
        return float(float(value) / 8589934592) / 10

    @staticmethod
    def largestValue(cls, values):
        return max(values)

    @staticmethod
    def deltaByInterval(cls, value, key, interval):

        if key not in cls.deltas:
            cls.deltas[key] = float(value)
            return 0
        else:
            retval = float(value) - cls.deltas[key]
            cls.deltas[key] = float(value)
            return retval / interval


def send_to_graphite(value, sourcehost, metric, checkname):

    message = 'PRODUCTION.host.%s.metricD.%s.%s %s %d\n' % \
        (sourcehost.split('.')[0], checkname, metric, value, int(time.time()))
    logger.info(message[:-1])
    sock = socket.socket()
    sock.connect((graphite['server'], graphite['port']))
    sock.sendall(message)
    sock.close()


def load_config():
    CHECKS = {}
    for filename in glob.glob("checks/*.json"):
        with open(filename, "rb") as fh:
            logger.debug("Found file [%s]", filename)
            CHECKS[filename.split("/")[1][:-5]] = json.loads(
                " ".join(fh.readlines()))
    return CHECKS


def run_snmp(name, config):

    pprint(name)
    pprint(config)
    while True:

        for subcheck in config['checks']:
            for host in config['hosts']:

                result = netsnmp.snmpwalk(
                    subcheck['oid'],
                    Version=2,
                    DestHost=host['name'],
                    Community=config['community']
                )

                if len(result):
                    value = result[0]
                else:
                    try:
                        msg = "Value isn't there for type [%s]=[%s]" % (
                            type(value),
                            value)

                        logger.exception(msg)
                    except Exception, e:
                        raise e
                    continue
                if 'transform' in subcheck:
                    transformer = getattr(
                        Transformation, subcheck['transform'])
                    if subcheck['transform'] == 'deltaByInterval':
                        value = transformer(
                            Transformation,
                            value,
                            host['name'] + subcheck['name'],
                            float(config['interval']))
                    elif subcheck['transform'] == 'largestValue':
                        value = transformer(
                            Transformation,
                            result)
                    else:
                        value = transformer(Transformation, value)

                send_to_graphite(
                    value=value,
                    sourcehost=host['name'],
                    metric=subcheck['name'],
                    checkname=name)
        time.sleep(float(config['interval']))


def do_run():
    thread_alive = 0
    THREADS = []
    # Test the App with CLI
    CHECKS = load_config()
    for name, config in CHECKS.items():
        # print name, config
        t = threading.Thread(
            target=run_snmp, args=(name, config))
        THREADS.append(t)
        THREADS[thread_alive].daemon = True
        THREADS[thread_alive].start()
        thread_alive += 1

    while thread_alive:
        for thread in threading.enumerate():
            if not thread.is_alive():
                thread_alive -= 1

        time.sleep(1)


class DaemonRun(Daemon):

    def run(self):
        do_run()

    def reload(self):

        load_config()
        logger.warn("Reloading metricD!!")

    def exit(self, signal, frame):

        self.determined.stop()
        logger.warn("Stopping metricD Threads!!")
        sys.exit(0)


# ====( main )==== #
def main():
    if args.cli:
        do_run()
    # This is all daemon control
    else:
        daemon = DaemonRun('metricD')
        signal.signal(signal.SIGTERM, daemon.exit)
        signal.signal(signal.SIGHUP, daemon.reload)
    if args.start:
        daemon.start()
    elif args.stop:
        daemon.stop()
    elif args.reload:
        daemon.reload()

    sys.exit(0)


# ====( run )==== #
if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
