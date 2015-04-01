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

try:
    import cPickle as pickle
except:
    import pickle

import pyaxel as pyalib


__version__ = '1.2.0'

fdlock_map = {}

[FOUND, PROCESSING, COMPLETED, CANCELLED, STOPPED, INVALID, ERROR,
 VERIFIED, CLOSING, RESERVED, CONNECTING] = range(200, 211)


## {{{ http://code.activestate.com/recipes/502291/ (r4)
def synchronized(f):
    def wrapper(self, *args, **kwargs):
        try: lock = self.__lock
        except AttributeError: # first time use
            lock = self.__dict__.setdefault('__lock', threading.RLock())
        lock.acquire()
        try: return f(self, *args, **kwargs)
        finally: lock.release()
    return wrapper


class ThreadPool(object):
    def __init__(self, num_workers, input_queue_size=0, output_queue_size=0):
        self._workers = []
        self._activeKey2Job = {}
        self._unassignedKey2Job = {}
        self._unassignedJobs = Queue.Queue(input_queue_size)
        self._processedJobs = Queue.Queue(output_queue_size)
        self.addWorkers(num_workers)

    @synchronized
    def addWorkers(self, n=1):
        for _ in xrange(n):
            self._workers.append(Worker(self._unassignedJobs, self._processedJobs,
                                        self._unassignedKey2Job))

    @synchronized
    def dismissWorkers(self, n=1):
        for _ in xrange(n):
            try: self._workers.pop().dismissed = True
            except IndexError: break

    @synchronized
    def addJob(self, job, timeout=None):
        key = job.key
        self._unassignedKey2Job[key] = self._activeKey2Job[key] = job
        self._unassignedJobs.put(job, timeout is None or timeout>0, timeout)

    @synchronized
    def cancelJob(self, key):
        try:
            del self._unassignedKey2Job[key]
            # if it's not in unassigned, it may be in progress or already
            # processed; don't try to delete it from active
            del self._activeKey2Job[key]
        except KeyError: pass

    @synchronized
    def cancelAllJobs(self):
        while self._unassignedKey2Job:
            del self._activeKey2Job[self._unassignedKey2Job.popitem()[0]]

    def numActiveJobs(self):
        return len(self._activeKey2Job)

    def iterProcessedJobs(self, timeout=None):
        block = timeout is None or timeout>0
        while self._activeKey2Job:
            try: job = self._processedJobs.get(block, timeout)
            except Queue.Empty:
                break
            key = job.key
            # at this point the key is guaranteed to be in _activeKey2Job even
            # if the job has been cancelled
            assert key in self._activeKey2Job
            del self._activeKey2Job[key]
            yield job

    def processedJobs(self, timeout=None):
        if timeout is None or timeout <= 0:
            return list(self.iterProcessedJobs(timeout))
        now = time.time
        end = now() + timeout
        processed = []
        while timeout > 0:
            try: processed.append(self.iterProcessedJobs(timeout).next())
            except StopIteration: break
            timeout = end - now()
        return processed


class JobRequest(object):
    class UnprocessedRequestError(Exception):
        pass

    def __init__(self, callable, args=(), kwds=None, key=None):
        if kwds is None: kwds = {}
        if key is None: key = id(self)
        for attr in 'callable', 'args', 'kwds', 'key':
            setattr(self, attr, eval(attr))
        self._exc_info = None

    def process(self):
        try:
            self._result = self.callable(*self.args, **self.kwds)
        except:
            self._exc_info = sys.exc_info()
        else:
            self._exc_info = None

    def result(self):
        if self._exc_info is not None:
            tp,exception,trace = self._exc_info
            raise tp,exception,trace
        try: return self._result
        except AttributeError:
            raise self.UnprocessedRequestError


class Worker(threading.Thread):
    def __init__(self, inputQueue, outputQueue, unassignedKey2Job, **kwds):
        super(Worker,self).__init__(**kwds)
        self.setDaemon(True)
        self._inputQueue = inputQueue
        self._outputQueue = outputQueue
        self._unassignedKey2Job = unassignedKey2Job
        self.dismissed = False
        self.start()

    def run(self):
        while True:
            # thread blocks here if inputQueue is empty
            job = self._inputQueue.get()
            key = job.key
            try: del self._unassignedKey2Job[key]
            except KeyError:
                continue
            if self.dismissed: # put back the job we just picked up and exit
                self._inputQueue.put(job)
                break
            job.process()
            # thread blocks here if outputQueue is full
            self._outputQueue.put(job)
## end of http://code.activestate.com/recipes/502291/ }}}


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
    pyaxel = pyalib.pyaxel_t()
    pyaxel.conf = conf
    pyaxel.metadata = metadata

    if not hasattr(conf, 'download_path') or not conf.download_path:
        pyaxel.conf.download_path = pyalib.PYAXEL_PATH
    if not pyaxel.conf.download_path.endswith(os.path.sep):
        pyaxel.conf.download_path += os.path.sep

    if type(url) is list:
        pyaxel.conf.num_connections = sorted([1, pyaxel.conf.num_connections, len(url)])[1]
        pyaxel.url = Queue.deque(url)
    else:
        pyaxel.url = Queue.deque([url])

    pyaxel.pool = ThreadPool(1)
    pyaxel.pool.addJob(JobRequest(pyaxel_initialize, [pyaxel]))

    pyaxel.ready = -8

    return pyaxel

def pyaxel_initialize(pyaxel):
    if not os.path.exists(pyaxel.conf.download_path):
        pyaxel.ready = -2
        return (-3, pyaxel)

    if not bool(os.stat(pyaxel.conf.download_path).st_mode & (stat.S_IFDIR|stat.S_IWUSR)):
        pyaxel.ready = -2
        return (-3, pyaxel)

    pyaxel.conn = [pyalib.conn_t()]
    pyaxel.conn[0].conf = pyaxel.conf

    for i in xrange(len(pyaxel.url)):
        url = pyaxel.url.popleft()
        if not pyalib.conn_set(pyaxel.conn[0], url):
            # could not parse url
            continue

        if not pyalib.conn_init(pyaxel.conn[0]):
            pyalib.pyaxel_error(pyaxel, pyaxel.conn[0].message)
            continue

        if not pyalib.conn_info(pyaxel.conn[0]):
            pyalib.pyaxel_error(pyaxel, pyaxel.conn[0].message)
            continue

        if pyaxel.conn[0].supported != 1 and len(pyaxel.url) > 0:
            continue

        pyaxel.url.appendleft(pyalib.conn_url(pyaxel.conn[0]))
        break

    if len(pyaxel.url) == 0:
        pyaxel.ready = -2
        return (-2, pyaxel)

    pyaxel.size = pyaxel.conn[0].size

    pyaxel.file_fname = pyaxel.conf.output_filename or pyaxel.conn[0].disposition or pyaxel.conn[0].file_name
    pyaxel.file_fname = pyalib.http_decode(pyaxel.file_fname) or pyaxel.conf.default_filename
    pyaxel.file_fname = pyaxel.file_fname.replace('/', '_')
    pyaxel.file_name = pyaxel.conf.download_path + pyaxel.file_fname
    pyaxel.file_type = pyalib.http_header(pyaxel.conn[0].http, 'content-type')
    if not pyaxel.file_type:
        pyaxel.file_type = 'application/octet-stream'

    if pyaxel.metadata:
        pyaxel.verified_progress = 0
        if 'pieces' in pyaxel.metadata:
            pyaxel.conf.max_speed = 0 # FIXME
            pyaxel.conf.buffer_size = pyaxel.metadata['pieces']['length']
            pyaxel.conf.num_connections = sorted((1, pyaxel.conf.num_connections, len(pyaxel.metadata['pieces']['hashes'])))[1]

    if pyaxel.conf.num_connections > 1:
        pyaxel.conn.extend([pyalib.conn_t() for i in xrange(pyaxel.conf.num_connections - 1)])

    if not pyaxel_open(pyaxel):
        pyalib.pyaxel_error(pyaxel, pyaxel.last_error)
        pyaxel.ready = -2
        return (-2, pyaxel)

    fdlock_map[pyaxel.outfd] = threading.Lock()

    pyaxel.ready = -5
    return (-5, pyaxel)

def pyaxel_configure(pyaxel):
    for i, conn in enumerate(pyaxel.conn):
        pyalib.conn_set(conn, pyaxel.url[0])
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

    pyaxel.pool.addWorkers(pyaxel.conf.num_connections - 1)
    for conn in pyaxel.conn:
        conn.delay = 0
        conn.retries = 1
        conn.reconnect_count = 0
        conn.start_byte = conn.current_byte
        if conn.start_byte < conn.last_byte:
            pyaxel.pool.addJob(JobRequest(pyaxel_connect, [conn]))

    pyaxel.ready = 0
    return (-4, pyaxel)

def pyaxel_connect(conn):
    if pyalib.conn_setup(conn):
        conn.last_transfer = time.time()
        if pyalib.conn_exec(conn):
            conn.last_transfer = time.time()
            conn.state = 0
            conn.enabled = 1
            return (3, conn)

    pyalib.conn_disconnect(conn)
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
        pyalib.pyaxel_message(pyaxel, 'Server unsupported. Starting with one connection.')
        pyaxel.conf.num_connections = 1
        pyaxel.conn = pyaxel.conn[:1]
    else:
        try:
            with open('%s.st' % pyaxel.file_name, 'rb') as fd:
                st = pickle.load(fd)

                pyaxel.conf.num_connections = st['num_connections']

                if pyaxel.conf.num_connections > len(pyaxel.conn):
                    pyaxel.conn.extend([pyalib.conn_t() for i in xrange(pyaxel.conf.num_connections - len(pyaxel.conn))])
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
    for job in pyaxel.pool.iterProcessedJobs(0):
        status, item = job.result()
        if status == -7:
            pyalib.pyaxel_message(pyaxel, 'Failed integrity check')
        elif status == -6:
            pyalib.pyaxel_message(pyaxel, 'Passed integrity check')
        elif status == -5:
            pyaxel.pool.addJob(JobRequest(pyaxel_configure, [pyaxel]))
        elif status == -4: # pyaxel_configure
            pass
        elif status == -3:
            pyalib.pyaxel_message(pyaxel, 'Cannot access directory')
        elif status in (-2, -1):
            pyalib.pyaxel_message(pyaxel, 'Could not setup pyaxel')
        elif status == 1:
            pyalib.conn_disconnect(item)
            if pyaxel.ready != 0:
                continue
            if item.state == 0 and item.current_byte < item.last_byte:
                if item.reconnect_count == pyaxel.conf.max_reconnect:
                    if item.retries == len(pyaxel.url):
                        pyalib.pyaxel_message(pyaxel, 'Connection %d error' % pyaxel.conn.index(item))
                        continue
                    pyalib.conn_set(item, pyaxel.url[0])
                    pyaxel.url.rotate(-1)
                    item.retries += 1
                    item.reconnect_count = 0
                    item.last_transfer = time.time()
            pyalib.pyaxel_message(pyaxel, 'Connection %d error' % pyaxel.conn.index(item))
            item.last_transfer = time.time()
            item.reconnect_count += 1
            threading.Timer(pyaxel.conf.reconnect_delay, pyaxel.pool.addJob, [JobRequest(pyaxel_connect, [item])]).start()
        elif status == 2:
            pyalib.pyaxel_message(pyaxel, 'Connection %d error' % pyaxel.conn.index(item))
            pyalib.conn_disconnect(item)
        elif status == 3:
            if pyaxel.ready != 0:
                pyalib.conn_disconnect(item)
                continue
            if len(pyaxel.url) > 1 and item.http.status != 206:
                pyalib.conn_disconnect(item)
                pyalib.pyaxel_message(pyaxel, 'Connection %d error: unsupported %s' % (pyaxel.conn.index(item), pyalib.conn_url(item)))
                if item.retries == len(pyaxel.url):
                    pyalib.pyaxel_message(pyaxel, 'Connection %d error: tried all mirrors' % pyaxel.conn.index(item))
                    continue
                pyalib.conn_set(item, pyaxel.url[0])
                pyaxel.url.rotate(-1)
                item.retries += 1
                item.reconnect_count = 0
                item.last_transfer = time.time()
                pyaxel.pool.addJob(JobRequest(pyaxel_connect, [item]))
                continue
            pyalib.pyaxel_message(pyaxel, 'Connection %d opened: %s' % (pyaxel.conn.index(item), pyalib.conn_url(item)))
            if pyaxel.metadata and 'pieces' in pyaxel.metadata:
                pyaxel.pool.addJob(JobRequest(pyaxel_piecewise_download, [pyaxel, item]))
            else:
                pyaxel.pool.addJob(JobRequest(pyaxel_download, [pyaxel, item]))
        elif status == 4:
            pyalib.conn_disconnect(item)
            pyalib.pyaxel_message(pyaxel, 'Connection %d closed' % pyaxel.conn.index(item))
        elif status == 5:
            pyalib.conn_disconnect(item)
            pyalib.pyaxel_message(pyaxel, 'Connection %d error: checksum invalid' % pyaxel.conn.index(item))

    if pyaxel.ready == 0:
        if time.time() > pyaxel.next_state:
            pyaxel_save(pyaxel)
            pyaxel.next_state = time.time() + pyaxel.conf.save_state_interval

        processes = pyaxel.pool.numActiveJobs()
        if processes > 0:
            for conn, bucket in zip(pyaxel.conn, pyaxel.buckets):
                bucket.capacity = pyaxel.conf.max_speed / processes
                bucket.fill_rate = pyaxel.conf.max_speed / processes
                if conn.enabled:
                    conn.delay = bucket.consume((conn.current_byte - conn.start_byte) / (time.time() - pyaxel.start_time))

        pyaxel.bytes_done = pyaxel.bytes_start + sum([conn.current_byte - conn.start_byte for conn in pyaxel.conn])
        pyaxel.bytes_per_second = (pyaxel.bytes_done - pyaxel.bytes_start) / (time.time() - pyaxel.start_time) # WARN float

        if pyaxel.size and pyaxel.bytes_done == pyaxel.size:
            pyalib.pyaxel_message(pyaxel, 'Download complete')
            pyaxel.ready = 1

    if pyaxel.ready == 1:
        if pyaxel.metadata and 'hash' in pyaxel.metadata:
            pyalib.pyaxel_message(pyaxel, 'Verifying checksum')
            pyaxel.pool.addJob(JobRequest(pyaxel_validate, [pyaxel]))
            pyaxel.ready = 4

def pyaxel_processes(pyaxel):
    return pyaxel.pool.numActiveJobs()

def pyaxel_status(pyaxel):
    status = None
    ready = pyaxel.ready

    if pyaxel.pool.numActiveJobs():
        if ready == 4:
            status = {'status':RESERVED}
            status['verified_progress'] = pyaxel.verified_progress / pyaxel.size * 100
        elif ready in (2, 3):
            status = {'status':CLOSING}
        elif ready == -8:
            status = {'status': CONNECTING}
        elif ready == -5:
            status = {'status': FOUND}
            status['conf'] = vars(pyaxel.conf)
            status['name'] = pyaxel.file_fname
            status['path'] = pyaxel.file_name
            status['type'] = pyaxel.file_type
            status['size'] = pyaxel.size
            status['chunks'] = [conn.last_byte - conn.first_byte for conn in pyaxel.conn]
            status['progress'] = [conn.current_byte - conn.first_byte for conn in pyaxel.conn]
        elif ready == 0:
            status = {'status': PROCESSING}
            status['rate'] = format_size(pyaxel.bytes_per_second)
            status['progress'] = [conn.current_byte - conn.first_byte for conn in pyaxel.conn]
    else:
        if ready in (0, 3, -1):
            status = {'status':CANCELLED}
        elif ready == 1:
            status = {'status':COMPLETED}
        elif ready == 2:
            status = {'status':STOPPED}
        elif ready in (-3, -2):
            status = {'status':ERROR}
        elif ready == -6:
            status = {'status':VERIFIED}
            status['verified_progress'] = pyaxel.verified_progress / pyaxel.size * 100
        elif ready == -7:
            status = {'status':INVALID}

    if pyaxel.conf.verbose:
        if status and pyaxel.message:
            status['log'] = pyaxel_print(pyaxel)

    return status

def pyaxel_print(pyaxel):
    messages = '\n'.join(pyaxel.message)
    del pyaxel.message[:]
    return messages

def pyaxel_download(pyaxel, conn):
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

def pyaxel_piecewise_download(pyaxel, conn):
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

def pyaxel_abort(pyaxel):
    pyaxel.ready = 3 if pyaxel.ready != 3 else -1

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
        pyalib.conn_disconnect(conn)
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
        conf = pyalib.conf_t()
        if not pyalib.conf_init(conf):
            return 1

        options = vars(options)
        for prop in options:
            if options[prop] != None:
                setattr(conf, prop, options[prop])

        axel = pyaxel_new(conf, args[0] if len(args) == 1 else args)
        while pyaxel_processes(axel):
            pyaxel_do(axel)
            if axel.conf.verbose and axel.message:
                sys.stdout.write(pyaxel_print(axel))
                sys.stdout.write('\n')
            if axel.size:
                sys.stdout.write('Downloaded [%d%%]\r' % (axel.bytes_done * 100 / axel.size))
            sys.stdout.flush()
            time.sleep(1)

        pyalib.pyaxel_print(axel)
        pyaxel_close(axel)
    except KeyboardInterrupt:
        print
        return 1
    except:
        print 'Unknown error!'
        return 2

    return 0

if __name__ == '__main__':
    sys.exit(main())
