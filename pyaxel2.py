#!/usr/bin/env python

import hashlib
import math
import os
import Queue
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


__version__ = '1.0.0'

fdlock_map = {}

(FOUND, PROCESSING, COMPLETED, CANCELLED, STOPPED, INVALID, ERROR,
 VERIFIED, CLOSING, RESERVED, CONNECTING) = range(200, 211)


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


def pyaxel_new(conf, url, metadata=None):
    pyaxel = pyaxellib.pyaxel_t()
    pyaxel.conf = conf
    pyaxel.metadata = metadata

    if not hasattr(conf, 'download_path') or not conf.download_path:
        pyaxel.conf.download_path = pyaxellib.PYAXEL_PATH
    if not pyaxel.conf.download_path.endswith(os.path.sep):
        pyaxel.conf.download_path += os.path.sep

    if type(url) is list:
        pyaxel.conf.num_connections = sorted([1, pyaxel.conf.num_connections, len(url)])[1]
        pyaxel.url = Queue.deque(url)
    else:
        pyaxel.url = Queue.deque([url])

    pyaxel.threads = threadpool.ThreadPool(1)
    pyaxel.threads.addJob(threadpool.JobRequest(pyaxel_initialize, [pyaxel]))
    pyaxel.active_jobs = 1

    pyaxel.ready = -8
    pyaxel_message(pyaxel)

    return pyaxel

def pyaxel_initialize(pyaxel):
    if not os.path.exists(pyaxel.conf.download_path):
        pyaxel.ready = -2
        return (-3, pyaxel)

    if not bool(os.stat(pyaxel.conf.download_path).st_mode & (stat.S_IFDIR|stat.S_IWUSR)):
        pyaxel.ready = -2
        return (-3, pyaxel)

    pyaxel.conn = [pyaxellib.conn_t()]
    pyaxel.conn[0].conf = pyaxel.conf

    for i in xrange(len(pyaxel.url)):
        url = pyaxel.url.popleft()
        if not pyaxellib.conn_set(pyaxel.conn[0], url):
            # could not parse url
            continue

        if not pyaxellib.conn_init(pyaxel.conn[0]):
            pyaxellib.pyaxel_error(pyaxel, pyaxel.conn[0].message)
            continue

        if not pyaxellib.conn_info(pyaxel.conn[0]):
            pyaxellib.pyaxel_error(pyaxel, pyaxel.conn[0].message)
            continue

        if pyaxel.conn[0].supported != 1 and len(pyaxel.url) > 0:
            continue

        pyaxel.url.appendleft(pyaxellib.conn_url(pyaxel.conn[0]))
        break

    if len(pyaxel.url) == 0:
        pyaxel.ready = -2
        return (-2, pyaxel)

    pyaxel.size = pyaxel.conn[0].size

    pyaxel.file_fname = pyaxel.conn[0].disposition or pyaxel.conn[0].file_name
    pyaxel.file_fname = pyaxel.file_fname.replace('/', '_')
    pyaxel.file_fname = pyaxellib.http_decode(pyaxel.file_fname) or pyaxel.conf.default_filename
    pyaxel.file_name = pyaxel.conf.download_path + pyaxel.file_fname

    pyaxel.file_type = pyaxellib.http_header(pyaxel.conn[0].http, 'content-type')
    if not pyaxel.file_type:
        pyaxel.file_type = 'application/octet-stream'

    if pyaxel.metadata:
        pyaxel.verified_progress = 0
        if 'pieces' in pyaxel.metadata:
            pyaxel.conf.max_speed = 0 # FIXME
            pyaxel.conf.buffer_size = pyaxel.metadata['pieces']['length']
            pyaxel.conf.num_connections = sorted((1, pyaxel.conf.num_connections, len(pyaxel.metadata['pieces']['hashes'])))[1]

    if pyaxel.conf.num_connections > 1:
        pyaxel.conn.extend([pyaxellib.conn_t() for i in xrange(pyaxel.conf.num_connections - 1)])

    if not pyaxel_open(pyaxel):
        pyaxellib.pyaxel_error(pyaxel, pyaxel.last_error)
        pyaxel.ready = -2
        return (-2, pyaxel)

    fdlock_map[pyaxel.outfd] = threading.Lock()

    pyaxel.ready = -5
    return (-5, pyaxel)

def pyaxel_configure(pyaxel):
    for i, conn in enumerate(pyaxel.conn):
        pyaxellib.conn_set(conn, pyaxel.url[0])
        pyaxel.url.rotate(-1)
        conn.conf = pyaxel.conf

    pyaxel.buckets = []
    if pyaxel.conf.max_speed > 0:
        speed = pyaxel.conf.max_speed / pyaxel.conf.num_connections
        for i in xrange(pyaxel.conf.num_connections):
            pyaxel.buckets.append(tokenbucket_c(speed, speed))

        if pyaxel.conf.max_speed < pyaxel.conf.buffer_size:
            pyaxel.conf.buffer_size = pyaxel.conf.max_speed

    pyaxel.start_time = time.time()
    pyaxel.bytes_start = pyaxel.bytes_done

    pyaxel.threads.addWorkers(pyaxel.conf.num_connections - 1)
    for conn in pyaxel.conn:
        conn.delay = 0
        conn.retries = 1
        conn.reconnect_count = 0
        conn.start_byte = conn.current_byte
        if conn.start_byte < conn.last_byte:
            pyaxel.threads.addJob(threadpool.JobRequest(pyaxel_connect, [conn]))
            pyaxel.active_jobs += 1

    pyaxel.ready = 0
    return (-4, pyaxel)

def pyaxel_connect(conn):
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

def pyaxel_divide(pyaxel):
    pieces = -(-pyaxel.size / pyaxel.conf.buffer_size)
    chunks = pieces / pyaxel.conf.num_connections
    for i in xrange(pyaxel.conf.num_connections):
        pyaxel.conn[i].first_byte = i * chunks * pyaxel.conf.buffer_size
        pyaxel.conn[i].current_byte = pyaxel.conn[i].first_byte
        pyaxel.conn[i].last_byte = (i + 1) * chunks * pyaxel.conf.buffer_size - 1
    pyaxel.conn[-1].last_byte = pyaxel.size - 1

def pyaxel_open(pyaxel):
    pyaxel.outfd = -1

    if not pyaxel.conn[0].supported:
        pyaxellib.pyaxel_message(pyaxel, 'Server unsupported. Starting with one connection.')
        pyaxel.conf.num_connections = 1
        pyaxel.conn = pyaxel.conn[:1]
    else:
        try:
            with open('%s.st' % pyaxel.file_name, 'rb') as fd:
                st = pickle.load(fd)

                pyaxel.conf.num_connections = st['num_connections']

                if pyaxel.conf.num_connections > len(pyaxel.conn):
                    pyaxel.conn.extend([pyaxellib.conn_t() for i in xrange(pyaxel.conf.num_connections - len(pyaxel.conn))])
                elif pyaxel.conf.num_connections < len(pyaxel.conn):
                    pyaxel.conn = pyaxel.conn[:pyaxel.conf.num_connections]

                pyaxel_divide(pyaxel)

                pyaxel.bytes_done = st['bytes_done']
                for conn, byte in zip(pyaxel.conn, st['current_byte']):
                    conn.current_byte = byte

                try:
                    flags = os.O_CREAT | os.O_WRONLY
                    if hasattr(os, 'O_BINARY'):
                        flags |= os.O_BINARY
                    pyaxel.outfd = os.open(pyaxel.file_name, flags)
                except os.error:
                    return 0
        except (IOError, EOFError, pickle.UnpicklingError):
            pass

    if pyaxel.outfd == -1:
        pyaxel_divide(pyaxel)

        try:
            flags = os.O_CREAT | os.O_WRONLY
            if hasattr(os, 'O_BINARY'):
                flags |= os.O_BINARY
            pyaxel.outfd = os.open(pyaxel.file_name, flags)
            if hasattr(os, 'ftruncate'):
                os.ftruncate(pyaxel.outfd, pyaxel.size)
        except os.error:
            return 0

    return 1

def pyaxel_do(pyaxel):
    for job in pyaxel.threads.iterProcessedJobs(0):
        state, item = job.result()
        if state == -7:
            pyaxel.active_jobs -= 1
            pyaxellib.pyaxel_message(pyaxel, 'Failed integrity check')
        elif state == -6:
            pyaxel.active_jobs -= 1
        elif state == -5:
            pyaxel.threads.addJob(threadpool.JobRequest(pyaxel_configure, [pyaxel]))
        elif state == -4:
            pyaxel.active_jobs -= 1
        elif state == -3:
            pyaxel.active_jobs -= 1
            pyaxellib.pyaxel_message(pyaxel, 'Cannot access directory')
        elif state in (-2, -1):
            pyaxel.active_jobs -= 1
            pyaxellib.pyaxel_message(pyaxel, 'Could not setup pyaxel')
        elif state == 1:
            pyaxellib.conn_disconnect(item)
            if pyaxel.ready != 0:
                pyaxel.active_jobs -= 1
                continue
            if item.state == 0 and item.current_byte < item.last_byte:
                if item.reconnect_count == pyaxel.conf.max_reconnect:
                    if item.retries == len(pyaxel.url):
                        pyaxellib.pyaxel_message(pyaxel, 'Connection %d error' % pyaxel.conn.index(item))
                        pyaxel.active_jobs -= 1
                        continue
                    pyaxellib.conn_set(item, pyaxel.url[0])
                    pyaxel.url.rotate(-1)
                    item.retries += 1
                    item.reconnect_count = 0
                    item.last_transfer = time.time()
            pyaxellib.pyaxel_message(pyaxel, 'Connection %d error' % pyaxel.conn.index(item))
            item.last_transfer = time.time()
            item.reconnect_count += 1
            threading.Timer(pyaxel.conf.reconnect_delay, pyaxel.threads.addJob, [threadpool.JobRequest(pyaxel_connect, [item])]).start()
        elif state == 2:
            pyaxellib.pyaxel_message(pyaxel, 'Connection %d error' % pyaxel.conn.index(item))
            pyaxel.active_jobs -= 1
            pyaxellib.conn_disconnect(item)
        elif state == 3:
            if pyaxel.ready != 0:
                pyaxel.active_jobs -= 1
                pyaxellib.conn_disconnect(item)
                continue
            if len(pyaxel.url) > 1 and item.http.status != 206:
                pyaxellib.conn_disconnect(item)
                pyaxellib.pyaxel_message(pyaxel, 'Connection %d error: unsupported %s' % (pyaxel.conn.index(item), pyaxellib.conn_url(item)))
                if item.retries == len(pyaxel.url):
                    pyaxellib.pyaxel_message(pyaxel, 'Connection %d error: tried all mirrors' % pyaxel.conn.index(item))
                    pyaxel.active_jobs -= 1
                    continue
                pyaxellib.conn_set(item, pyaxel.url[0])
                pyaxel.url.rotate(-1)
                item.retries += 1
                item.reconnect_count = 0
                item.last_transfer = time.time()
                pyaxel.threads.addJob(threadpool.JobRequest(pyaxel_connect, [item]))
                continue
            pyaxellib.pyaxel_message(pyaxel, 'Connection %d opened: %s' % (pyaxel.conn.index(item), pyaxellib.conn_url(item)))
            pyaxel.threads.addJob(threadpool.JobRequest(pyaxel_download, [pyaxel, item]))
        elif state == 4:
            pyaxel.active_jobs -= 1
            pyaxellib.conn_disconnect(item)
            pyaxellib.pyaxel_message(pyaxel, 'Connection %d closed' % pyaxel.conn.index(item))
        elif state == 5:
            pyaxel.active_jobs -= 1
            pyaxellib.conn_disconnect(item)
            pyaxellib.pyaxel_message(pyaxel, 'Connection %d error: checksum invalid' % pyaxel.conn.index(item))

    if pyaxel.ready == 0:
        if time.time() > pyaxel.next_state:
            pyaxel_save(pyaxel)
            pyaxel.next_state = time.time() + pyaxel.conf.save_state_interval

        if pyaxel.active_jobs:
            for conn, bucket in zip(pyaxel.conn, pyaxel.buckets):
                bucket.capacity = pyaxel.conf.max_speed / pyaxel.active_jobs
                bucket.fill_rate = pyaxel.conf.max_speed / pyaxel.active_jobs
                if conn.enabled:
                    conn.delay = bucket.consume((conn.current_byte - conn.start_byte) / (time.time() - pyaxel.start_time))

        pyaxel.bytes_done = pyaxel.bytes_start + sum([conn.current_byte - conn.start_byte for conn in pyaxel.conn])
        pyaxel.bytes_per_second = (pyaxel.bytes_done - pyaxel.bytes_start) / (time.time() - pyaxel.start_time) # WARN float
        pyaxel.finish_time = pyaxel.start_time + (pyaxel.size - pyaxel.bytes_start) / (pyaxel.bytes_per_second + 1)

        if pyaxel.size and pyaxel.bytes_done == pyaxel.size:
            pyaxellib.pyaxel_message(pyaxel, 'Download complete')
            pyaxel.ready = 1

    if pyaxel.ready == 1:
        if pyaxel.metadata:
            pyaxellib.pyaxel_message(pyaxel, 'Verifying checksum')
            pyaxel.threads.addJob(threadpool.JobRequest(pyaxel_validate, [pyaxel]))
            pyaxel.active_jobs += 1
            pyaxel.ready = 4

    pyaxel_message(pyaxel)

    return pyaxel.active_jobs

def pyaxel_message(pyaxel):
    pyaxel.msg = None

    if pyaxel.active_jobs:
        if pyaxel.ready == 4:
            pyaxel.msg = {'status':RESERVED}
            pyaxel.msg['verified_progress'] = pyaxel.verified_progress / pyaxel.size * 100
        elif pyaxel.ready in (2, 3):
            pyaxel.msg = {'status':CLOSING}
        elif pyaxel.ready == -8:
            pyaxel.msg = {'status': CONNECTING}
        elif pyaxel.ready == -5:
            pyaxel.msg = {'status': FOUND}
            pyaxel.msg['conf'] = vars(pyaxel.conf)
            pyaxel.msg['name'] = pyaxel.file_fname
            pyaxel.msg['path'] = pyaxel.file_name
            pyaxel.msg['type'] = pyaxel.file_type
            pyaxel.msg['size'] = pyaxel.size
            pyaxel.msg['chunks'] = [conn.last_byte - conn.first_byte for conn in pyaxel.conn]
            pyaxel.msg['progress'] = [conn.current_byte - conn.first_byte for conn in pyaxel.conn]
        elif pyaxel.ready == 0:
            pyaxel.msg = {'status': PROCESSING}
            pyaxel.msg['rate'] = format_size(pyaxel.bytes_per_second)
            pyaxel.msg['progress'] = [conn.current_byte - conn.first_byte for conn in pyaxel.conn]
    else:
        if pyaxel.ready in (0, 3, -1):
            pyaxel.msg = {'status':CANCELLED}
        elif pyaxel.ready == 1:
            pyaxel.msg = {'status':COMPLETED}
        elif pyaxel.ready == 2:
            pyaxel.msg = {'status':STOPPED}
        elif pyaxel.ready in (-3, -2):
            pyaxel.msg = {'status':ERROR}
        elif pyaxel.ready == -6:
            pyaxel.msg = {'status':VERIFIED}
            pyaxel.msg['verified_progress'] = pyaxel.verified_progress / pyaxel.size * 100
        elif pyaxel.ready == -7:
            pyaxel.msg = {'status':INVALID}

    if pyaxel.conf.verbose:
        if pyaxel.msg and pyaxel.message:
            pyaxel.msg['log'] = pyaxel_print(pyaxel)

def pyaxel_print(pyaxel):
    messages = '\n'.join(pyaxel.message)
    del pyaxel.message[:]
    return messages

def pyaxel_download(pyaxel, conn):
    if pyaxel.metadata and 'pieces' in pyaxel.metadata:
        for buffer_size, hash_obj, checksum in pyaxel_hashrange(pyaxel, conn):
            if pyaxel.ready != 0:
                break

            conn.last_transfer = time.time()

            try:
                data = conn.http.fd.read(buffer_size)
            except socket.error:
                return (1, conn)

            size = len(data)
            if size == 0:
                return (4, conn)
            if size != buffer_size:
                return (1, conn)

            hash_obj.update(data)
            if hash_obj.hexdigest() != checksum:
                return (5, conn)

            try:
                pyaxel_write(pyaxel, conn.current_byte, data)
            except IOError:
                return (2, conn)

            conn.current_byte += size
            time.sleep(conn.delay)
    else:
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
                pyaxel_write(pyaxel, conn.current_byte, data)
            except IOError:
                return (2, conn)

            conn.current_byte += size
            time.sleep(conn.delay)

    return (4, conn)

def pyaxel_write(pyaxel, offset, data):
    fdlock_map[pyaxel.outfd].acquire()
    try:
        os.lseek(pyaxel.outfd, offset, os.SEEK_SET)
        os.write(pyaxel.outfd, data)
    finally:
        fdlock_map[pyaxel.outfd].release()

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

def pyaxel_hashrange(pyaxel, conn):
    hash_list = pyaxel.metadata['pieces']['hashes']
    hash_type = pyaxel.metadata['pieces']['type']
    buffer_size = pyaxel.metadata['pieces']['length']
    for i in xrange(conn.current_byte / buffer_size, -(-(conn.last_byte + 1) / buffer_size)):
        yield (min(conn.last_byte + 1 - conn.current_byte, buffer_size), hashlib.new(hash_type), hash_list[i])

def pyaxel_validate(pyaxel):
    if 'hash' in pyaxel.metadata:
        if hasattr(hashlib, pyaxel.metadata['hash']['type']):
            algo = hashlib.new(pyaxel.metadata['hash']['type'])

            with open(pyaxel.file_name, 'rb') as fd:
                fd.seek(0)
                pyaxel.verified_progress = 0
                while True:
                    data = fd.read(2 ** 20)
                    if not data:
                        break
                    algo.update(data)
                    pyaxel.verified_progress += len(data)

            if algo.hexdigest() == pyaxel.metadata['hash']['checksum']:
                pyaxel.ready = -6
                return (-6, pyaxel)

    pyaxel.ready = -7
    return (-7, pyaxel)

def pyaxel_stop(pyaxel):
    pyaxel.ready = 2 if pyaxel.ready != 2 else -1
    pyaxel_message(pyaxel)

def pyaxel_abort(pyaxel):
    pyaxel.ready = 3 if pyaxel.ready != 3 else -1
    pyaxel_message(pyaxel)

def pyaxel_close(pyaxel):
    if pyaxel.ready == -1:
        return

    if pyaxel.outfd != -1:
        os.close(pyaxel.outfd)
        if pyaxel.outfd in fdlock_map:
            del fdlock_map[pyaxel.outfd] # WARN
        pyaxel.outfd = -1

    if pyaxel.ready in (1, 3, -6, -7):
        if os.path.exists('%s.st' % pyaxel.file_name):
            os.remove('%s.st' % pyaxel.file_name)
        if pyaxel.ready == 3:
            if os.path.exists(pyaxel.file_name):
                os.remove(pyaxel.file_name)
    elif pyaxel.bytes_done > 0:
        pyaxel_save(pyaxel)

    for conn in pyaxel.conn:
        pyaxellib.conn_disconnect(conn)
        conn.enabled = 0

def format_size(num, prefix=True):
    if num < 1:
        return '0'
    try:
        k = int(math.log(num, 1024))
        return '%.2f%s' % (num / (1024.0 ** k), 'bkMGTPEY'[k] if prefix else '')
    except TypeError:
        return '0'

def main(argv=None):
    if argv is None:
        argv = sys.argv

    from optparse import OptionParser
    from optparse import IndentedHelpFormatter
    fmt = IndentedHelpFormatter(indent_increment=4, max_help_position=40, width=77, short_first=1)
    parser = OptionParser(usage='Usage: %prog [options] url', formatter=fmt, version=__version__)
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
    parser.add_option('-q', '--quiet', dest='verbose',
                      action='store_false',
                      help='leave stdout alone')

    (options, args) = parser.parse_args(argv[1:])

    if len(args) == 0:
        parser.print_help()
        return 0

    try:
        conf = pyaxellib.conf_t()
        pyaxellib.conf_init(conf)
        if not pyaxellib.conf_load(conf, pyaxellib.PYAXEL_PATH + pyaxellib.PYAXEL_CONFIG):
            return 1

        options = vars(options)
        for prop in options:
            if options[prop] != None:
                setattr(conf, prop, options[prop])

        axel = pyaxel_new(conf, args[0] if len(args) == 1 else args)
        while pyaxel_do(axel):
            if axel.msg and 'log' in axel.msg:
                sys.stdout.write(axel.msg['log'])
                sys.stdout.write('\n')
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
