#!/usr/bin/env python

import os, math, cPickle, json, time, traceback, base64, hashlib, struct, array
import threading, urllib2, socket, asyncore, sys

from ThreadPool import ThreadPool, JobRequest
from optparse import OptionParser
from urllib import url2pathname

import StateManager
import WebSocket

pyapath = os.path.dirname(os.path.abspath(__file__)) + os.path.sep

(IDENT, START, STOP, ABORT, QUIT) = range(5)

(ACK, OK, INVALID, BAD_REQUEST, ERROR, PROC, END, INCOMPLETE, STOPPED, UNDEFINED, INITIALIZING) = range(11)

std_headers = {
    "User-Agent": "Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US; rv:1.9.2) Gecko/20100115 Firefox/3.6",
    "Accept-Charset": "ISO-8859-1,utf-8;q=0.7,*;q=0.7",
    "Accept": "text/xml,application/xml,application/xhtml+xml,text/html;q=0.9,text/plain;q=0.8,image/png,*/*;q=0.5",
    "Accept-Language": "en-us,en;q=0.5",
}

## {{{ http://code.activestate.com/recipes/52215/ (r1)
def backtrace():
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
            request = urllib2.Request(url, None, std_headers)
            data = urllib2.urlopen(request)
            content_length = int(data.info()['Content-Length'])
        except:
            retries += 1
        else:
            break
    return content_length

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

def get_file_info(url):
    retries = 0
    info = {}
    while retries < 1:
        try:
            request = urllib2.Request(url, None, std_headers)
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
        return "%.2f%s" % (num / (1024.0 ** int(k)), "" if not prefix else "bKMGTPEY"[int(k)])
    except TypeError:
        return "0"

def compact_msg(obj):
    return json.dumps(obj, separators=(',',':'))

def general_configuration(options):
    urllib2.install_opener(urllib2.build_opener(urllib2.ProxyHandler()))
    urllib2.install_opener(urllib2.build_opener(urllib2.HTTPCookieProcessor()))
    socket.setdefaulttimeout(20)
    config = Config()
    config.nworkers = 20
    config.pool = ThreadPool(num_workers=config.nworkers)
    config.download_path = options.get("output_dir", pyapath)
    config.max_splits = options.get("num_connections", 4)
    config.max_bandwidth = options.get("max_speed", 0)
    config.allotted_bandwidth = config.max_bandwidth
    config.host = options.get("host", "127.0.0.1")
    config.port = options.get("port", 8002)

class Config(object):
    def __new__(cls, *args, **kw):
        if '_shared_state' not in cls.__dict__:
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

    def __init__(self, output_fn, url, fsize, pickle={}):
        self.url = url
        self.sleep_timer = 0.0
        self.need_to_quit = False
        self.output_fn = output_fn
        self.elapsed_time = pickle.get("elapsed_time", 1.0)

        config = Config()

        chunk_count = config.max_splits
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
        addJob = config.pool.addJob
        callback = self.retrieve
        for s in states: addJob(JobRequest(callback, [s]))

    def retrieve(self, state):
        name = threading.currentThread().getName()
        request = urllib2.Request(self.url, None, std_headers)
        request.add_header('Range', 'bytes=%d-%d' % (state.offset, state.offset + state.length))

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
                    print "Connection %s: len(data_block) != fetch_size." % name
                    os.close(output)
                    return self.retrieve(state)
            except socket.timeout, s:
                print "Connection", name, "timed out with", s, ". Retrying..."
                os.close(output)
                return self.retrieve(state)

            os.write(output, data_block)
            state.length -= fetch_size
            state.progress += fetch_size
            state.offset += len(data_block)

        os.close(output)
        state.done = True
        return True

    def isComplete(self):
        states = self.download_states
        return len(self.download_states) >= 0 and all(s.done for s in states)

    def getSnapshot(self):
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

    def getStatus(self):
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

class ClientSessionState:
    def __init__(self, session):
        self.state_fn = None
        self.output_fn = None
        self.output_fp = None
        self.connection = None
        self.inprogress = False
        self.session = session
        self.delay = 0.0

        manager = StateManager.StateManager()
        manager.add("identity", IDENT, "listening", self.identAction)
        manager.add("listening", START, "downloading", self.startAction)
        manager.add("downloading", ABORT, "listening", self.abortAction)
        manager.add("downloading", STOP, "listening", self.stopAction)
        manager.add("downloading", QUIT, "listening", self.quitAction)
        manager.add("listening", ABORT, "listening", self.abortAction)
        manager.add("listening", QUIT, "listening", self.quitAction)
        manager.start("identity")
        self.state_manager = manager

        self.config = Config()

    def execute(self, data):
        try:
            msg = json.loads(data)
            self.state_manager.execute(msg["cmd"], msg["arg"])

        except StateManager.TransitionError, e:
            resp = "'%s' command not recognized <State:%s>" % (e.inp, e.cur)
            self.postMessage(compact_msg({"event":BAD_REQUEST,"data":resp}))

        except StateManager.FSMError, e:
            self.postMessage(compact_msg({"event":BAD_REQUEST,"data":e}))

        except Exception, e:
            resp = "Internal server error (%s)" % e
            self.postMessage(compact_msg({"event":BAD_REQUEST,"data":resp}))
            backtrace()

    def noneAction(self, state, cmd, args):
        pass

    def identAction(self, state, cmd, args):
        conn_type = args.get("type")

        if conn_type == "ECHO":
            self.postMessage(compact_msg({"event":OK,"data":args.get("msg")}))
            self.session.end()
        elif conn_type in ["MGR","WKR"]:
            if conn_type == "MGR":
                self.session.server.savePreferences(args.get("bw"), args.get("dlpath"), args.get("splits"))
            self.postMessage(compact_msg({"event":ACK}))

    def startAction(self, state, cmd, args):
        self.postMessage(compact_msg({"event":INITIALIZING}))

        time.sleep(1.50)

        url = args.get("url")
        file_info = get_file_info(url)

        if len(file_info) == 0: # TODO fix this
            raise Exception("Couldn't retrieve file info <%s>" % url2pathname(url))

        path = self.config.download_path

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

        #self.delay =  1e6 / (self.session.getMaxSpeed() * segments)
        connection = Connection(file_path + ".part", url, file_size, state_info)

        snapshot = connection.getSnapshot()

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

        self.postMessage(compact_msg(msg))

    def stopAction(self, state, cmd, args):
        print "Stopping:", self.output_fn

        self.inprogress = False

        self.closeConnection()
        self.connection = None

        self.state_fn = None
        self.output_fn = None

        self.postMessage(compact_msg({"event":STOPPED}))

    def abortAction(self, state, cmd, args):
        if self.connection != None:
            print "Aborting:", self.output_fn

            self.inprogress = False

            self.closeConnection()
            self.connection = None

            os.remove(self.output_fp + self.state_fn)
            os.remove(self.output_fp + self.output_fn + ".part")

            self.state_fn = None
            self.output_fp = None
            self.output_fn = None

        self.postMessage(compact_msg({"event":INCOMPLETE}))

    def quitAction(self, state, cmd, args):
        self.session.end()

    def update(self):
        if self.inprogress == False: return

        connection = self.connection
        connection.update()

        snapshot = connection.getSnapshot()
        status = connection.getStatus()

        downloaded = sum(status)
        avg_speed = downloaded / connection.elapsed_time
        max_speed = self.config.allotted_bandwidth
        if max_speed > 0:
            theta = avg_speed / max_speed
            if theta > 1.05: self.delay += 0.01
            elif theta < 0.95 and self.delay >= 0.01: self.delay -= 0.01
            elif theta < 0.95: self.delay = 0.0
            connection.sleep(self.delay)

        save_state_info(self.output_fp + self.state_fn, snapshot)

        self.session.send_message(compact_msg({"event":PROC,"data":{"prog":status,"rate":bytes_to_str(avg_speed)}}))

        if connection.isComplete():
            fpath = self.output_fp
            fname = self.output_fn
            sname = self.state_fn
            print "Completed:", fpath + fname

            os.remove(fpath + sname)
            os.rename(fpath + fname + ".part", fpath + fname)

            self.inprogress = False
            self.state_manager.start('listening')
            self.session.send_message(compact_msg({"event":END}))

    def postMessage(self, msg):
        self.session.send_message(msg)

    def closeConnection(self):
        self.connection.destroy()
        del self.connection

class ClientSession():
    def __init__(self, sock, server):
        self.server = server
        self.state = ClientSessionState(self)
        self.stream = WebSocket.Stream(sock, self)

    def update(self):
        if self.stream.handshaken:
           self.state.update()

    def send_message(self, msg):
        self.stream.handle_response(msg)

    def message_recieved(self, msg):
        self.state.execute(msg)

    def stream_closed(self):
        self.state.closeConnection()
        self.server.removeClient(self)

#    def stream_error(self):
#        pass

    def end(self):
        self.stream.disconnect()


class WebSocketServer(asyncore.dispatcher):
    def __init__(self):
        asyncore.dispatcher.__init__(self)
        self.clients = []
        self.config = Config()
        state_info = get_state_info(pyapath + "pyaxel.st")
        if len(state_info) > 0:
            self.setMaxBandwidth(state_info.get("bandwidth", self.config.max_bandwidth))
            self.setDownloadPath(state_info.get("path", self.config.download_path))
            self.setMaxSplits(state_info.get("splits", self.config.max_splits))

    def handle_accept(self):
        try:
            sock, endpoint = self.accept()
        except TypeError:
            return
        except socket.error, err:
            #if err.args[0] != errno.ECONNABORTED:
            #    raise
            return
        else:
            if endpoint == None:
                return
            self.log("incoming connection from %s" % repr(endpoint))
            self.clients.append(ClientSession(sock, self))
            self.adjustBandwidthSetting()

    def refresh(self):
        for c in self.clients: c.update()
        for _ in self.config.pool.iterProcessedJobs(timeout=0): pass

    def savePreferences(self, bandwidth, path, splits):
        state_info = {
            "bandwidth": bandwidth,
            "splits": splits,
            "path": path
        }
        save_state_info(pyapath + "pyaxel.st", state_info)
        self.setMaxBandwidth(bandwidth)
        self.setDownloadPath(path)
        self.setMaxSplits(splits)

    def setMaxBandwidth(self, bandwidth):
        self.config.max_bandwidth = bandwidth
        self.adjustBandwidthSetting()

    def setDownloadPath(self, path):
        if not os.path.exists(path):
            return
        self.config.download_path = path

    def setMaxSplits(self, count):
        self.config.max_splits = count

    def adjustBandwidthSetting(self):
        bandwidth = self.config.max_bandwidth * 1024
        try:
            self.config.allotted_bandwidth = int(bandwidth / len(self.clients))
        except:
            self.config.allotted_bandwidth = int(bandwidth)

    def removeClient(self, client):
        self.clients.remove(client)
        self.adjustBandwidthSetting()

    def startService(self, endpoint=("", 8118), backlog=5):
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

    def stopService(self):
        sys.stdout.write('\n')
        self.log("stopping service")
        for c in self.clients: c.end()
        asyncore.socket_map.clear()
        #asyncore.close_all()


def run(options={}):
    if sys.platform.startswith('win'):
        print 'aborting: unsupported platform:', sys.platform
        return

    major, minor, micro, release, serial = sys.version_info
    if (major, minor, micro) < (2, 6, 0):
        print 'aborting: unsupported python version: %s.%s.%s' % \
            (major, minor, micro)
        return

    general_configuration(options)
    config = Config()
    endpoint = (config.host, config.port)
    server = WebSocketServer()

    try:
        server.startService(endpoint)
    except socket.error, e:
        (errno, strerror) = e
        print "Error:", endpoint, strerror
        server.stopService()
        return
    except:
        pass

    pool = config.pool
    pool.cancelAllJobs()
    pool.dismissWorkers(config.nworkers)
    server.stopService()
    sys.stdout.flush()


if __name__ == "__main__":
    usage="Usage: %prog [options]"
    description="Note: options will be overridden by those that exist in the (pyaxel.st) file."
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
                      type="str", default=pyapath,
                      help="By default, files are saved to current working"
                      " directory. Use this option to change where the saved"
                      "files should go.",
                      metavar="DIR")

    (options, args) = parser.parse_args()

    run(options.__dict__)
