#!/usr/bin/env python

import asyncore
import asynchat
import array
import atexit
import base64
import hashlib
import json
import math
import os
import socket
import stat
import sys
import struct
import time
import traceback
from signal import SIGTERM

import pyaxel as pyalib
import pyaxelws


__version__ = '1.3.0'

[BAD_REQUEST] = range(100, 101)
[START, STOP, ABORT, QUIT] = range(4)


class Daemon:
    """
    A generic daemon class.
    http://www.jejik.com/articles/2007/02/a_simple_unix_linux_daemon_in_python/
    """

    def __init__(self, pidfile, stdin, stdout, stderr):
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.pidfile = pidfile

    def daemonize(self):
        try:
            pid = os.fork()
            if pid > 0:
                # exit first parent
                sys.exit(0)
        except OSError, e:
            sys.stderr.write("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
            sys.exit(1)

        # decouple from parent environment
        os.chdir("/")
        os.setsid()
        os.umask(0)

        # do second fork
        try:
            pid = os.fork()
            if pid > 0:
                # exit from second parent
                sys.exit(0)
        except OSError, e:
            sys.stderr.write("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
            sys.exit(1)

        # redirect standard file descriptors
        sys.stdout.flush()
        sys.stderr.flush()
        si = file(self.stdin, 'r')
        so = file(self.stdout, 'a+')
        se = file(self.stderr, 'a+', 0)
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())

        # write pidfile
        atexit.register(self.delpid)
        pid = str(os.getpid())
        file(self.pidfile,'w+').write("%s\n" % pid)

    def delpid(self):
        if os.path.exists(self.pidfile):
            os.remove(self.pidfile)

    def start(self, opts={}):
        # Check for a pidfile to see if the daemon already runs
        try:
            pf = file(self.pidfile,'r')
            pid = int(pf.read().strip())
            pf.close()
        except IOError:
            pid = None

        if pid:
            message = "pidfile %s already exist. Daemon already running?\n"
            sys.stderr.write(message % self.pidfile)
            sys.exit(1)

        # Start the daemon
        self.daemonize()
        self.run(opts)

    def stop(self):
        # Get the pid from the pidfile
        try:
            pf = file(self.pidfile,'r')
            pid = int(pf.read().strip())
            pf.close()
        except IOError:
            pid = None

        if not pid:
            message = "pidfile %s does not exist. Daemon not running?\n"
            sys.stderr.write(message % self.pidfile)
            return # not an error in a restart

        # Try killing the daemon process
        try:
            while 1:
                os.kill(pid, SIGTERM)
                time.sleep(0.1)
        except OSError, err:
            err = str(err)
            if err.find("No such process") > 0:
                self.delpid()
            else:
                print str(err)
                sys.exit(1)

    def run(self, opts={}):
        pass

class WebSocket(asynchat.async_chat):
    """this class implements version 13 of the WebSocket protocol,
    http://tools.ietf.org/html/rfc6455
    """

    def __init__(self, sock, reciever):
        asynchat.async_chat.__init__(self, sock)
        self.reciever = reciever
        self.input_buffer = []
        self.output_buffer = []
        self.handshaken = False
        self.state = self.parse_request_header
        self.set_terminator('\x0D\x0A\x0D\x0A')

    def parse_request_header(self, data):
        crlf = '\x0D\x0A'

        # TODO validate GET
        fields = dict([l.split(': ', 1) for l in data.split(crlf)[1:]])
        required = ('Host', 'Upgrade', 'Connection', 'Sec-WebSocket-Key',
                    'Sec-WebSocket-Version')
        if not all(map(lambda f: f in fields, required)):
            self.last_error = (1002, 'malformed request')
            self.handle_error()
            return

        sha1 = hashlib.sha1()
        sha1.update(fields['Sec-WebSocket-Key'])
        sha1.update('258EAFA5-E914-47DA-95CA-C5AB0DC85B11')
        challenge = base64.b64encode(sha1.digest())

        self.push('HTTP/1.1 101 Switching Protocols' + crlf)
        self.push('Upgrade: websocket' + crlf)
        self.push('Connection: Upgrade' + crlf)
        self.push('Sec-WebSocket-Accept: %s' % challenge + crlf * 2)

        self.handshaken = True
        self.set_terminator(2)
        self.state = self.parse_frame_header

    def parse_frame_header(self, data):
        hi, lo = struct.unpack('BB', data)

        # no extensions
        if hi & 0x70:
            self.last_error = (1003, 'no extensions support')
            self.handle_error()
            return

        final = hi & 0x80
        opcode = hi & 0x0F
        #mask = lo & 0x80
        length = lo & 0x7F
        control = opcode & 0x0B

        if not control and opcode == 0x02:
            self.last_error = (1003, 'unsupported data format')
            self.handle_error()
            return

        if final:
            if control >= 0x08:
                # TODO handle ping/pong
                if length > 0x7D:
                    self.last_error = (1002, 'bad frame')
                    self.handle_error()
                    return
        else:
            if not control:
                if opcode == 0x01:
                    # no interleave
                    if self.frame_header:
                        self.last_error = (1003, 'unsupported message format')
                        self.handle_error()
                        return

        self.frame_header = []
        self.frame_header.append(final)
        self.frame_header.append(opcode)
        #self.frame_header.append(mask)
        self.frame_header.append(length)

        if length <= 0x7D:
            self.state = self.parse_payload_masking_key
            self.set_terminator(4)
        elif length == 0x7E:
            self.state = self.parse_payload_extended_len
            self.set_terminator(2)
        else:
            self.state = self.parse_payload_extended_len
            self.set_terminator(8)

    def parse_payload_extended_len(self, data):
        fmt = '>H' if self.frame_header[2] == 0x7E else '>Q'
        self.frame_header[2] = struct.unpack(fmt, data)[0]
        self.state = self.parse_payload_masking_key
        self.set_terminator(4)

    def parse_payload_masking_key(self, data):
        self.frame_header.append(data)
        self.state = self.parse_payload_data
        self.set_terminator(self.frame_header[2])

    def parse_payload_data(self, data):
        bytes = array.array('B', data)
        mask = array.array('B', self.frame_header[3])
        bytes = [chr(b ^ mask[i % 4]) for i, b in enumerate(bytes)]
        self.output_buffer.extend(bytes)
        if self.frame_header[0]:
            msg = ''.join(self.output_buffer)
            del self.output_buffer[:]
            del self.frame_header
            self.reciever.channel_message(msg)
        self.set_terminator(2)
        self.state = self.parse_frame_header

    def collect_incoming_data(self, data):
        self.input_buffer.append(data)

    def found_terminator(self):
        self.state(''.join(self.input_buffer))
        del self.input_buffer[:]

    def handle_close(self):
        self.close()
        self.reciever.channel_closed()
        self._cleanup()

    def handle_error(self):
        if hasattr(self, 'last_error'):
            status, reason = self.last_error
            msg = struct.pack('>H%ds' % len(reason), status, reason)
            self.send_message(msg, 0x08)
        self.handle_close()

    def _cleanup(self):
        del self.output_buffer[:]
        del self.input_buffer[:]
        if hasattr(self, 'last_error'):
            del self.last_error
        if hasattr(self, 'frame_header'):
            del self.frame_header
        self.handshaken = False

    # frontend

    def send_message(self, msg, opcode=0x01):
        if not self.handshaken:
            return

        header = chr(0x80 | opcode)
        length = len(msg)
        if length <= 0x7D:
            header += chr(length)
        elif length <= 0xFFFF:
            header += struct.pack('>BH', 0x7E, length)
        else:
            header += struct.pack('>BQ', 0x7F, length)
        self.push(header + msg)

    def disconnect(self, status=1000, reason=''):
        if not self.handshaken:
            return

        msg = struct.pack('>H%ds' % len(reason), status, reason)
        self.send_message(msg, 0x08)
        self.close()
        self._cleanup()


class StateMachineError(Exception):
    pass


class TransitionError(StateMachineError):
    pass


class ChannelState:
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
                raise TransitionError('input not recognized: %s -> %s' % self.current, inp)


class Channel:
    def __init__(self, sock, server):
        self.axel = None
        self.server = server
        self.websocket = WebSocket(sock, self)
        self.state = ChannelState()
        self.state.add('listening', START, 'established', self.start)
        self.state.add('listening', ABORT, 'listening', self.abort)
        self.state.add('listening', QUIT, 'listening', self.quit)
        self.state.add('established', STOP, 'listening', self.stop)
        self.state.add('established', ABORT, 'listening', self.abort)
        self.state.add('established', QUIT, 'listening', self.quit)
        self.state.start('listening')

    def channel_message(self, msg):
        try:
            msg = json.loads(msg)
            self.state.execute(msg['cmd'], msg.get('req', {}))
        except TransitionError:
            self.send_message({'status':BAD_REQUEST})
        except (StateMachineError, Exception):
            self.close()

    def channel_closed(self):
        self.close()

    def send_message(self, msg):
        self.websocket.send_message(json.dumps(msg, separators=(',',':')))

    def start(self, request):
        conf = pyalib.conf_t()
        pyalib.conf_init(conf)
        prefs = request.get('conf', {})
        for p in prefs:
            setattr(conf, p, prefs[p])
        self.server.add_client(self)
        self.axel = pyaxelws.pyaxel_new(conf, request.get('url'), request.get('metadata'))
        self.send_message(pyaxelws.pyaxel_status(self.axel))

    def stop(self, request):
        self.server.add_client(self)
        pyaxelws.pyaxel_stop(self.axel)
        self.send_message(pyaxelws.pyaxel_status(self.axel))

    def abort(self, request):
        self.server.add_client(self)
        pyaxelws.pyaxel_abort(self.axel)
        self.send_message(pyaxelws.pyaxel_status(self.axel))

    def quit(self, request):
        self.close()

    def update(self):
        pyaxelws.pyaxel_do(self.axel)
        status = pyaxelws.pyaxel_status(self.axel)
        if status:
            self.websocket.send_message(status)
        if not pyaxelws.pyaxel_processes(self.axel):
            self.close(0)
            self.state.start('listening')

    def close(self, status=1000, reason=''):
        if self.axel:
            pyaxelws.pyaxel_close(self.axel)
        if status > 999:
            self.websocket.disconnect(status, reason)
        self.server.remove_client(self)


class Server(asyncore.dispatcher):
    def __init__(self):
        asyncore.dispatcher.__init__(self)
        self.clients = []

    def writable(self):
        return False

    def handle_accept(self):
        try:
            conn, addr = self.accept()
            if addr:
                sys.stdout.write('incoming connection from %s\n' % repr(addr))
                Channel(conn, self)
        except socket.error, err:
            self.log_info(err, 'error')

    def start_service(self, endpoint, backlog=5):
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind(endpoint)
        self.listen(backlog)
        sys.stdout.write('websocket server waiting on %s\n' % repr(endpoint))
        sys.stdout.flush()
        while asyncore.socket_map:
            asyncore.loop(use_poll=True, timeout=1, count=1)
            for c in self.clients:
                c.update()

    def stop_service(self):
        sys.stdout.write('stopping service\n')
        sys.stdout.flush()
        self.close()
        for c in self.clients:
            c.close(status=1001, reason='server shutdown')

    def add_client(self, client):
        if client not in self.clients:
            self.clients.append(client)

    def remove_client(self, client):
        if client in self.clients:
            self.clients.remove(client)


def run(opts={}):
    if opts.get('verbose'):
        pyalib.dbg_lvl = 1

    server = Server()
    try:
        server.start_service((opts.get('host', '127.0.0.1'), opts.get('port', 8002)))
    except KeyboardInterrupt:
        print
    except:
        pass

    server.stop_service()
    sys.stdout.flush()
    return 0

def setup(opts={}):
    major, minor, micro, release, serial = sys.version_info
    if (major, minor, micro) < (2, 6, 0):
        print 'cannot setup server: unsupported Python version.\n'
        return 1

    if (opts.get('kill') or opts.get('daemon')):
        if sys.platform.startswith('win'):
            print 'cannot setup daemon: unsupported platform.\n'
            return 1

        devnull = os.devnull if (hasattr(os, 'devnull')) else '/dev/null'
        pidfile = '/tmp/pyaxelws.pid'
        logfile = '/tmp/pyaxelws.log'
        daemon = Daemon(pidfile=pidfile, stdin=devnull, stdout=logfile, stderr=logfile)
        if (opts.get('kill')):
            daemon.stop()
        if (opts.get('daemon')):
            daemon.run = run
            daemon.start(opts)
        return 0

    return run(opts)

if __name__ == '__main__':
    from optparse import OptionParser
    version = 'server-%s pyaxel-%s pyaxelws-%s\n' % (__version__,
                                                     pyalib.__version__,
                                                     pyaxelws.__version__)
    parser = OptionParser(usage='Usage: %prog [options]', version=version)
    parser.add_option('-a', '--host', dest='host',
                      type='string', metavar='HOST', default='127.0.0.1',
                      help='bind to address (default 127.0.0.1)')
    parser.add_option('-p', '--port', dest='port',
                      type='int', metavar='PORT', default=8002,
                      help='listen on port (default 8002)')
    parser.add_option('-v', '--verbose', dest='verbose', action='store_true',
                      help='print HTTP headers to stdout')
    parser.add_option('-d', '--daemon', dest='daemon', action='store_true',
                      help='run in daemon mode')
    parser.add_option('-k', '--kill', dest='kill', action='store_true',
                      help='kill daemon process')

    opts, args = parser.parse_args()
    sys.exit(setup(vars(opts)))
