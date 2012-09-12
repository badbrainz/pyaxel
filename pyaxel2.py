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

PYAXEL_SRC_VERSION = '1.0.0'

qfile_map = {}


class tokenbucket_c():
    def __init__(self, tokens, fill_rate):
        self.capacity = float(tokens)
        self.credits = float(tokens)
        self.fill_rate = float(fill_rate)
        self.timestamp = time.time()

    def consume(self, tokens):
        if self.credits < self.capacity:
            now = time.time()
            delta = self.fill_rate * (now - self.timestamp)
            self.credits = min(self.capacity, self.credits + delta)
            self.timestamp = now
        tokens = max(tokens, self.credits)
        expected_time = (tokens - self.credits) / self.fill_rate
        if expected_time <= 0:
            self.credits -= tokens
        return max(0, expected_time)


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

    pyaxellib.pyaxel_message(pyaxel, 'Starting download: %s' % pyaxel.file_name)

    pyaxel.buckets = []
    if pyaxel.conf.max_speed > 0:
        speed = pyaxel.conf.max_speed / pyaxel.conf.num_connections
        for i in xrange(pyaxel.conf.num_connections):
            pyaxel.buckets.append(tokenbucket_c(speed, speed))

    pyaxel.threads = threadpool.ThreadPool(pyaxel.conf.num_connections)
    for conn in pyaxel.conn:
        if conn.current_byte <= conn.last_byte:
            conn.delay = 0
            conn.state = 1
            conn.reconnect_count = 0
            pyaxel.threads.addJob(threadpool.JobRequest(setup_thread, [conn]))
            conn.last_transfer = time.time()

    pyaxel.start_time = time.time()
    pyaxel.bytes_start = pyaxel.bytes_done
    pyaxel.active_threads = pyaxel.conf.num_connections
    pyaxel.ready = 0

def pyaxel_stop(pyaxel):
    pyaxellib.pyaxel_message(pyaxel, 'Stopping download: %s' % pyaxel.file_name)

    for conn in pyaxel.conn:
        conn.enabled = 0
    pyaxel.ready = 2

def pyaxel_abort(pyaxel):
    pyaxellib.pyaxel_message(pyaxel, 'Aborting download: %s' % pyaxel.file_name)

    for conn in pyaxel.conn:
        conn.enabled = 0
    pyaxel.ready = 3

def pyaxel_do(pyaxel):
    if time.time() > pyaxel.next_state:
        pyaxel_save(pyaxel)
        pyaxel.next_state = time.time() + pyaxel.conf.save_state_interval

    for job in pyaxel.threads.iterProcessedJobs(0):
        state, conn = job.result()
        if state == 0:
            if conn.current_byte < conn.last_byte:
                pyaxellib.pyaxel_message(pyaxel, 'Connection %d unexpectedly closed.' % pyaxel.conn.index(conn))
            else:
                pyaxellib.pyaxel_message(pyaxel, 'Connection %d finished.' % pyaxel.conn.index(conn))
            pyaxellib.conn_disconnect(conn)
            pyaxel.active_threads -= 1
        elif state == 1:
            pyaxellib.conn_disconnect(conn)
            if conn.state == 0 and conn.current_byte < conn.last_byte:
                if conn.reconnect_count >= pyaxel.conf.max_reconnect:
                    pyaxellib.pyaxel_message(pyaxel, 'Error on connection %d: Too many reconnect attempts.' % pyaxel.conn.index(conn))
                    pyaxel.active_threads -= 1
                    continue
            else:
                pyaxellib.pyaxel_message(pyaxel, 'Error on connection %d.' % pyaxel.conn.index(conn))
            pyaxellib.pyaxel_message(pyaxel, 'Restarting connection %d.' % pyaxel.conn.index(conn))
            pyaxellib.conn_set(conn, pyaxel.url[0])
            conn.last_transfer = time.time()
            conn.reconnect_count += 1
            conn.state = 1
            threading.Timer(pyaxel.conf.reconnect_delay, pyaxel.threads.addJob, [threadpool.JobRequest(setup_thread, [conn])]).start()
        if state == 2:
            pyaxellib.pyaxel_message(pyaxel, 'Write error!')
            pyaxellib.conn_disconnect(conn)
            pyaxel.active_threads -= 1
        elif state == 3:
            pyaxellib.pyaxel_message(pyaxel, 'Connection %d opened.' % pyaxel.conn.index(conn))
            pyaxel.threads.addJob(threadpool.JobRequest(download_thread, [pyaxel, conn]))

    pyaxel.bytes_done = pyaxel.bytes_start + sum([conn.current_byte - conn.start_byte for conn in pyaxel.conn])
    pyaxel.bytes_per_second = (pyaxel.bytes_done - pyaxel.bytes_start) / (time.time() - pyaxel.start_time)
#    pyaxel.finish_time = pyaxel.start_time + (pyaxel.size - pyaxel.bytes_start) / pyaxel.bytes_per_second

    if pyaxel.active_threads and pyaxel.buckets:
        for conn, bucket in zip(pyaxel.conn, pyaxel.buckets):
            bucket.capacity = pyaxel.conf.max_speed / pyaxel.active_threads
            bucket.fill_rate = pyaxel.conf.max_speed / pyaxel.active_threads
            if conn.enabled:
                conn.delay = bucket.consume((conn.current_byte - conn.start_byte) / (time.time() - pyaxel.start_time))

    if pyaxel.bytes_done == pyaxel.size:
        pyaxellib.pyaxel_message(pyaxel, 'Download complete: %s' % pyaxel.file_name)
        pyaxel.ready = 1

def pyaxel_seek(pyaxel, offset):
    qfile_map[pyaxel.outfd].put(offset, block=True)

def pyaxel_write(pyaxel, data):
    os.lseek(pyaxel.outfd, qfile_map[pyaxel.outfd].get(), os.SEEK_SET)
    os.write(pyaxel.outfd, data)

def pyaxel_close(pyaxel):
    if pyaxel.outfd in qfile_map:
        del qfile_map[pyaxel.outfd] # WARN

    for conn in pyaxel.conn:
        conn.enabled = 0

    if pyaxel.ready in (1, 3):
        if os.path.exists('%s.st' % pyaxel.file_name):
            os.remove('%s.st' % pyaxel.file_name)
        if pyaxel.ready == 3:
            if os.path.exists(pyaxel.file_name):
                os.remove(pyaxel.file_name)
    elif pyaxel.bytes_done > 0 and pyaxel.ready != -1:
        pyaxel_save(pyaxel)

    pyaxel.ready = -1

    if pyaxel.outfd != -1:
        os.close(pyaxel.outfd)
        pyaxel.outfd = -1
    for conn in pyaxel.conn:
        pyaxellib.conn_disconnect(conn)

def pyaxel_save(pyaxel):

    if not pyaxel.conn[0].supported:
        return

    try:
        with open('%s.st' % pyaxel.file_name, 'wb') as fd:
            bytes = [conn.current_byte for conn in pyaxel.conn]
            state = {
                'num_connections': pyaxel.conf.num_connections,
                'bytes_done': pyaxel.bytes_start + sum([offset - conn.start_byte for offset, conn in zip(bytes, pyaxel.conn)]),
                'current_byte': bytes
            }
            pickle.dump(state, fd)
    except IOError:
        pass

def pyaxel_print(pyaxel):
    messages = '\n'.join(pyaxel.message)
    del pyaxel.message[:]
    return messages

def download_thread(pyaxel, conn):
    while conn.enabled == 1:
        conn.last_transfer = time.time()
        fetch_size = min(conn.last_byte + 1 - conn.current_byte, pyaxel.conf.buffer_size)
        try:
            data = conn.http.fd.read(fetch_size)
        except socket.error:
            return (1, conn)
        size = len(data)
        if size == 0:
            return (0, conn)
        if size != fetch_size:
            return (1, conn)
        try:
            pyaxel_seek(pyaxel, conn.current_byte)
            pyaxel_write(pyaxel, data)
        except IOError:
            return (2, conn)
        conn.current_byte += size
        time.sleep(conn.delay)

    return (0, conn)

def setup_thread(conn):
    if pyaxellib.conn_setup(conn):
        conn.last_transfer = time.time()
        if pyaxellib.conn_exec(conn):
            conn.last_transfer = time.time()
            conn.state = 0
            conn.enabled = 1
            return (3, conn)

    pyaxellib.conn_disconnect(conn)
    conn.state = 0
    return (1, conn)

def main(argv=None):
    import stat
    import os

    from optparse import OptionParser

    if argv is None:
        argv = sys.argv

    from optparse import OptionParser
    from optparse import IndentedHelpFormatter
    fmt = IndentedHelpFormatter(indent_increment=4, max_help_position=40, width=77, short_first=1)
    parser = OptionParser(usage='Usage: %prog [options] url', formatter=fmt, version=PYAXEL_SRC_VERSION)
    parser.add_option('-n', '--num-connections', dest='num_connections',
                      type='int', default=1,
                      help='maximum number of connections',
                      metavar='x')
    parser.add_option('-s', '--max-speed', dest='max_speed',
                      type='int', default=0,
                      help='maximum speed (bytes per second)',
                      metavar='x')
    parser.add_option('-o', '--output-path', dest='download_path',
                      type='string', default=pyaxellib.PYAXEL_DEST,
                      help='local download directory',
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

            options = vars(options)
            for prop in options:
                setattr(conf, prop, options[prop])

            axel = pyaxellib.pyaxel_new(conf, 0, url)
            if axel.ready == -1:
                pyaxellib.pyaxel_print(axel)
                return 1

            pyaxellib.pyaxel_print(axel)

            if not conf.download_path.endswith(os.path.sep):
                conf.download_path += os.path.sep
            axel.file_name = conf.download_path + axel.file_name

            # TODO check permissions, destination opt, etc.
            if not bool(os.stat(conf.download_path).st_mode & stat.S_IWUSR):
                print 'Can\'t access protected directory: %s' % conf.download_path
                return 1

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
