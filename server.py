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

import pyaxel as pyaxellib
import pyaxel2
import threadpool
import websocket


# channel_c reply codes
(ACK, OK, INVALID, BAD_REQUEST, ERROR, PROC, END, INCOMPLETE, STOPPED,
 UNDEFINED, INITIALIZING) = range(11)

# channel_c command inputs
(IDENT, START, STOP, ABORT, QUIT) = range(5)


class StateMachineError(Exception):
    pass


class TransitionError(StateMachineError):
    def __init__(self, inp, cur, msg):
        self.inp = inp
        self.cur = cur
        self.msg = msg


class StateMachine:
    def __init__(self):
        self.states = {}
        self.state = None

    def start(self, state):
        self.state = state

    def add(self, state, inp, newstate, action=None):
        try:
            self.states[state][inp] = (newstate, action)
        except KeyError:
            self.states[state] = {}
            self.states[state][inp] = (newstate, action)

    def execute(self, inp, args=()):
        if self.state not in self.states:
            raise StateMachineError('invalid state: %s' % self.state)
        state = self.states[self.state]
        if inp in state:
            newstate, action = state[inp]
            if action is not None:
                action(self.state, inp, args)
            self.state = newstate
        else:
            if None in state:
                newstate, action = state[None]
                if action is not None:
                    action(self.state, inp, args)
                self.state = newstate
            else:
                raise TransitionError(self.inp, self.cur, 'input not recognized')


class channel_c:
    def __init__(self, sock, server):
        self.axel = None
        self.server = server
        self.websocket = websocket.AsyncChat(sock, self)
        self.state = StateMachine()
        self.state.add('initial', IDENT, 'listening', self.state_ident)
        self.state.add('listening', START, 'established', self.state_start)
        self.state.add('listening', ABORT, 'listening', self.state_abort)
        self.state.add('listening', QUIT, 'listening', self.state_quit)
        self.state.add('established', STOP, 'listening', self.state_stop)
        self.state.add('established', ABORT, 'listening', self.state_abort)
        self.state.add('established', QUIT, 'listening', self.state_quit)
        self.state.start('initial')

    def state_ident(self, state, inp, args):
        if args and args.get('type') in ['ECHO', 'MGR', 'WKR']:
            if args.get('type') == 'ECHO':
                self.websocket.handle_response(deflate_msg({'event':OK,
                    'data':args.get('msg')}))
                self.websocket.disconnect()
            elif args.get('type') == 'MGR':
                self.state.start('initial')
                msg = {'event':ACK}
                if 'pref' in args:
                    pass
                if 'info' in args:
                    msg['version'] = pyaxellib.PYAXEL_VERSION
                self.websocket.handle_response(deflate_msg(msg))
            else:
                self.websocket.handle_response(deflate_msg({'event':ACK}))
        else:
            self.websocket.handle_response(deflate_msg({'event':BAD_REQUEST}))

    # start/resume
    def state_start(self, state, inp, args):
        self.websocket.handle_response(deflate_msg({'event':INITIALIZING}))

        url = args.get('url')
        conf = pyaxellib.conf_t()

        pyaxellib.conf_init(conf)
        if not pyaxellib.conf_load(conf, pyaxellib.PYAXEL_PATH + pyaxellib.PYAXEL_CONFIG):
            raise Exception('couldn\'t load pyaxel config file')

        self.axel = pyaxellib.pyaxel_new(conf, 0, url)
        if self.axel.ready == -1:
            pyaxellib.pyaxel_print(self.axel)
            raise Exception(self.axel.last_error)

        pyaxellib.pyaxel_print(self.axel)

        if not bool(os.stat(os.getcwd()).st_mode & stat.S_IWUSR):
            raise Exception('can\'t access protected directory: %s' % os.getcwd())

        if not pyaxel2.pyaxel_open(self.axel):
            pyaxellib.pyaxel_print(self.axel)
            raise Exception(self.axel.last_error)

        # TODO send content-type header
        msg = {
            'event': OK,
            'url': url,
            'name': self.axel.file_name,
            'type': 'test',
            'size': self.axel.size,
            'chunks': [conn.last_byte - conn.first_byte for conn in self.axel.conn],
            'progress': [conn.current_byte - conn.first_byte for conn in self.axel.conn]
        }
        self.websocket.handle_response(deflate_msg(msg))

        pyaxel2.pyaxel_start(self.axel)
        pyaxellib.pyaxel_print(self.axel)

    # pause
    def state_stop(self, state, inp, args):
        if self.axel:
            print "Stopping:", self.axel.file_name
            pyaxel2.pyaxel_close(self.axel)
        self.websocket.handle_response(deflate_msg({"event":STOPPED}))

    # quit
    def state_abort(self, state, inp, args):
        if self.axel:
            print "Aborting:", self.axel.file_name
            pyaxel2.pyaxel_close(self.axel)
            pyaxel2.pyaxel_unlink(self.axel)
            self.axel = None
        self.websocket.handle_response(deflate_msg({'event':INCOMPLETE}))

    # disconnect
    def state_quit(self, state, inp, args):
        self.close()

    def chat_message(self, msg):
        try:
            msg = inflate_msg(msg)
            self.state.execute(msg['cmd'], msg.get('arg'))
        except StateMachineError, e:
            self.websocket.handle_response(deflate_msg({'event':BAD_REQUEST,'data':e}))
        except TransitionError, e:
            resp = '\'%s\' %s <state:%s>' % (e.inp, e.msg, e.cur)
            self.websocket.handle_response(deflate_msg({'event':BAD_REQUEST,'data':resp}))
        except Exception, e:
            import debug
            debug.backtrace()
            self.state.start('listening')
            self.websocket.handle_response(deflate_msg({'event':BAD_REQUEST,'data':str(e)}))
            self.close()

    def chat_error(self):
        self.close()

    def update(self):
        if not self.axel or self.axel.ready == -1:
            return

        if self.axel.active_threads:
            pyaxel2.pyaxel_do(self.axel)
            msg = {
                'event': PROC,
                'progress': [conn.current_byte - conn.first_byte for conn in self.axel.conn],
                'rate': format_size(self.axel.bytes_done / (time.time() - self.axel.start_time))
            }
            self.websocket.handle_response(deflate_msg(msg))
            if self.axel.message:
                pyaxellib.pyaxel_print(self.axel)
            return

        if self.axel.ready == 1:
            self.websocket.handle_response(deflate_msg({'event':END}))
        else:
            self.websocket.handle_response(deflate_msg({'event':INCOMPLETE}))

        pyaxel2.pyaxel_close(self.axel)

    def close(self, status=1000, reason=''):
        if self.axel and self.axel.ready == 0:
            pyaxel2.pyaxel_close(self.axel)
            self.axel = None

        self.websocket.disconnect(status, reason)
        self.server.remove_channel(self)


class server_c(asyncore.dispatcher):
    def __init__(self):
        asyncore.dispatcher.__init__(self)
        self.channels = []

    def writable(self):
        return False

    def handle_accept(self):
        try:
            conn, addr = self.accept()
            if addr:
                self.log('incoming connection from %s' % repr(addr))
                self.channels.append(channel_c(conn, self))
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
            for channel in self.channels:
                channel.update()

    def stop_service(self):
        self.log('stopping service')
        self.close()
        for c in self.channels:
            c.close(status=1001, reason='server shutdown')

    def remove_channel(self, channel):
        self.channels.remove(channel)


def format_size(num, prefix=True):
    if num < 1:
        return '0'
    try:
        k = int(math.log(num, 1024))
        return '%.2f%s' % (num / (1024.0 ** k), 'bKMGTPEY'[k] if prefix else '')
    except TypeError:
        return '0'

def deflate_msg(msg):
    return json.dumps(msg, separators=(',',':'))

def inflate_msg(msg):
    return json.loads(msg)

def run(options={}):
    if sys.platform.startswith('win'):
        print 'aborting: unsupported platform:', sys.platform
        return 1

    major, minor, micro, release, serial = sys.version_info
    if (major, minor, micro) < (2, 6, 0):
        print 'aborting: unsupported python version: %s.%s.%s' % \
            (major, minor, micro)
        return 1

    server = server_c()
    try:
        server.start_service(('127.0.0.1', 8002))
    except socket.error:
        pass
    except KeyboardInterrupt:
        print
        pass
    except:
        import debug
        debug.backtrace()

    server.stop_service()
    sys.stdout.flush()

    return 0

if __name__ == '__main__':
#    usage='Usage: %prog [options]'
#    description='Note: options will be overridden by those that exist in the' \
#        ' %s file.' % pyaxel.PYAXELWS_SETTINGS
#    parser = OptionParser(usage=usage, description=description)
#    parser.add_option('-s', '--max-speed', dest='max_speed',
#                      type='int', default=0,
#                      help='Specifies maximum speed (Kbytes per second).'
#                      ' Useful if you don't want the program to suck up'
#                      ' all of your bandwidth',
#                      metavar='SPEED')
#    parser.add_option('-n', '--num-connections', dest='num_connections',
#                      type='int', default=1,
#                      help='You can specify the number of connections per'
#                      ' download here. The default is %d.' % 1,
#                      metavar='NUM')
#    parser.add_option('-a', '--host', dest='host',
#                      type='string', default=pyaxel.PYAXELWS_HOST,
#                      help='You can specify the address of the network'
#                      ' interface here. The default is %s' % pyaxel.PYAXELWS_HOST,
#                      metavar='HOST')
#    parser.add_option('-p', '--port', dest='port',
#                      type='int', default=pyaxel.PYAXELWS_PORT,
#                      help='You can specify the port to listen for'
#                      ' connections here. The default is %d.' % pyaxel.PYAXELWS_PORT,
#                      metavar='PORT')
#    parser.add_option('-d', '--directory', dest='download_path',
#                      type='string', default=pyaxel.PYAXELWS_DEST,
#                      help='Use this option to change where the files are'
#                      ' saved. By default, files are saved in the current'
#                      ' working directory.',
#                      metavar='DIR')
#    parser.add_option('-v', '--verbose', dest='verbose', action='store_true')
#    (options, args) = parser.parse_args()
#    run(options.__dict__)
    sys.exit(run())
