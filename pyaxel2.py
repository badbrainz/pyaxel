import pdb
import time
import threading

import threadpool
import pyaxel as pyaxellib

setup_threadpool = threadpool.ThreadPool(4)


class fakefile_c:
    def __init__(self, outfd):
        self.outfd = outfd
        self.lock = threading.Lock()
        self.offset = None

    def write(self, data):
        self.outfd.seek(self.offset)
        self.outfd.write(data)
        self.lock.release()

    def seek(self, offset):
        self.lock.acquire()
        self.offset = offset

    def close(self):
        self.outfd.close()


def pyaxel_open(pyaxel):
    if pyaxel.outfd == -1:
        if not pyaxellib.pyaxel_open(pyaxel):
            return 0

    pyaxel.outfd = fakefile_c(pyaxel.outfd)

    for conn in pyaxel.conn:
        conn.bytes_read = 0
#        conn.start_byte = conn.current_byte

    return 1

def pyaxel_start(pyaxel):
    # TODO assign mirrors
    for i, conn in enumerate(pyaxel.conn):
        pyaxellib.conn_set(conn, pyaxel.url[0])
        conn.conf = pyaxel.conf
        if i:
            conn.supported = 1

    pyaxellib.pyaxel_message(pyaxel, 'Starting download.')

    for conn in pyaxel.conn:
        if conn.current_byte <= conn.last_byte:
            conn.state = 1
            setup_threadpool.addJob(threadpool.JobRequest(pyaxellib.setup_thread, [conn]))
            conn.last_transfer = time.time()

    pyaxel.start_time = time.time()
    pyaxel.ready = 0

def pyaxel_do(pyaxel):
    # TODO tokenbucket
    pyaxel.outfd.lock.acquire()
    for conn in pyaxel.conn:
        pyaxel.bytes_done += conn.bytes_read
        conn.bytes_read = 0
#    pyaxel.bytes_done += sum([conn.bytes_read for conn in pyaxel.conn])
    if time.time() > pyaxel.next_state:
        pyaxellib.pyaxel_save(pyaxel)
        pyaxel.next_state = time.time() + pyaxel.conf.save_state_interval
    pyaxel.outfd.lock.release()
#    print pyaxel.bytes_done , pyaxel.size
    if pyaxel.bytes_done == pyaxel.size:
        pyaxellib.pyaxel_message(pyaxel, 'Download complete.')
        pyaxel.ready = 1

def pyaxel_run(pyaxel):
    for i, conn in enumerate(pyaxel.conn):
        setup_threadpool.addJob(threadpool.JobRequest(download_thread, [pyaxel, conn]))

def pyaxel_join(pyaxel):
    return

def download_thread(pyaxel, conn):
    while not pyaxel.ready:
        if conn.enabled == -1:
            time.sleep(1)

        if not conn.enabled:
            break

        if conn.enabled == 1:
            try:
                conn.last_transfer = time.time()
                fetch_size = min(conn.last_byte + 1 - conn.current_byte, pyaxel.conf.buffer_size)
                data = conn.http.fd.read(fetch_size)
                size = len(data)
                if size == 0:
                    if conn.current_byte < conn.last_byte:# and pyaxel.size != INT_MAX:
                        pyaxellib.pyaxel_message(pyaxel, 'Connection %d unexpectedly closed.' % pyaxel.conn.index(conn))
                    else:
                        pyaxellib.pyaxel_message(pyaxel, 'Connection %d finished.' % pyaxel.conn.index(conn))
#                    if not pyaxel.conn[0].supported:
#                        pyaxel.ready = 1
                    conn.enabled = 0
                    pyaxellib.conn_disconnect(conn)
                    break
                if size != fetch_size:
                    pyaxellib.pyaxel_message(pyaxel, 'Error on connection %d.' % pyaxel.conn.index(conn))
                    conn.enabled = -1
                    pyaxellib.conn_disconnect(conn)
                    continue
                try:
                    pyaxel.outfd.seek(conn.current_byte)
                    pyaxel.outfd.write(data)
                except IOError:
                    pyaxellib.pyaxel_message(pyaxel, 'Write error!')
                    conn.enabled = 0
                    pyaxellib.conn_disconnect(conn)
#                    pyaxel.ready = -1
                    return
                conn.current_byte += size
                conn.bytes_read += size
            except Exception, e:
                pyaxellib.pyaxel_message(pyaxel, 'Unexpected error on connection %d: %s' % (pyaxel.conn.index(conn), e))
                conn.enabled = -1
                pyaxellib.conn_disconnect(conn)
                continue

        if conn.enabled == -1 and conn.current_byte < conn.last_byte:
            if conn.state == 0:
                pyaxellib.pyaxel_message(pyaxel, 'Restarting connection %d.' % pyaxel.conn.index(conn))
                # TODO try another URL
                pyaxellib.conn_set(conn, pyaxel.url[0])
                conn.state = 1
                setup_threadpool.addJob(threadpool.JobRequest(pyaxellib.setup_thread, [conn]))
                conn.last_transfer = time.time()
            elif conn.state == 1:
                if time.time() > conn.last_transfer + pyaxel.conf.reconnect_delay:
                    pyaxellib.conn_disconnect(conn)
                    conn.state = 0
