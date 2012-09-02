#!/usr/bin/env python

import os, sys, time, math, json, traceback
import base64, hashlib, struct, array, Queue
import threading, urllib, urllib2, httplib
import socket, asyncore, asynchat
import contextlib

from optparse import OptionParser

import pyaxel
import threadpool
import debug
import websocket
import statemachine

(ACK, OK, INVALID, BAD_REQUEST, ERROR, PROC, END, INCOMPLETE, STOPPED,
 UNDEFINED, INITIALIZING) = range(11)

(IDENT, START, STOP, ABORT, QUIT) = range(5)

STD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US; rv:1.9.2) \
        Gecko/20100115 Firefox/3.6",
    "Accept-Charset": "ISO-8859-1,utf-8;q=0.7,*;q=0.7",
    "Accept-Language": "ISO-8859-1,utf-8;q=0.7,*;q=0.3",
    "Accept-Encoding": "gzip,deflate,sdch"
}

def bytes_to_str(num, prefix=True):
    if num == 0: return "0"
    try:
        k = math.log(num, 1024)
        s = "" if not prefix else "bKMGTPEY"[int(k)]
        return "%.2f%s" % (num / (1024.0 ** int(k)), s)
    except TypeError:
        return "0"

def compact_msg(obj):
    return json.dumps(obj, separators=(',',':'))

def adjust_bandwidth(num_distributions):
    conf = Config()
    bandwidth = conf.max_speed * 1024
    try:
        conf.distr_bandwidth = int(bandwidth / num_distributions)
    except:
        conf.distr_bandwidth = int(bandwidth)

def general_configuration(options={}):
    pickle = pyaxel.get_config()
    options = dict(options.items() + pickle.items())

    conf = Config()
#    conf.nworkers = 20
#    conf.pool = threadpool.ThreadPool(num_workers=conf.nworkers)
    conf.download_path = options.get("download_path") or pyaxel.PYAXELWS_PATH
    conf.num_connections = options.get("num_connections") or 1
    conf.max_speed = options.get("max_speed") or 0
    conf.distr_bandwidth = conf.max_speed * 1024
    conf.host = options.get("host") or pyaxel.PYAXELWS_HOST
    conf.port = options.get("port") or pyaxel.PYAXELWS_PORT

    if options.get("verbose"):
        httplib.HTTPConnection.debuglevel = 1

#    urllib2.install_opener(urllib2.build_opener(urllib2.ProxyHandler()))
    urllib2.install_opener(urllib2.build_opener(urllib2.HTTPCookieProcessor()))

    socket.setdefaulttimeout(20)

    return conf


class Config(object):
    def __new__(cls, *args, **kw):
        if "_shared_state" not in cls.__dict__:
            cls._shared_state = {}
        obj = object.__new__(cls)
        obj.__dict__ = cls._shared_state
        return obj


class TokenBucket(object):
    def __init__(self, tokens, fill_rate):
        self.capacity = float(tokens)
        self.credits = float(tokens)
        self.fill_rate = float(fill_rate)
        self.timestamp = time.time()

    def consume(self, tokens):
        credits = self.tokens
        tokens = max(tokens, credits)
        expected_time = (tokens - credits) / self.fill_rate
        if expected_time <= 0:
            self.credits -= tokens
        return max(0, expected_time)

    @property
    def tokens(self):
        if self.credits < self.capacity:
            now = time.time()
            delta = self.fill_rate * (now - self.timestamp)
            self.credits = min(self.capacity, self.credits + delta)
            self.timestamp = now
        return self.credits


class FileWriter(threading.Thread):
    def __init__(self, filename):
        threading.Thread.__init__(self)
        self.daemon = True
        self.chunks = Queue.Queue()
        self.file_name = filename
        self.dismissed = False
        self.rate = 0
        self.max_rate = 0
        self.start()

    def add_chunk(self, chunk):
        if not self.dismissed:
            if not chunk:
                chunk = (0, None)
            self.chunks.put(chunk)

    def run(self):
        if not self.dismissed:
            with open(self.file_name, "wb") as output:
                now = time.time
                while not self.dismissed:
                    offset, bytes = self.chunks.get()# put None and break
                    self.chunks.task_done()
                    if bytes:
                        output.seek(offset)
                        output.write(bytes)
#                        print 'wrote', len(bytes), 'offset', offset
#                    count = 0
#                    start = now()
#                    end = now() + 1
#                    while end - now() > 0:
#                        offset, bytes = self.chunks.get()
#                        output.seek(offset)
#                        output.write(bytes)
#                        count += 1
#                        self.chunks.task_done()
#                    self.rate = count / (now() - start)
#                    self.max_rate = max(self.rate, self.max_rate)

    def killme(self):
        self.dismissed = True
        with self.chunks.mutex:
            self.chunks.queue.clear()


class ConnectionReadError(Exception):
    pass


class ChunkInfo:
    def __init__(self, begin, offset, length):
        self.begin = begin
        self.offset = offset
        self.length = length

    def write(self, bytes):
        self.offset = self.offset + len(bytes)

    @property
    def completed(self):
        return self.offset - self.begin

    @property
    def remaining(self):
        return self.begin + self.length - self.offset


buffer_size = 1024 * 10
class Chunk:
    def __init__(self):
        self.delay = 0.0
        self.quit = False

    def __call__(self, partition, reader):
        url, info, fdo, block_size = partition
        if info.length > 0:
            start = info.offset
            end = info.begin + info.length
            request = urllib2.Request(url, headers=STD_HEADERS)
            request.add_header("Range", "bytes=%d-%d" % (start, end))
            with contextlib.closing(urllib2.urlopen(request)) as fdi:
                in_buffer = ''
                while not self.quit:
                    fetch_size = min(end - info.offset, block_size)
                    data = fdi.read(fetch_size)
                    if len(data) == 0:
                        break
                    if len(data) != fetch_size:
                        raise ConnectionReadError
                    info.write(data)
                    in_buffer += data
                    if info.offset == end:
                        fdo.add_chunk((start, in_buffer))
                        break
                    while len(in_buffer) >= buffer_size:
                        fdo.add_chunk((start, in_buffer[:buffer_size]))
                        in_buffer = in_buffer[buffer_size:]
                        start += buffer_size
                    #time.sleep(self.delay)
        return reader


class Connection:
    def __init__(self, fd):
#        self.sleep_time = 0.0
        self.quit = False
        self.chunks = []
        self.buckets = []
        for i in range(4, 0, -1):
            bucket = TokenBucket(100 * 1024, 25 * 1024)
            self.buckets.append(bucket)
        self.thread_pool = threadpool.ThreadPool(num_workers=0)
        self.writer = fd

    def add_job(self, job):
        chunk = Chunk()
        self.chunks.append(chunk)
        self.thread_pool.addJob(threadpool.JobRequest(chunk, [job, chunk]))
        self.thread_pool.addWorkers(1)

    def tick(self):
#        for chunk, bucket in zip(self.chunks, self.buckets):
#            bucket.capacity = self.writer.max_rate * 1024
#            bucket.credits = max(1024, self.writer.rate * 1024)
#            #chunk.delay = bucket.consume(chunk.avg_speed)
#            chunk.delay = bucket.consume(self.writer.rate)

        thread_pool = self.thread_pool
        for job in thread_pool.iterProcessedJobs(0):
            try:
                chunk = job.result()
                self.chunks.remove(chunk)
            except ConnectionReadError:
                print 're-assigning job', job.key
                thread_pool.addJob(job)
            except urllib2.URLError:
                print 'fucked url', job.key
                self.destroy()
            except Exception, e:
#                debug.backtrace()
                print e
#                print 're-assigning job', job.key
                debug.backtrace()
#                thread_pool.addJob(job)

    def sleep(self, t):
        self.sleep_time = t

    def destroy(self):
        self.thread_pool.dismissAllWorkers()
        self.thread_pool.cancelAllJobs()
        for chunk in self.chunks:
            chunk.quit = True


class ChannelDispatcher:
    def __init__(self, sock, server):
        self.server = server
        self.channel = websocket.ChatChannel(sock, self)
        self.state_fn = None
        self.output_fn = None
        self.output_fp = None
        self.connection = None
        self.credits = 200 * 1024
        self.conf = Config()
        self.state_manager = statemachine.StateMachine()
        manager = self.state_manager
        manager.add("initial", IDENT, "listening", self.identAction)
        manager.add("listening", START, "established", self.startAction)
        manager.add("listening", ABORT, "listening", self.abort_action)
        manager.add("listening", QUIT, "listening", self.quitAction)
        manager.add("established", STOP, "listening", self.stop_action)
        manager.add("established", ABORT, "listening", self.abort_action)
        manager.add("established", QUIT, "listening", self.quitAction)
        manager.start("initial")

    def execute(self, data):
        try:
            msg = json.loads(data)
            self.state_manager.execute(msg["cmd"], msg.get("arg"))
        except (IOError, statemachine.TransitionError), e:
            debug.backtrace()
            self.close_connection()
            self.post_message({"event":BAD_REQUEST, "data":str(e)})
        except:
            debug.backtrace()
            self.close_connection()
            self.post_message({"event":BAD_REQUEST,
                "data":"internal server error"})

    def identAction(self, s, cmd, args):
        conn_type = args["type"]
        if conn_type == "ECHO":
            self.post_message({"event":OK,"data":args.get("msg")})
            self.end()
        elif conn_type in ["MGR", "WKR"]:
            msg = {"event":ACK}
            if conn_type == "MGR":
                if "pref" in args:
                    # TODO fix this
                    pref = args["pref"]
                    state = {
                        "max_speed": pref.get("speed", 0),
                        "num_connections": pref.get("splits", 1),
                        "download_path": pref.get("dlpath", pyaxel.PYAXELWS_DEST)
                    }
                    pyaxel.set_config(state)
                    conf = Config()
                    if os.path.exists(state["download_path"]):
                        conf.download_path = state["download_path"]
                    conf.max_speed = state["max_speed"]
                    conf.num_connections = state["num_connections"]
                    adjust_bandwidth(self.server.get_client_count() - 1)
                if "info" in args:
                    info = args["info"]
                    for i in xrange(len(info)):
                        if "version" == info[i]:
                            msg["version"] = pyaxel.PYAXELWS_VERSION
                self.state_manager.start("initial")
            else:
                pass
            self.post_message(msg)

    def startAction(self, s, cmd, args):
        self.post_message({"event":INITIALIZING})
        adjust_bandwidth(self.server.get_client_count())
        url = args.get("url")
#        info = get_file_info(url)
        name = args.get("name")
        path = self.conf.download_path
        file_url, info = pyaxel.follow_redirect(url)
#        file_url = info.get("location")
        file_type = info.get("content-type")
        file_size = int(info.get("content-length") or 0)
        if not file_size:
            raise Exception
        if not name:
            name = info.get("content-disposition")
            if name:
                key, params = pyaxel.parse_header_field(name)
                if key == "attachment":
                    name = params.get("filename") or params.get("name")
            if not name:
                name = url.rsplit("/", 1)[1]
            if not name:
                raise Exception
        file_name = urllib.url2pathname(name).replace('/', '_')
        file_path = os.path.join(path, file_name)
        state_fn = file_name + ".st"
        state_part = file_path + ".part"
        state_info = pyaxel.get_state_info(path + state_fn)
        output_fd = os.open(state_part, os.O_CREAT | os.O_WRONLY)
        # write zero at the end
        os.close(output_fd)
        chunk_count = self.conf.num_connections
        if file_size <= 1024 * 1024:
            chunk_count = 1
        chunk_count = state_info.get("chunk_count", chunk_count)
        chunks = state_info.get("chunks")
        if not chunks:
            chunks = [file_size / chunk_count] * chunk_count
            chunks[0] += file_size % chunk_count
        offset = 0
        states = []
        progress = state_info.get("progress", [0] * chunk_count)
        for length, completed in zip(chunks, progress):
            states.append(ChunkInfo(offset, offset + completed, length))
            offset += length
        #self.delay =  1e6 / (self.getMaxSpeed() * segments)
        fd = FileWriter(state_part)
        connection = Connection(fd)
        for state in states:
            connection.add_job((file_url, state, fd, 1024))
#        connection.start()
        msg = {
            "event": OK,
            "url": url,
            "name": file_name,
            "type": file_type,
            "size": file_size,
            "chunks": chunks,
            "progress": progress
        }
        self.output_fn = file_name
        self.output_fp = path
        self.state_fn = state_fn
        self.connection = connection
        self.fd = fd
        self.download_states = states
        self.start_time = time.time()
        self.post_message(msg)
        print "downloading:", file_url
        print "location:", file_path
        print "size:", file_size

    def stop_action(self, s, cmd, args):
        print "stopping:", self.output_fn
        self.close_connection()
        self.state_fn = None
        self.output_fn = None
        self.post_message({"event":STOPPED})

    def abort_action(self, transition, cmd, args):
        # aborting active job
        if transition == "established":
            print "aborting:", self.output_fn
            self.close_connection()
            os.remove(self.output_fp + self.state_fn)
            os.remove(self.output_fp + self.output_fn + ".part")
            self.state_fn = None
            self.output_fp = None
            self.output_fn = None
        self.post_message({"event":INCOMPLETE})

    def quitAction(self, s, cmd, args):
        self.end()

    def tick(self, tick):
        if not self.connection:
            return
        self.connection.tick()
        snapshot = self.get_snapshot()
        progress = snapshot["progress"]
        # TODO improve this
        elapsed = tick - self.start_time
        avg_speed = sum(progress) / elapsed
#        max_speed = self.conf.distr_bandwidth
#        if max_speed > 0:
#            bitrate = max_speed / 2
#            if self.credits < max_speed:
#                delta = bitrate * elapsed
#                self.credits = min(max_speed, self.credits + delta)
#            credits = self.credits
#            tokens = max(avg_speed, credits)
#            expected_time = (tokens - credits) / bitrate
#            if expected_time <= 0:
#                self.credits -= tokens
#            delay = max(0, expected_time)
#            self.connection.sleep(delay)
        self.post_message({"event": PROC,
                           "progress": progress,
                           "rate": bytes_to_str(avg_speed)})
        if all(not r for r in snapshot["remaining"]):
            print "completed:", self.output_fp + self.output_fn
            self.close_connection()
            fpath = self.output_fp
            fname = self.output_fn
            if sum(snapshot["remaining"]) == 0:
                os.remove(fpath + self.state_fn)
                os.rename(fpath + fname + ".part", fpath + fname)
                self.post_message({"event":END})
            else:
                self.post_message({"event":INCOMPLETE})
            self.state_manager.start('listening')

    def post_message(self, msg):
        self.send_message(compact_msg(msg))

    def get_snapshot(self):
        snapshot = {"remaining":[], "progress":[]}
        for state in self.download_states:
            remaining = state.remaining
            snapshot["remaining"].append(remaining)
            snapshot["progress"].append(state.length - remaining)
        return snapshot

    def close_connection(self):
        if self.connection:
            snapshot = self.get_snapshot()
            pyaxel.save_state_info(self.output_fp + self.state_fn, snapshot)
            self.connection.destroy()
            self.connection = None
            self.fd.killme()
        adjust_bandwidth(self.server.get_client_count() - 1)

    def send_message(self, msg):
        self.channel.handle_response(msg)

    def message_recieved(self, msg):
        self.execute(msg)

    def socket_closed(self):
        self.close_connection()
        self.server.remove_client(self)

    def socket_error(self):
        try:
            self.socket_closed()
        except:
            pass

    def end(self, status=1000, reason=""):
        self.channel.disconnect(status, reason)

    def update(self, tick):
        if self.channel.handshaken:
           self.tick(tick)


class WebSocketChannel(asyncore.dispatcher):
    def __init__(self):
        asyncore.dispatcher.__init__(self)
        self.dispatchers = []

    def writable(self):
        return False

    def handle_accept(self):
        try:
            conn, addr = self.accept()
            if addr is not None:
                self.log("incoming connection from %s" % repr(addr))
                self.dispatchers.append(ChannelDispatcher(conn, self))
        except socket.error, err:
            self.log_info('error: %s' % err, 'error')

    def start_service(self, endpoint, backlog=5):
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind(endpoint)
        self.listen(backlog)
        self.log("websocket server waiting on %s ..." % repr(endpoint))
        while asyncore.socket_map:
            asyncore.loop(use_poll=True, timeout=1, count=1)
            self.tick()
            sys.stdout.flush()

    def stop_service(self):
        sys.stdout.write('\n')
        self.log("stopping service")
        self.close()
        for c in self.dispatchers:
            c.end(status=1001, reason="server shutdown")

    def get_client_count(self):
        return len(self.dispatchers)

    def remove_client(self, client):
        self.dispatchers.remove(client)

    def tick(self):
        tick = time.time()
        for d in self.dispatchers:
            d.update(tick)


def run(options={}):
    if sys.platform.startswith('win'):
        print 'aborting: unsupported platform:', sys.platform
        return
    major, minor, micro, release, serial = sys.version_info
    if (major, minor, micro) < (2, 6, 0):
        print 'aborting: unsupported python version: %s.%s.%s' % \
            (major, minor, micro)
        return
    port = WebSocketChannel()
    try:
        conf = general_configuration(options)
        port.start_service((conf.host, conf.port))
    except socket.error:
        port.stop_service()
        return
    except KeyboardInterrupt:
        pass
    except:
        debug.backtrace()
    port.stop_service()
    sys.stdout.flush()


if __name__ == "__main__":
    usage="Usage: %prog [options]"
    description="Note: options will be overridden by those that exist in the" \
        " %s file." % pyaxel.PYAXELWS_SETTINGS
    parser = OptionParser(usage=usage, description=description)
    parser.add_option("-s", "--max-speed", dest="max_speed",
                      type="int", default=0,
                      help="Specifies maximum speed (Kbytes per second)."
                      " Useful if you don't want the program to suck up"
                      " all of your bandwidth",
                      metavar="SPEED")
    parser.add_option("-n", "--num-connections", dest="num_connections",
                      type="int", default=1,
                      help="You can specify the number of connections per"
                      " download here. The default is %d." % 1,
                      metavar="NUM")
    parser.add_option("-a", "--host", dest="host",
                      type="string", default=pyaxel.PYAXELWS_HOST,
                      help="You can specify the address of the network"
                      " interface here. The default is %s" % pyaxel.PYAXELWS_HOST,
                      metavar="HOST")
    parser.add_option("-p", "--port", dest="port",
                      type="int", default=pyaxel.PYAXELWS_PORT,
                      help="You can specify the port to listen for"
                      " connections here. The default is %d." % pyaxel.PYAXELWS_PORT,
                      metavar="PORT")
    parser.add_option("-d", "--directory", dest="download_path",
                      type="string", default=pyaxel.PYAXELWS_DEST,
                      help="Use this option to change where the files are"
                      " saved. By default, files are saved in the current"
                      " working directory.",
                      metavar="DIR")
    parser.add_option("-v", "--verbose", dest="verbose", action="store_true")
    (options, args) = parser.parse_args()
    run(options.__dict__)
