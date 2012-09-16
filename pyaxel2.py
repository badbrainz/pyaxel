#!/usr/bin/env python

import Queue
import os
import socket
import sys
import stat
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

def pyaxel_new(conf, url):
    pyaxel = pyaxellib.pyaxel_t()
    pyaxel.conf = conf

    if not hasattr(conf, 'download_path') or not conf.download_path:
        pyaxel.conf.download_path = pyaxellib.PYAXEL_PATH
    if not pyaxel.conf.download_path.endswith(os.path.sep):
        pyaxel.conf.download_path += os.path.sep

    if type(url) is list:
        pyaxel.url = Queue.deque(url)
    else:
        pyaxel.url = Queue.deque([url])

    pyaxellib.pyaxel_message(pyaxel, 'Initializing download.')

    pyaxel.active_threads = 1
    pyaxel.threads = threadpool.ThreadPool(1)
    pyaxel.threads.addJob(threadpool.JobRequest(initialize_thread, [pyaxel]))

    return pyaxel

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
    for job in pyaxel.threads.iterProcessedJobs(0):
        state, item = job.result()
        if state == -5: # initialization_thread
            pyaxellib.pyaxel_message(pyaxel, 'Configuring download.')
            pyaxel.threads.addJob(threadpool.JobRequest(configuration_thread, [pyaxel]))
        elif state == -4: # configuration_thread
            pyaxel.active_threads -= 1
            pyaxellib.pyaxel_message(pyaxel, 'Starting download.')
        elif state == -3: # initialization_thread
            pyaxel.active_threads -= 1
            pyaxellib.pyaxel_message(pyaxel, 'Cannot access protected directory: %s' % pyaxel.conf.download_path)
        elif state in (-2, -1): # configuration_thread
            pyaxel.active_threads -= 1
            pyaxellib.pyaxel_message(pyaxel, 'Could not setup pyaxel')
        elif state == 1:
            pyaxellib.conn_disconnect(item)
            if item.state == 0 and item.current_byte < item.last_byte:
                if item.reconnect_count >= pyaxel.conf.max_reconnect:
                    pyaxellib.pyaxel_message(pyaxel, 'Error on connection %d: Too many reconnect attempts.' % pyaxel.conn.index(item))
                    pyaxel.active_threads -= 1
                    continue
            else:
                pyaxellib.pyaxel_message(pyaxel, 'Error on connection %d.' % pyaxel.conn.index(item))
            pyaxellib.pyaxel_message(pyaxel, 'Restarting connection %d.' % pyaxel.conn.index(item))
            item.last_transfer = time.time()
            item.reconnect_count += 1
            threading.Timer(pyaxel.conf.reconnect_delay, pyaxel.threads.addJob, [threadpool.JobRequest(setup_thread, [item])]).start()
        elif state == 2:
            pyaxel.active_threads -= 1
            pyaxellib.pyaxel_message(pyaxel, 'Write error!')
            pyaxellib.conn_disconnect(item)
        elif state == 3:
            if len(pyaxel.url) > 1 and item.http.status != 206:
                pyaxellib.conn_disconnect(item)
                pyaxellib.pyaxel_message(pyaxel, 'Connection %d unsupported: %s' % (pyaxel.conn.index(item), pyaxellib.conn_url(item)))
                pyaxellib.conn_set(item, pyaxel.url[0])
                pyaxel.url.rotate(1)
                item.last_transfer = time.time()
                item.reconnect_count = 0
                pyaxel.threads.addJob(threadpool.JobRequest(setup_thread, [item]))
                continue
            pyaxellib.pyaxel_message(pyaxel, 'Connection %d opened: %s' % (pyaxel.conn.index(item), pyaxellib.conn_url(item)))
            pyaxel.threads.addJob(threadpool.JobRequest(download_thread, [pyaxel, item]))
        elif state == 4:
            pyaxel.active_threads -= 1
            if item.current_byte < item.last_byte:
                pyaxellib.pyaxel_message(pyaxel, 'Connection %d unexpectedly closed.' % pyaxel.conn.index(item))
            else:
                pyaxellib.pyaxel_message(pyaxel, 'Connection %d finished.' % pyaxel.conn.index(item))
            pyaxellib.conn_disconnect(item)

    if pyaxel.ready == 0:
        if time.time() > pyaxel.next_state:
            pyaxel_save(pyaxel)
            pyaxel.next_state = time.time() + pyaxel.conf.save_state_interval

        for conn, bucket in zip(pyaxel.conn, pyaxel.buckets):
            bucket.capacity = pyaxel.conf.max_speed / pyaxel.active_threads
            bucket.fill_rate = pyaxel.conf.max_speed / pyaxel.active_threads
            if conn.enabled:
                conn.delay = bucket.consume((conn.current_byte - conn.start_byte) / (time.time() - pyaxel.start_time))

        pyaxel.bytes_done = pyaxel.bytes_start + sum([conn.current_byte - conn.start_byte for conn in pyaxel.conn])
        pyaxel.bytes_per_second = (pyaxel.bytes_done - pyaxel.bytes_start) / (time.time() - pyaxel.start_time)
        pyaxel.finish_time = pyaxel.start_time + (pyaxel.size - pyaxel.bytes_start) / (pyaxel.bytes_per_second + 1)

        if pyaxel.size and pyaxel.bytes_done == pyaxel.size:
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

def initialize_thread(pyaxel):
    if not bool(os.stat(pyaxel.conf.download_path).st_mode & stat.S_IWUSR):
        return (-3, pyaxel)

    pyaxel.conn = [pyaxellib.conn_t() for i in xrange(pyaxel.conf.num_connections)]
    pyaxel.conn[0].conf = pyaxel.conf

    for i in xrange(len(pyaxel.url)):
        url = pyaxel.url.pop()
        if not pyaxellib.conn_set(pyaxel.conn[0], url):
            pyaxellib.pyaxel_error(pyaxel, 'Could not parse URL: %s' % url)
            continue

        if not pyaxellib.conn_init(pyaxel.conn[0]):
            pyaxellib.pyaxel_error(pyaxel, pyaxel.conn[0].message)
            continue

        if not pyaxellib.conn_info(pyaxel.conn[0]):
            pyaxellib.pyaxel_error(pyaxel, pyaxel.conn[0].message)
            continue

        if pyaxel.conn[0].supported == 0 and len(pyaxel.url) > 0:
            continue

        pyaxel.url.append(pyaxellib.conn_url(pyaxel.conn[0]))
        break

    if len(pyaxel.url) == 0:
        pyaxel.ready = -1
        return (-1, pyaxel)

    pyaxel.size = pyaxel.conn[0].size
    if pyaxel.size != pyaxellib.INT_MAX:
        pyaxellib.pyaxel_message(pyaxel, 'File size: %d' % pyaxel.size)

    pyaxel.file_name = pyaxel.conn[0].disposition or pyaxel.conn[0].file_name
    pyaxel.file_name = pyaxel.file_name.replace('/', '_')
    pyaxel.file_name = pyaxellib.http_decode(pyaxel.file_name) or pyaxel.conf.default_filename
    pyaxel.file_name = pyaxel.conf.download_path + pyaxel.file_name

    if not pyaxellib.pyaxel_open(pyaxel):
        pyaxellib.pyaxel_error(pyaxel, pyaxel.last_error)
        pyaxel.ready = -2
        return (-2, pyaxel)

    qfile_map[pyaxel.outfd] = Queue.Queue(maxsize=1)
    pyaxel.ready = -5

    return (-5, pyaxel)

def configuration_thread(pyaxel):
    for i, conn in enumerate(pyaxel.conn):
        pyaxellib.conn_set(conn, pyaxel.url[0])
        pyaxel.url.rotate(1)
        conn.conf = pyaxel.conf
        if i: conn.supported = 1

    pyaxel.buckets = []
    if pyaxel.conf.max_speed > 0:
        speed = pyaxel.conf.max_speed / pyaxel.conf.num_connections
        for i in xrange(pyaxel.conf.num_connections):
            pyaxel.buckets.append(tokenbucket_c(speed, speed))

        if pyaxel.conf.max_speed / pyaxel.conf.buffer_size < 1:
            pyaxel_message(pyaxel, 'Buffer resized for this speed.')
            pyaxel.conf.buffer_size = pyaxel.conf.max_speed
        pyaxel.delay_time = 10000 / pyaxel.conf.max_speed * pyaxel.conf.buffer_size * pyaxel.conf.num_connections

    pyaxel.start_time = time.time()
    pyaxel.bytes_start = pyaxel.bytes_done

    pyaxel.threads.addWorkers(pyaxel.conf.num_connections - 1)
    for conn in pyaxel.conn:
        conn.start_byte = conn.current_byte
        if conn.current_byte < conn.last_byte:
            conn.delay = 0
            conn.reconnect_count = 0
            pyaxel.active_threads += 1
            pyaxel.threads.addJob(threadpool.JobRequest(setup_thread, [conn]))
            conn.last_transfer = time.time()

    pyaxel.ready = 0

    return (-4, pyaxel)

def download_thread(pyaxel, conn):
    while pyaxel.ready == 0:
        conn.last_transfer = time.time()
        fetch_size = min(conn.last_byte + 1 - conn.current_byte, pyaxel.conf.buffer_size)
        try:
            data = conn.http.fd.read(fetch_size)
        except socket.error:
            return (1, conn)
        size = len(data)
        if size == 0:
            return (4, conn)
        if size != fetch_size:
            return (1, conn)
        try:
            pyaxel_seek(pyaxel, conn.current_byte)
            pyaxel_write(pyaxel, data)
        except IOError:
            return (2, conn)
        conn.current_byte += size
        time.sleep(conn.delay)

    return (4, conn)

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
                      type='int', metavar='x',
                      help='maximum number of connections')
    parser.add_option('-s', '--max-speed', dest='max_speed',
                      type='int', metavar='x',
                      help='maximum speed (bytes per second)')
    parser.add_option('-o', '--output-path', dest='download_path',
                      type='string', metavar='x',
                      help='local download directory')
    parser.add_option('-u', '--user-agent', dest='user_agent',
                      type='string', metavar='x',
                      help='user agent header')

    (options, args) = parser.parse_args(argv[1:])

    if len(args) == 0:
        parser.print_help()
    else:
        # TODO search mirrors
        try:
            conf = pyaxellib.conf_t()

            pyaxellib.conf_init(conf)
            if not pyaxellib.conf_load(conf, pyaxellib.PYAXEL_PATH + pyaxellib.PYAXEL_CONFIG):
                return 1

            options = vars(options)
            for prop in options:
                if options[prop] != None:
                    setattr(conf, prop, options[prop])

            # TODO mirror file comparison
            axel = pyaxel_new(conf, args)

            while axel.active_threads:
                pyaxel_do(axel)
                if axel.message:
                    pyaxellib.pyaxel_print(axel)
                if axel.size:
                    sys.stdout.write('Downloaded [%d%%]\r' % (axel.bytes_done * 100 / axel.size))
                sys.stdout.flush()
                time.sleep(1)

            pyaxellib.pyaxel_print(axel)

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
