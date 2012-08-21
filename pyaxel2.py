#!/usr/bin/env python

import Queue
import os
import socket
import sys
import time
import threading

import threadpool
import pyaxel as pyaxellib

try:
    import cPickle as pickle
except:
    import pickle

qfile_map = {}


def pyaxel_open(pyaxel):
    if pyaxel.outfd == -1:
        if not pyaxellib.pyaxel_open(pyaxel):
            return 0

    qfile_map[pyaxel.outfd] = Queue.Queue(maxsize=1)

    for conn in pyaxel.conn:
        conn.start_byte = conn.current_byte

    return 1

def pyaxel_start(pyaxel):
    for i, conn in enumerate(pyaxel.conn):
        pyaxellib.conn_set(conn, pyaxel.url[0])
        conn.conf = pyaxel.conf
        if i:
            conn.supported = 1

    pyaxellib.pyaxel_message(pyaxel, 'Starting download.')

    pyaxel.threads = threadpool.ThreadPool(pyaxel.conf.num_connections)
    for conn in pyaxel.conn:
        if conn.current_byte <= conn.last_byte:
            conn.state = 1
            conn.reconnect_count = 0
            pyaxel.threads.addJob(threadpool.JobRequest(setup_thread, [conn]))
            conn.last_transfer = time.time()

    pyaxel.start_time = time.time()
    pyaxel.start_byte = pyaxel.bytes_done
    pyaxel.active_threads = pyaxel.conf.num_connections
    pyaxel.ready = 0

def pyaxel_stop(pyaxel):
    for conn in pyaxel.conn:
        conn.enabled = 0

def pyaxel_do(pyaxel):
    if time.time() > pyaxel.next_state:
        pyaxel_save(pyaxel)
        pyaxel.next_state = time.time() + pyaxel.conf.save_state_interval

    for job in pyaxel.threads.iterProcessedJobs(0):
        state, conn = job.result()
        if state == -2:
            pyaxellib.pyaxel_message(pyaxel, 'Write error!')
            pyaxellib.conn_disconnect(conn)
            pyaxel.active_threads -= 1
        elif state == -1:
            pyaxellib.conn_disconnect(conn)
            if conn.state == 0 and conn.current_byte < conn.last_byte:
                pyaxellib.pyaxel_message(pyaxel, 'Restarting connection %d.' % pyaxel.conn.index(conn))
                if conn.reconnect_count > 5:
                    pyaxellib.pyaxel_message(pyaxel, 'Error on connection %d: Too many reconnect attempts.' % pyaxel.conn.index(conn))
                    pyaxel.active_threads -= 1
                    continue
                conn.reconnect_count += 1
                pyaxellib.conn_set(conn, pyaxel.url[0])
                conn.state = 1
                pyaxel.threads.addJob(threadpool.JobRequest(setup_thread, [conn]))
                conn.last_transfer = time.time()
            else:
                pyaxellib.pyaxel_message(pyaxel, 'Error on connection %d.' % pyaxel.conn.index(conn))
        elif state == 0:
            if conn.current_byte < conn.last_byte:
                pyaxellib.pyaxel_message(pyaxel, 'Connection %d unexpectedly closed.' % pyaxel.conn.index(conn))
            else:
                pyaxellib.pyaxel_message(pyaxel, 'Connection %d finished.' % pyaxel.conn.index(conn))
            pyaxellib.conn_disconnect(conn)
            pyaxel.active_threads -= 1
        elif state == 1:
            pyaxellib.pyaxel_message(pyaxel, 'Connection %d opened.' % pyaxel.conn.index(conn))
            pyaxel.threads.addJob(threadpool.JobRequest(download_thread, [pyaxel, conn]))

    pyaxel.bytes_done = pyaxel.start_byte + sum([conn.current_byte - conn.start_byte for conn in pyaxel.conn])
    if pyaxel.bytes_done == pyaxel.size:
        pyaxellib.pyaxel_message(pyaxel, 'Download complete.')
        pyaxel.ready = 1

def pyaxel_seek(pyaxel, offset):
    qfile_map[pyaxel.outfd].put(offset, block=True)

def pyaxel_write(pyaxel, data):
    os.lseek(pyaxel.outfd, qfile_map[pyaxel.outfd].get(), os.SEEK_SET)
    os.write(pyaxel.outfd, data)

def pyaxel_close(pyaxel):
    if pyaxel.outfd in qfile_map:
        del qfile_map[pyaxel.outfd] # WARN
    pyaxellib.pyaxel_close(pyaxel)

def pyaxel_unlink(pyaxel):
    if os.path.exists('%s.st' % self.axel.file_name):
        os.remove('%s.st' % self.axel.file_name)
    if os.path.exists(self.axel.file_name):
        os.remove(self.axel.file_name)

def pyaxel_save(pyaxel):
    if not pyaxel.conn[0].supported:
        return

    try:
        with open('%s.st' % pyaxel.file_name, 'wb') as fd:
            bytes = [conn.current_byte for conn in pyaxel.conn]
            state = {
                'num_connections': pyaxel.conf.num_connections,
                'bytes_done': pyaxel.start_byte + sum([offset - conn.start_byte for offset, conn in zip(bytes, pyaxel.conn)]),
                'current_byte': bytes
            }
            pickle.dump(state, fd)
    except IOError:
        pass

def download_thread(pyaxel, conn):
    while conn.enabled == 1:
        conn.last_transfer = time.time()
        fetch_size = min(conn.last_byte + 1 - conn.current_byte, pyaxel.conf.buffer_size)
        try:
            data = conn.http.fd.read(fetch_size)
        except socket.error:
            return (-1, conn)
        size = len(data)
        if size == 0:
            return (0, conn)
        if size != fetch_size:
            return (-1, conn)
        try:
            pyaxel_seek(pyaxel, conn.current_byte)
            pyaxel_write(pyaxel, data)
        except IOError:
            return (-2, conn)
        conn.current_byte += size

    return (0, conn)

def setup_thread(conn):
    if pyaxellib.conn_setup(conn):
        conn.last_transfer = time.time()
        if pyaxellib.conn_exec(conn):
            conn.last_transfer = time.time()
            conn.state = 0
            conn.enabled = 1
            return (1, conn)

    pyaxellib.conn_disconnect(conn)
    conn.state = 0
    return (-1, conn)

def main(argv=None):
    import stat
    import os

    from optparse import OptionParser

    if argv is None:
        argv = sys.argv

    parser = OptionParser(usage='Usage: %prog [options] url')
    parser.add_option('-q', '--quiet', dest='verbose',
                      default=False, action='store_true',
                      help='leave stdout alone')
    parser.add_option('-p', '--print', dest='http_debug',
                      default=False, action='store_true',
                      help='print HTTP info')
    parser.add_option('-n', '--num-connections', dest='num_connections',
                      type='int', default=1,
                      help='specify maximum number of connections',
                      metavar='x')
    parser.add_option('-s', '--max-speed', dest='max_speed',
                      type='int', default=0,
                      help='specify maximum speed (bytes per second)',
                      metavar='x')

    (options, args) = parser.parse_args(argv[1:])

    if len(args) != 1:
        parser.print_help()
    else:
        # TODO search mirrors
        try:
            url = args[0]
            conf = pyaxellib.conf_t()

            pyaxellib.conf_init(conf)
            if not pyaxellib.conf_load(conf, pyaxellib.PYAXEL_PATH + pyaxellib.PYAXEL_CONFIG):
                return 1

            for prop in options.__dict__:
                if not callable(options.__dict__[prop]):
                    setattr(conf, prop, getattr(options, prop))

            conf.verbose = bool(conf.verbose)
            conf.http_debug = bool(conf.http_debug)
            conf.num_connections = options.num_connections

            axel = pyaxellib.pyaxel_new(conf, 0, url)
            if axel.ready == -1:
                pyaxellib.pyaxel_print(axel)
                return 1

            pyaxellib.pyaxel_print(axel)

            # TODO check permissions, destination opt, etc.
            if not bool(os.stat(os.getcwd()).st_mode & stat.S_IWUSR):
                print 'Can\'t access protected directory: %s' % os.getcwd()
                return 1
#                if not os.access(axel.file_name, os.F_OK):
#                    print 'Couldn\'t access %s' % axel.file_name
#                    return 0
#                if not os.access('%s.st' % axel.file_name, os.F_OK):
#                    print 'Couldn\'t access %s.st' % axel.file_name
#                    return 0

            if not pyaxel_open(axel):
                pyaxellib.pyaxel_print(axel)
                return 1

            pyaxel_start(axel)
            pyaxellib.pyaxel_print(axel)

            while axel.active_threads:
                pyaxel_do(axel)
                if axel.message:
                    pyaxellib.pyaxel_print(axel)
                sys.stdout.write('Downloaded [%d%%]\r' % (axel.bytes_done * 100 / axel.size))
                sys.stdout.flush()
                time.sleep(1)

            pyaxel_close(axel)
        except KeyboardInterrupt:
            print
            return 1
        except:
            import debug
            debug.backtrace()
            return 1

        return 0

if __name__ == '__main__':
    sys.exit(main())
