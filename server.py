#!/usr/bin/env python

import asyncore
import asynchat
import json
import math
import os
import socket
import stat
import sys
import time

import threadpool
import websocket
import pyaxel as pyalib
import pyaxel2 as pyalib2


__version__ = '1.2.0'
__author__ = 'wormboy.d@gmail.com'

[BAD_REQUEST] = range(100, 101)

[START, STOP, ABORT, QUIT] = range(4)


class StateMachineError(Exception):
    pass


class TransitionError(StateMachineError):
    def __init__(self, cur, inp, msg):
        self.cur = cur
        self.inp = inp
        self.msg = msg


class chanstate_c:
    def __init__(self):
        self.states = {}
        self.current = None

    def start(self, state):
        self.current = state

    def add(self, state, inp, next, action=None):
        if state not in self.states:
            self.states[state] = {}
        self.states[state][inp] = (next, action)

    def execute(self, inp, args=()):
        if self.current not in self.states:
            raise StateMachineError('invalid state: %s' % self.current)
        state = self.states[self.current]
        if inp in state:
            next, action = state[inp]
            if action is not None:
                action(args)
            self.current = next
        else:
            if None in state:
                next, action = state[None]
                if action is not None:
                    action(args)
                self.current = next
            else:
                raise TransitionError(self.current, inp, 'input not recognized')


class channel_c:
    def __init__(self, sock, server):
        self.axel = None
        self.server = server
        self.websocket = websocket.AsyncChat(sock, self)
        self.state = chanstate_c()
        self.state.add('listening', START, 'established', self.start)
        self.state.add('listening', ABORT, 'listening', self.abort)
        self.state.add('listening', QUIT, 'listening', self.quit)
        self.state.add('established', STOP, 'listening', self.stop)
        self.state.add('established', ABORT, 'listening', self.abort)
        self.state.add('established', QUIT, 'listening', self.quit)
        self.state.start('listening')

    def channel_message(self, msg):
        try:
            msg = inflate_message(msg)
            self.state.execute(msg['cmd'], msg.get('req', {}))
        except TransitionError:
            self.websocket.send_message(deflate_message({'status':BAD_REQUEST}))
        except (StateMachineError, Exception):
            self.close()

    def channel_closed(self):
        self.close()

    def start(self, request):
        conf = pyalib.conf_t()
        pyalib.conf_init(conf)
        prefs = request.get('conf', {})
        for p in prefs:
            setattr(conf, p, prefs[p])
        self.server.add_client(self)
        self.axel = pyalib2.pyaxel_new(conf, request.get('url'), request.get('metadata'))
        self.websocket.send_message(deflate_message(pyalib2.pyaxel_status(self.axel)))

    def stop(self, request):
        self.server.add_client(self)
        pyalib2.pyaxel_stop(self.axel)
        self.websocket.send_message(deflate_message(pyalib2.pyaxel_status(self.axel)))

    def abort(self, request):
        self.server.add_client(self)
        pyalib2.pyaxel_abort(self.axel)
        self.websocket.send_message(deflate_message(pyalib2.pyaxel_status(self.axel)))

    def quit(self, request):
        self.close()

    def update(self):
        pyalib2.pyaxel_do(self.axel)
        status = pyalib2.pyaxel_status(self.axel)
        if status:
            self.websocket.send_message(deflate_message(status))
        if not pyalib2.pyaxel_processes(self.axel):
            self.close(0)
            self.state.start('listening')

    def close(self, status=1000, reason=''):
        if self.axel:
            pyalib2.pyaxel_close(self.axel)
        if status > 999:
            self.websocket.disconnect(status, reason)
        self.server.remove_client(self)


class server_c(asyncore.dispatcher):
    def __init__(self):
        asyncore.dispatcher.__init__(self)
        self.clients = []

    def writable(self):
        return False

    def handle_accept(self):
        try:
            conn, addr = self.accept()
            if addr:
                self.log_info('incoming connection from %s' % repr(addr))
                channel_c(conn, self)
        except socket.error, err:
            self.log_info('error: %s' % err, 'error')

    def start_service(self, endpoint, backlog=5):
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind(endpoint)
        self.listen(backlog)
        self.log_info('websocket server waiting on %s' % repr(endpoint))
        while asyncore.socket_map:
            asyncore.loop(use_poll=True, timeout=1, count=1)
            for c in self.clients:
                c.update()

    def stop_service(self):
        self.log_info('stopping service')
        self.close()
        for c in self.clients:
            c.close(status=1001, reason='server shutdown')

    def add_client(self, client):
        if client not in self.clients:
            self.clients.append(client)

    def remove_client(self, client):
        if client in self.clients:
            self.clients.remove(client)


def deflate_message(msg):
    return json.dumps(msg, separators=(',',':'))

def inflate_message(msg):
    return json.loads(msg)

def run(opts={}):
    sys.stdout.write('PyaxelWS-%s\n' % __version__)
    sys.stdout.write('pyaxel-%s pyaxel2-%s websocket-%s\n' %
        (pyalib.__version__, pyalib2.__version__, websocket.__version__))

    major, minor, micro, release, serial = sys.version_info
    if (major, minor, micro) < (2, 6, 0):
        sys.stderr.write('aborting: unsupported Python version: %s.%s.%s\n' % \
            (major, minor, micro))
        return 1

    if opts.get('verbose'):
        pyalib.dbg_lvl = 1

    server = server_c()
    try:
        server.start_service((opts.get('host', '127.0.0.1'), opts.get('port', 8002)))
    except KeyboardInterrupt:
        print
    except Exception, e:
        import debug
        debug.backtrace()

    server.stop_service()
    sys.stdout.flush()

    return 0

if __name__ == '__main__':
    from optparse import OptionParser
    usage = 'Usage: %prog [options]'
    description = 'Note: options will override %s file.' % pyalib.PYAXEL_CONFIG
    parser = OptionParser(usage=usage, description=description, version=__version__)
    parser.add_option('-a', '--host', dest='host',
                      type='string', default='127.0.0.1',
                      help='change the address of the network interface',
                      metavar='HOST')
    parser.add_option('-p', '--port', dest='port',
                      type='int', default=8002,
                      help='change the port to listen on for connections',
                      metavar='PORT')
    parser.add_option('-v', '--verbose', dest='verbose', action='store_true',
                      help='print HTTP headers to stdout')
    parser.add_option('-d', '--debug', dest='debug', action='store_true',
                      help='print debug info on error')
    opts, args = parser.parse_args()
    sys.exit(run(vars(opts)))
