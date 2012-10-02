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
import pyaxel as pyaxellib
import pyaxel2 as pyaxellib2


SRV_SRC_VERSION = '1.1.0'

# channel_c reply codes
(ACCEPTED, CREATED, CLOSING, BAD_REQUEST, RESERVED) = range(100, 105)

# channel_c command inputs
(IDENT, START, STOP, ABORT, QUIT) = range(5)


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
        self.current_state = None

    def start(self, state):
        self.current_state = state

    def add(self, state, inp, next, action=None):
        try:
            self.states[state][inp] = (next, action)
        except KeyError:
            self.states[state] = {}
            self.states[state][inp] = (next, action)

    def execute(self, inp, args=()):
        if self.current_state not in self.states:
            raise StateMachineError('invalid state: %s' % self.current_state)
        state = self.states[self.current_state]
        if inp in state:
            next, action = state[inp]
            if action is not None:
                action(args)
            self.current_state = next
        else:
            if None in state:
                next, action = state[None]
                if action is not None:
                    action(args)
                self.current_state = next
            else:
                raise TransitionError(self.current_state, inp, 'input not recognized')


class channel_c:
    def __init__(self, sock, server):
        self.axel = None
        self.server = server
        self.websocket = websocket.AsyncChat(sock, self)
        self.state = chanstate_c()
        self.state.add('initial', IDENT, 'listening', self.ident)
        self.state.add('listening', START, 'established', self.start)
        self.state.add('listening', ABORT, 'listening', self.abort)
        self.state.add('listening', QUIT, 'listening', self.quit)
        self.state.add('established', STOP, 'listening', self.stop)
        self.state.add('established', ABORT, 'listening', self.abort)
        self.state.add('established', QUIT, 'listening', self.quit)
        self.state.start('initial')

    def chat_message(self, msg):
        try:
            msg = inflate_msg(msg)
            self.state.execute(msg['cmd'], msg.get('req', {}))
        except TransitionError, e:
            resp = '\'%s\' %s <state:%s>' % (e.inp, e.msg, e.cur)
            self.websocket.handle_response(deflate_msg({'event':BAD_REQUEST,
                'log':resp}))
        except (StateMachineError, Exception):
            self.close()

    def chat_closed(self):
        self.close()

    def ident(self, request):
        if request.get('type') == 'ECHO':
            self.websocket.handle_response(request.get('msg'))
            self.close()
        else:
            self.websocket.handle_response(deflate_msg({'event':ACCEPTED,
                'version': SRV_SRC_VERSION}))

    def start(self, request):
        conf = pyaxellib.conf_t()
        pyaxellib.conf_init(conf)

        prefs = request.get('conf', {})
        for p in prefs:
            setattr(conf, p, prefs[p])

        if 'type' not in request:
            self.websocket.handle_response(deflate_msg({'event':BAD_REQUEST}))
            self.state.start('listening')
            return

        if 'download' == request['type']:
            self.server.add_websocket_channel(self)
            self.axel = pyaxellib2.pyaxel_new(conf, request.get('url'), request.get('metadata'))
            self.websocket.handle_response(deflate_msg({'event':CREATED,
                'log':pyaxellib2.pyaxel_print(self.axel)}))
        elif 'validate' == request['type']:
            if self.axel:
                self.server.add_websocket_channel(self)
                pyaxellib2.pyaxel_checksum(self.axel, request.get('checksum'), request.get('algorithm'))
                self.websocket.handle_response(deflate_msg({'event':RESERVED,
                    'log':pyaxellib2.pyaxel_print(self.axel)}))

    def stop(self, request):
        if self.axel:
            self.server.add_websocket_channel(self)
            pyaxellib2.pyaxel_stop(self.axel)
            self.websocket.handle_response(deflate_msg({'event':CLOSING,
                'log':pyaxellib2.pyaxel_print(self.axel)}))

    def abort(self, request):
        if self.axel:
            self.server.add_websocket_channel(self)
            pyaxellib2.pyaxel_abort(self.axel)
            self.websocket.handle_response(deflate_msg({'event':CLOSING,
                'log':pyaxellib2.pyaxel_print(self.axel)}))

    def quit(self, request):
        self.close()

    def update(self):
        pyaxellib2.pyaxel_do(self.axel)
        if self.axel.active_threads:
            if self.axel.msg:
                self.websocket.handle_response(deflate_msg(self.axel.msg))
        else:
            self.close(0)

    def close(self, status=1000, reason=''):
        if self.websocket.handshaken:
            if self.axel:
                if self.axel.msg:
                    self.websocket.handle_response(deflate_msg(self.axel.msg))
                if self.axel.ready != -1:
                    pyaxellib2.pyaxel_close(self.axel)
            if status > 999:
                self.websocket.disconnect(status, reason)

        self.server.remove_websocket_channel(self)
        self.state.start('listening')


class server_c(asyncore.dispatcher):
    def __init__(self):
        asyncore.dispatcher.__init__(self)
        self.websocket_channels = []

    def writable(self):
        return False

    def handle_accept(self):
        try:
            conn, addr = self.accept()
            if addr:
                self.log('incoming connection from %s' % repr(addr))
                channel_c(conn, self)
        except socket.error, err:
            self.log_info('error: %s' % err, 'error')

    def start_service(self, endpoint, backlog=5):
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind(endpoint)
        self.listen(backlog)
        self.log('websocket server waiting on %s' % repr(endpoint))
        while asyncore.socket_map:
            asyncore.loop(use_poll=True, timeout=1, count=1)
            for channel in self.websocket_channels:
                channel.update()

    def stop_service(self):
        self.log('stopping service')
        self.close()
        for channel in self.websocket_channels:
            channel.close(status=1001, reason='server shutdown')

    def add_websocket_channel(self, channel):
        if channel not in self.websocket_channels:
            self.websocket_channels.append(channel)

    def remove_websocket_channel(self, channel):
        if channel in self.websocket_channels:
            self.websocket_channels.remove(channel)


def deflate_msg(msg):
    return json.dumps(msg, separators=(',',':'))

def inflate_msg(msg):
    return json.loads(msg)

def run(opts={}):
    major, minor, micro, release, serial = sys.version_info
    if (major, minor, micro) < (2, 6, 0):
        sys.stderr.write('aborting: unsupported python version: %s.%s.%s\n' % \
            (major, minor, micro))
        return 1

    if opts.get('verbose'):
        pyaxellib.dbg_lvl = 1

    server = server_c()
    try:
        server.start_service((opts.get('host', '127.0.0.1'), opts.get('port', 8002)))
    except socket.error:
        pass
    except KeyboardInterrupt:
        print
    except:
        import debug
        debug.backtrace()

    server.stop_service()
    sys.stdout.flush()

    return 0

if __name__ == '__main__':
    from optparse import OptionParser
    usage = 'Usage: %prog [options]'
    description = 'Note: options will override %s file.' % pyaxellib.PYAXEL_CONFIG
    parser = OptionParser(usage=usage, description=description, version=SRV_SRC_VERSION)
    parser.add_option('-a', '--host', dest='host',
                      type='string', default='127.0.0.1',
                      help='change the address of the network interface',
                      metavar='HOST')
    parser.add_option('-p', '--port', dest='port',
                      type='int', default=8002,
                      help='change the port to listen on for connections',
                      metavar='PORT')
    parser.add_option('-v', '--verbose', dest='verbose', action='store_true',
                      help='print HTTP headers to stdout',)
    opts, args = parser.parse_args()
    sys.exit(run(vars(opts)))
