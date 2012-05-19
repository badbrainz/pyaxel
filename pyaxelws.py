#!/usr/bin/env python

import os, sys, time, math, cPickle, json, traceback
import base64, hashlib, struct, array
import threading, urllib2, socket, asyncore, asynchat

from optparse import OptionParser
from urllib import url2pathname

import statemachine
import threadpool

PYAXELWS_PATH = os.path.dirname(os.path.abspath(__file__)) + os.path.sep
PYAXELWS_VERSION = "1.1.0"

(ACK, OK, INVALID, BAD_REQUEST, ERROR, PROC, END, INCOMPLETE, STOPPED,
 UNDEFINED, INITIALIZING) = range(11)

(IDENT, START, STOP, ABORT, QUIT) = range(5)

STD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US; rv:1.9.2) \
        Gecko/20100115 Firefox/3.6",
    "Accept-Charset": "ISO-8859-1,utf-8;q=0.7,*;q=0.7",
    "Accept": "text/xml,application/xml,application/xhtml+xml,text/html;q=0.9,\
        text/plain;q=0.8,image/png,*/*;q=0.5",
    "Accept-Language": "en-us,en;q=0.5",
}

## {{{ http://code.activestate.com/recipes/52215/ (r1)
def backtrace(debug_locals=True):
    tb = sys.exc_info()[2]
    while 1:
        if not tb.tb_next:
            break
        tb = tb.tb_next
    stack = []
    f = tb.tb_frame
    while f:
        stack.append(f)
        f = f.f_back
    stack.reverse()
    traceback.print_exc()
    print "Locals by frame, innermost last"
    for frame in stack:
        print
        print "Frame %s in %s at line %s" % (frame.f_code.co_name,
                                             frame.f_code.co_filename,
                                             frame.f_lineno)
        if debug_locals:
            for key, value in frame.f_locals.items():
                print "\t%20s = " % key,
                try:
                    print value
                except:
                    print "<ERROR WHILE PRINTING VALUE>"
## end of http://code.activestate.com/recipes/52215/ }}}

def get_file_size(url):
    retries = 0
    content_length = 0
    while retries < 5:
        try:
            request = urllib2.Request(url, None, STD_HEADERS)
            data = urllib2.urlopen(request)
            content_length = int(data.info()["Content-Length"])
        except:
            retries += 1
        else:
            break
    return content_length

def get_file_info(url):
    retries = 0
    info = {}
    while retries < 1:
        try:
            request = urllib2.Request(url, None, STD_HEADERS)
            data = urllib2.urlopen(request)
            header = data.info()
            info["type"] = header.get("Content-Type")
            info["size"] = int(header.get("Content-Length"))
            info["name"] = header.get("Content-Disposition")
        except:
            retries += 1
        else:
            break
    return info

def get_state_info(filename):
    state = {}
    try:
        os.stat(filename)
    except OSError, o:
        pass
    else:
        state_fd = file(filename, "r")
        try:
            state = cPickle.load(state_fd)
        except cPickle.UnpicklingError:
            print "State file is corrupted"
        except Exception, e:
            pass
        state_fd.close()
    return state

def save_state_info(fname, state):
    state_fd = file(fname, "wb")
    cPickle.dump(state, state_fd)
    state_fd.close()

def bytes_to_str(num, prefix=True):
    if num == 0: return "0"
    try:
        k = math.log(num, 1024)
        s = "" if not prefix else "bKMGTPEY"[int(k)]
        return "%.2f%s" % (num / (1024.0 ** int(k)), s)
    except TypeError:
        return "0"

def parse_header(line):
    plist = [x.strip() for x in line.split(';')]
    key = plist.pop(0).lower()
    pdict = {}
    for p in plist:
        i = p.find('=')
        if i >= 0:
            name = p[:i].strip().lower()
            value = p[i+1:].strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
                value = value.replace('\\\\', '\\').replace('\\"', '"')
            pdict[name] = value
    return key, pdict

def compact_msg(obj):
    return json.dumps(obj, separators=(',',':'))

def general_configuration(options):
    if not options:
        options = get_state_info(PYAXELWS_PATH + "pyaxel.st")

    conf = Config()
    conf.nworkers = 20
    conf.pool = threadpool.ThreadPool(num_workers=conf.nworkers)
    conf.download_path = options.get("output_dir", PYAXELWS_PATH)
    conf.max_splits = options.get("num_connections", 4)
    conf.max_bandwidth = options.get("max_speed", 0)
    conf.distr_bandwidth = conf.max_bandwidth
    conf.host = options.get("host", "127.0.0.1")
    conf.port_num = options.get("port", 8002)

    urllib2.install_opener(urllib2.build_opener(urllib2.ProxyHandler()))
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


class Connection:
    class DownloadState:
        def __init__(self, progress, length, offset):
            self.done = False
            self.length = length
            self.offset = offset
            self.progress = progress


    def __init__(self, output_fn, url, fsize, splits, pickle={}):
        self.url = url
        self.sleep_timer = 0.0
        self.need_to_quit = False
        self.output_fn = output_fn
        self.elapsed_time = pickle.get("elapsed_time", 1.0)

        chunk_count = splits
        if fsize <= 1024 * 1024: chunk_count = 1

        chunk_count = pickle.get("chunk_count", chunk_count)
        file_size = pickle.get("file_size", fsize)

        chunks = pickle.get("chunks")
        if chunks == None:
            chunks = [(file_size / chunk_count) for i in range(chunk_count)]
            chunks[0] += file_size % chunk_count

        offset = 0
        states = []
        addState = states.append
        state = Connection.DownloadState
        progress = pickle.get("progress", [0 for i in range(chunk_count)])
        for chunk_length, progress in zip(chunks, progress):
            addState(state(progress, chunk_length-progress, offset+progress))
            offset += chunk_length

        self.chunk_count = chunk_count
        self.download_states = states
        self.file_size = file_size
        self.chunks = chunks

        self.start_time = time.time()

    def retrieve(self, state):
        name = threading.currentThread().getName()
        request = urllib2.Request(self.url, None, STD_HEADERS)
        request.add_header("Range", "bytes=%d-%d" % (state.offset,
            state.offset + state.length))

        while 1:
            try:
                data = urllib2.urlopen(request)
            except urllib2.URLError, u:
                pass
            else:
                break

        output = os.open(self.output_fn, os.O_WRONLY) # os.O_BINARY
        os.lseek(output, state.offset, os.SEEK_SET)

        block_size = 1024
        while state.length > 0:
            if self.need_to_quit:
                os.close(output)
                return

            time.sleep(self.sleep_timer)

            if state.length >= block_size:
                fetch_size = block_size
            else:
                fetch_size = state.length

            try:
                data_block = data.read(fetch_size)
                if len(data_block) != fetch_size:
                    print "Connection %s: bad read size" % name
                    os.close(output)
                    return self.retrieve(state)
            except socket.timeout, s:
                print "Connection", name, "timed out with. Retrying..."
                os.close(output)
                return self.retrieve(state)

            os.write(output, data_block)
            state.length -= fetch_size
            state.progress += fetch_size
            state.offset += len(data_block)

        os.close(output)
        state.done = True
        return True

    def is_complete(self):
        states = self.download_states
        return len(self.download_states) >= 0 and all(s.done for s in states)

    def get_snapshot(self):
        states = self.download_states
        snapshot = {
            "elapsed_time": self.elapsed_time,
            "chunk_count": self.chunk_count,
            "file_size": self.file_size,
            "chunks": self.chunks,
            "remaining": [s.length for s in states],
            "progress": [s.progress for s in states]
        }
        return snapshot

    def get_status(self):
        states = self.download_states
        return [y.progress for y in states]

    def update(self):
        end_time = time.time()
        self.elapsed_time += end_time - self.start_time
        self.start_time = end_time

    def sleep(self, timer):
        self.sleep_timer = timer

    def destroy(self):
        self.need_to_quit = True


class ChannelState:
    def __init__(self, channel):
        self.state_fn = None
        self.output_fn = None
        self.output_fp = None
        self.connection = None
        self.inprogress = False
        self.channel = channel
        self.delay = 0.0

        manager = statemachine.State()
        manager.add("initial", IDENT, "listening", self.identAction)
        manager.add("listening", START, "established", self.startAction)
        manager.add("listening", ABORT, "listening", self.abortAction)
        manager.add("listening", QUIT, "listening", self.quitAction)
        manager.add("established", STOP, "listening", self.stopAction)
        manager.add("established", ABORT, "listening", self.abortAction)
        manager.add("established", QUIT, "listening", self.quitAction)
        manager.start("initial")
        self.state_manager = manager

        self.conf = Config()

    def execute(self, data):
        try:
            msg = json.loads(data)
            self.state_manager.execute(msg["cmd"], msg.get("arg"))
        except statemachine.TransitionError, e:
            resp = "'%s' command not recognized <State:%s>" % (e.inp, e.cur)
            self.post_message(compact_msg({"event":BAD_REQUEST,"data":resp}))
        except statemachine.FSMError, e:
            self.post_message(compact_msg({"event":BAD_REQUEST,"data":e}))
        except:
            self.close_connection()
            self.state_manager.start('listening')
            self.post_message(compact_msg({"event":BAD_REQUEST,"data":
                "internal server error"}))

    def identAction(self, state, cmd, args):
        conn_type = args["type"]

        if conn_type == "ECHO":
            self.post_message(compact_msg({"event":OK,"data":args.get("msg")}))
            self.channel.end()
        elif conn_type in ["MGR", "WKR"]:
            msg = {"event":ACK}
            if conn_type == "MGR":
                if "pref" in args:
                    # TODO fix this
                    self.channel.server.save_preferences(args["pref"])
                if "info" in args:
                    info = args["info"]
                    for i in xrange(len(info)):
                        if "version" == info[i]:
                            msg["version"] = PYAXELWS_VERSION
                self.state_manager.start("initial")
            else:
                pass
            self.post_message(compact_msg(msg))

    def startAction(self, state, cmd, args):
        self.post_message(compact_msg({"event":INITIALIZING}))

        time.sleep(1.50)

        url = args.get("url")
        file_info = get_file_info(url)

        if len(file_info) == 0: # TODO fix this
            raise Exception("Couldn't get file info <%s>" % url2pathname(url))

        path = self.conf.download_path

        file_name = args.get("name")
        if file_name == None:
            file_name = file_info.get("name")
            if file_name != None:
                key, params = parse_header(file_name)
                if key == "attachment":
                    file_name = params.get("filename") or params.get("name")
                else:
                    file_name = None
            if file_name == None:
                file_name = url.rsplit("/", 1)[1]
            if not file_name:
                raise

        file_name = url2pathname(file_name)
        file_path = os.path.join(path, file_name)
        file_type = file_info.get("type")
        file_size = file_info.get("size", 0)

        print "Downloading:", file_name
        print "Location:", path
        print "Size:", bytes_to_str(file_size)

        state_fn = file_name + ".st"
        state_info = get_state_info(path + state_fn)

        output_fd = os.open(file_path + ".part", os.O_CREAT | os.O_WRONLY)
        os.close(output_fd)

        #self.delay =  1e6 / (self.channel.getMaxSpeed() * segments)
        connection = Connection(file_path + ".part", url, file_size,
                                self.conf.max_splits, state_info)

        addJob = self.conf.pool.addJob
        callback = connection.retrieve
        request = threadpool.JobRequest
        for s in connection.download_states: addJob(request(callback, [s]))

        snapshot = connection.get_snapshot()

        msg = {
            "event": OK,
            "url": url,
            "name": file_name,
            "type": file_type,
            "size": file_size,
            "chunks": snapshot["chunks"],
            "progress": snapshot["progress"]
        }

        self.output_fn = file_name
        self.output_fp = path
        self.state_fn = state_fn
        self.connection = connection

        self.inprogress = True

        self.post_message(compact_msg(msg))

    def stopAction(self, state, cmd, args):
        print "Stopping:", self.output_fn

        self.inprogress = False
        self.close_connection()

        self.state_fn = None
        self.output_fn = None

        self.post_message(compact_msg({"event":STOPPED}))

    def abortAction(self, state, cmd, args):
        if self.connection != None:
            print "Aborting:", self.output_fn

            self.inprogress = False
            self.close_connection()

            os.remove(self.output_fp + self.state_fn)
            os.remove(self.output_fp + self.output_fn + ".part")

            self.state_fn = None
            self.output_fp = None
            self.output_fn = None

        self.post_message(compact_msg({"event":INCOMPLETE}))

    def quitAction(self, state, cmd, args):
        self.channel.end()

    def update(self):
        if self.inprogress == False: return

        connection = self.connection
        connection.update()

        snapshot = connection.get_snapshot()
        status = connection.get_status()

        downloaded = sum(status)
        avg_speed = downloaded / connection.elapsed_time
        max_speed = self.conf.distr_bandwidth
        if max_speed > 0:
            theta = avg_speed / max_speed
            if theta > 1.05: self.delay += 0.01
            elif theta < 0.95 and self.delay >= 0.01: self.delay -= 0.01
            elif theta < 0.95: self.delay = 0.0
            connection.sleep(self.delay)

        save_state_info(self.output_fp + self.state_fn, snapshot)

        self.channel.send_message(compact_msg({
            "event": PROC,
            "data": {
                "prog": status,
                "rate": bytes_to_str(avg_speed)
            }
        }))

        if connection.is_complete():
            fpath = self.output_fp
            fname = self.output_fn
            sname = self.state_fn
            print "Completed:", fpath + fname

            os.remove(fpath + sname)
            os.rename(fpath + fname + ".part", fpath + fname)

            self.inprogress = False
            self.state_manager.start('listening')
            self.channel.send_message(compact_msg({"event":END}))

    def post_message(self, msg):
        self.channel.send_message(msg)

    def close_connection(self):
        if self.connection != None:
            self.connection.destroy()
            self.connection = None


class ChatChannel(asynchat.async_chat):
    """this implements version 13 of the WebSocket protocol,
    <http://tools.ietf.org/html/rfc6455>
    """

    def __init__(self, sock, handler):
        asynchat.async_chat.__init__(self, sock)
        self.app_data = []
        self.in_buffer = []
        #self.out_buffer = []
        self.handler = handler
        self.handshaken = False
        self.strat = self.handle_request
        self.set_terminator('\x0D\x0A\x0D\x0A')

    def handle_response(self, msg, opcode=0x01):
        header = chr(0x80 | opcode)
        # no fragmentation
        length = len(msg)
        if length <= 0x7D:
            header += chr(length)
        elif length <= 0xFFFF:
            header += struct.pack('>BH', 0x7E, length)
        else:
            header += struct.pack('>BQ', 0x7F, length)
        self.push(header + msg)

    def handle_request(self):
        data = self._get_input()
        crlf = '\x0D\x0A'

        # TODO validate GET
        fields = dict([l.split(": ", 1) for l in data.split(crlf)[1:]])
        required = ("Host", "Upgrade", "Connection", "Sec-WebSocket-Key",
                    "Sec-WebSocket-Version")
        if not all(map(lambda f: f in fields, required)):
            print fields
            self.log_info("malformed request:\n%s" % data, "error")
            self.handle_error()
            return

        sha1 = hashlib.sha1()
        sha1.update(fields["Sec-WebSocket-Key"])
        sha1.update("258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
        challenge = base64.b64encode(sha1.digest())

        self.push("HTTP/1.1 101 Switching Protocols" + crlf)
        self.push("Upgrade: websocket" + crlf)
        self.push("Connection: Upgrade" + crlf)
        self.push("Sec-WebSocket-Accept: %s" % challenge + crlf * 2)

        self.handshaken = True
        self.set_terminator(2)
        self.strat = self.parse_frame_header

    def parse_frame_header(self):
        hi, lo = struct.unpack('BB', self._get_input())

        # no extensions
        if hi & 0x70:
            self.log_info("no extensions support", "error")
            self.handle_error()
            return

        final = hi & 0x80
        opcode = hi & 0x0F
        #mask = lo & 0x80
        length = lo & 0x7F
        control = opcode & 0x0B

        if not control and opcode == 0x02:
            self.log_info("unsupported data format", "error")
            self.handle_error()
            return

        if final:
            if control >= 0x08:
                # TODO handle ping/pong
                if length > 0x7D:
                    self.log_info("bad frame", "error")
                    self.handle_error()
                    return
        else:
            if not control:
                if opcode == 0x01:
                    if self.frame_header:
                        # no interleave
                        self.log_info("unsupported message format", "error")
                        self.handle_error()
                        return

        header = []
        header.append(final)
        header.append(opcode)
        #header.append(mask)
        header.append(length)

        if length < 0x7E:
            self.strat = self.parse_payload_masking_key
            self.set_terminator(4)
        elif length == 0x7E:
            self.strat = self.parse_payload_extended_len
            self.set_terminator(2)
        else:
            self.strat = self.parse_payload_extended_len
            self.set_terminator(8)

        self.frame_header = header

    def parse_payload_extended_len(self):
        length = self._get_input()
        fmt = '>H' if self.frame_header[2] == 0x7E else '>Q'
        self.frame_header[2] = struct.unpack(fmt, length)[0]
        self.strat = self.parse_payload_masking_key
        self.set_terminator(4)

    def parse_payload_masking_key(self):
        key = self._get_input()
        self.frame_header.append(key)
        self.strat = self.parse_payload_data
        self.set_terminator(self.frame_header[2])

    def parse_payload_data(self):
        data = self._get_input()
        bytes = array.array('B', data)
        mask = array.array('B', self.frame_header[3])
        bytes = [chr(b ^ mask[i % 4]) for i, b in enumerate(bytes)]
        self.app_data.extend(bytes)

        if self.frame_header[0]:
            del self.frame_header
            msg = "".join(self.app_data)
            del self.app_data[:]
            self.handler.message_recieved(msg)

        self.set_terminator(2)
        self.strat = self.parse_frame_header

    def collect_incoming_data(self, data):
        self.in_buffer.append(data)

    def found_terminator(self):
        self.strat()

    def handle_close(self):
        self.close() # just to be safe
        self.handler.socket_closed()
        self._cleanup()

    def handle_error(self):
        self.handler.socket_error()

    def disconnect(self, status, reason):
        msg = struct.pack(">H%ds" % len(reason), status, reason)
        self.handle_response(msg, 0x08)
        self.close()
        self._cleanup()

    def _cleanup(self):
        del self.app_data[:]
        del self.in_buffer[:]
        try:
            del self.frame_header
        except AttributeError:
            pass
        self.handshaken = False

    def _get_input(self):
        data = "".join(self.in_buffer)
        del self.in_buffer[:]
        return data


class ChannelDispatcher():
    def __init__(self, sock, channel):
        self.server = channel
        self.state = ChannelState(self)
        self.channel = ChatChannel(sock, self)

    def update(self):
        if self.channel.handshaken:
           self.state.update()

    def send_message(self, msg):
        self.channel.handle_response(msg)

    def message_recieved(self, msg):
        self.state.execute(msg)

    def socket_closed(self):
        self.state.close_connection()
        self.server.remove_client(self)

    def socket_error(self):
        try:
            self.socket_closed()
        except:
            pass

    def end(self, status=1000, reason=""):
        self.channel.disconnect(status, reason)


class WebSocketChannel(asyncore.dispatcher):
    def __init__(self, conf):
        asyncore.dispatcher.__init__(self)
        self.dispatchers = []
        self.conf = conf

    def handle_accept(self):
        try:
            conn, addr = self.accept()
            if addr == None:
                return
        except socket.error, err:
            #if err.args[0] != errno.ECONNABORTED:
            #    raise
            pass
        else:
            self.log("incoming connection from %s" % repr(addr))
            self.dispatchers.append(ChannelDispatcher(conn, self))
            self.adjust_bandwith()

    def refresh(self):
        for c in self.dispatchers: c.update()
        for _ in self.conf.pool.iterProcessedJobs(timeout=0): pass

    def save_preferences(self, prefs):
        state_info = {
            "bandwidth": prefs.get("bw"),
            "splits": prefs.get("splits"),
            "path": prefs.get("dlpath")
        }
        save_state_info(PYAXELWS_PATH + "pyaxel.st", state_info)
        self.set_max_bandwidth(state_info["bandwidth"])
        self.set_download_path(state_info["path"])
        self.set_max_splits(state_info["splits"])

    def set_max_bandwidth(self, bandwidth):
        self.conf.max_bandwidth = bandwidth
        self.adjust_bandwith()

    def set_download_path(self, path):
        if os.path.exists(path):
            self.conf.download_path = path

    def set_max_splits(self, count):
        self.conf.max_splits = count

    def adjust_bandwith(self):
        bandwidth = self.conf.max_bandwidth * 1024
        try:
            self.conf.distr_bandwidth = int(bandwidth / len(self.dispatchers))
        except:
            self.conf.distr_bandwidth = int(bandwidth)

    def remove_client(self, client):
        self.dispatchers.remove(client)
        self.adjust_bandwith()

    def start_service(self, endpoint=("", 8118), backlog=5):
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind(endpoint)
        self.listen(backlog)
        self.log("websocket server waiting on %s ..." % repr(endpoint))
        loop = asyncore.loop
        refresh = self.refresh
        flush = sys.stdout.flush
        while asyncore.socket_map:
            loop(timeout=1, count=1)
            refresh()
            flush()

    def stop_service(self):
        sys.stdout.write('\n')
        self.log("stopping service")
        for c in self.dispatchers: c.end(status=1001, reason="server shutdown")
        asyncore.socket_map.clear()
        #asyncore.close_all()


def run(options=None):
    if sys.platform.startswith('win'):
        print 'aborting: unsupported platform:', sys.platform
        return

    major, minor, micro, release, serial = sys.version_info
    if (major, minor, micro) < (2, 6, 0):
        print 'aborting: unsupported python version: %s.%s.%s' % \
            (major, minor, micro)
        return

    conf = general_configuration(options)
    endpoint = (conf.host, conf.port_num)
    port = WebSocketChannel(conf)

    try:
        port.start_service(endpoint)
    except socket.error, e:
#        (errno, strerror) = e
#        print "error:", endpoint, strerror
        port.stop_service()
        return
    except:
        pass

    pool = conf.pool
    pool.cancelAllJobs()
    pool.dismissWorkers(conf.nworkers)
    port.stop_service()
    sys.stdout.flush()


if __name__ == "__main__":
    usage="Usage: %prog [options]"
    description="Note: options will be overridden by those that exist in the \
        (pyaxel.st) file."
    parser = OptionParser(usage=usage, description=description)
    parser.add_option("-s", "--max-speed", dest="max_speed",
                      type="int", default=0,
                      help="Specifies maximum speed (Kbytes per second)."
                      " Useful if you don't want the program to suck up"
                      " all of your bandwidth",
                      metavar="SPEED")
    parser.add_option("-n", "--num-connections", dest="num_connections",
                      type="int", default=4,
                      help="You can specify an alternative number of"
                      " connections per download here.",
                      metavar="NUM")
    parser.add_option("-p", "--port", dest="port",
                      type="int", default=8002,
                      help="You can specify the port to listen for"
                      " connections here. Default port number is 8002.",
                      metavar="PORT")
    parser.add_option("-d", "--directory", dest="output_dir",
                      type="str", default=PYAXELWS_PATH,
                      help="By default, files are saved to current working"
                      " directory. Use this option to change where the saved"
                      "files should go.",
                      metavar="DIR")

    (options, args) = parser.parse_args()

    run(options.__dict__)
