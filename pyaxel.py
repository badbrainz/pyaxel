#!/usr/bin/env python

''' TODO
    * implement rate limiting
    * handle network error:
        - unable to break from infinit loop

    CHANGES
    * renamed http_connect to http_init
    * conn_setup sets Range header
    * deprecated http_size()
'''

import contextlib
import threading
import httplib
import urllib
import urllib2
import urlparse
import socket
import time
import stat
import sys
import os

import StringIO
import ConfigParser

from collections import deque
#from ConfigParser import SafeConfigParser

try:
    import cPickle as pickle
except:
    import pickle

PYAXEL_VERSION = "1.0.0"
PYAXEL_SVN = "r"
PYAXEL_PATH = os.path.dirname(os.path.abspath(__file__)) + os.path.sep
PYAXEL_CONFIG = "pyaxel.cfg"
PYAXEL_DEST = PYAXEL_PATH

PROTO_FTP = 1
PROTO_HTTP = 2
PROTO_DEFAULT = PROTO_HTTP
SCHEME_DEFAULT = 'http'

INT_MAX = sys.maxsize

STD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US; rv:1.9.2) "\
        "Gecko/20100115 Firefox/3.6",
    "Accept-Charset": "ISO-8859-1,utf-8;q=0.7,*;q=0.7",
    "Accept-Language": "ISO-8859-1,utf-8;q=0.7,*;q=0.3",
    "Accept-Encoding": "gzip,deflate,sdch"
}

dbg_lvl = 0


class conf_t():
    pass


def conf_init(conf):
    conf.buffer_size = 5120
    conf.reconnect_delay = 20
    conf.max_speed = 0
    conf.num_connections = 1
    conf.connection_timeout = 45
    conf.http_proxy = 0
    conf.no_proxy = 0
    conf.strip_cgi_parameters = 1
    conf.save_state_interval = 10
    conf.default_file_name = 'default'
    conf.verbose = 1
    conf.http_debug = 0
    conf.alternate_output = 1
    conf.search_timeout = 10
    conf.search_threads = 3
    conf.search_amount = 15
    conf.search_top = 3

#    if not conf_load(conf, PYAXEL_PATH + PYAXEL_CONFIG):
#        return 0

    return 1


class CfgParser(ConfigParser.RawConfigParser):

    fakesec = 'section'

    def read(self, filename):
        # WARN string-only arg
        ret = []
        try:
            with open(filename, 'r') as fd:
                text = StringIO.StringIO("[%s]\n" % CfgParser.fakesec + fd.read())
                self.readfp(text, filename)
        except (IOError, EOFError):
            pass
        else:
            ret.append(filename)

        return ret


    def getopt(self, opt, default=None):
        try: return self.get(CfgParser.fakesec, opt)
        finally: return default

    def setopt(self, opt, val):
        self.set(CfgParser.fakesec, opt, val)

    def save(self, filename):
        with open(filename, 'w') as fd:
            self.write(fd)

def conf_load(conf, path):
    parser = CfgParser()
    parser.read(path)
    conf.verbose = int(parser.getopt('verbose', conf.verbose))
    conf.http_debug = int(parser.getopt('http_debug', conf.http_debug))
    conf.max_speed = int(parser.getopt('max_speed', conf.max_speed))
    conf.buffer_size = int(parser.getopt('buffer_size', conf.buffer_size))
    conf.reconnect_delay = int(parser.getopt('reconnect_delay', conf.reconnect_delay))
    conf.num_connections = int(parser.getopt('num_connections', conf.num_connections))
    conf.connection_timeout = int(parser.getopt('connection_timeout', conf.connection_timeout))
    conf.save_state_interval = int(parser.getopt('save_state_interval', conf.save_state_interval))
    conf.strip_cgi_parameters = int(parser.getopt('strip_cgi_parameters', conf.strip_cgi_parameters))
#        conf.http_proxy = 0
#        conf.no_proxy = 0
#        conf.default_file_name = 'default'
#        conf.alternate_output = 1
#        conf.search_timeout = 10
#        conf.search_threads = 3
#        conf.search_amount = 15
#        conf.search_top = 3
#        dbg_lvl = int(parser.getopt('http_debug', dbg_lvl))

    return 1


class pyaxel_t:
    def __init__(self):
        #self.buffer = ''
        self.bytes_done = 0
        self.conf = None
        self.conn = []
        self.delay_time = 0
        self.file_name = ''
        self.message = []
        self.next_state = 0
        self.outfd = -1
        self.ready = 0
        self.save_state_interval = -1
        self.size = 0
        self.start_byte = 0
        self.start_time = None
        self.url = ''


def pyaxel_new(conf, count, url):
    pyaxel = pyaxel_t()
    pyaxel.conf = conf

    if conf.max_speed > 0:
        if conf.max_speed / conf.buffer_size < 1:
            pyaxel_message(pyaxel, "Buffer resized for this speed.")
            conf.buffer_size = conf.max_speed
        pyaxel.delay_time = 1000000 / conf.max_speed * conf.buffer_size * conf.num_connections
    #pyaxel.buffer = ''

    pyaxel.url = deque()
    if count == 0:
        pyaxel.url.append(url)
    else:
        pyaxel.url.extend(url[:count])

    pyaxel.conn = [conn_t() for i in xrange(conf.num_connections)]
    pyaxel.conn[0].conf = conf

    if not conn_set(pyaxel.conn[0], pyaxel.url[0]):
        pyaxel_message(pyaxel, "Could not parse URL.")
        pyaxel.ready = -1
        return pyaxel

    if not conn_init(pyaxel.conn[0]):
        pyaxel_message(pyaxel, pyaxel.conn[0].message)
        pyaxel.ready = -1
        return pyaxel

    if not conn_info(pyaxel.conn[0]):
        pyaxel_message(pyaxel, pyaxel.conn[0].message)
        pyaxel.ready = -1
        return pyaxel

#    pyaxel.file_name = http_decode(pyaxel.conn[0].disposition or pyaxel.conn[0].file)
    pyaxel.file_name = pyaxel.conn[0].disposition or pyaxel.conn[0].file
    pyaxel.file_name = pyaxel.file_name.replace('/', '_')
    pyaxel.file_name = http_encode(pyaxel.file_name)
    # fuck index pages
    #pyaxel.file_name = http_decode(pyaxel.conn[0].file) or conf.default_file_name

    s = conn_url(pyaxel.conn[0])
    pyaxel.url[0] = s
    pyaxel.size = pyaxel.conn[0].size
    if pyaxel.size != INT_MAX:
        pyaxel_message(pyaxel, 'File size: %d' % pyaxel.size)

    # fuck ftp for now

    return pyaxel

def pyaxel_open(pyaxel):
    pyaxel_message(pyaxel, 'Opening output file: %s' % pyaxel.file_name)

    pyaxel.outfd = -1

    if not pyaxel.conn[0].supported:
        pyaxel_message(pyaxel, 'Server unsupported. Starting with one connection.')
        pyaxel.num_connections = 1
        pyaxel.conn = pyaxel.conn[:1]
        pyaxel_divide(pyaxel)
    else:
        try:
            with open('%s.st' % pyaxel.file_name, 'rb') as fd:
                st = pickle.load(fd)
                pyaxel.conf.num_connections = st.get('num_connections', 1)

                if pyaxel.conf.num_connections > len(pyaxel.conn):
                    pyaxel.conn.extend([conn_t() for i in xrange(pyaxel.conf.num_connections - len(pyaxel.conn))])
                elif pyaxel.conf.num_connections < len(pyaxel.conn):
                    pyaxel.conn = pyaxel.conn[:pyaxel.conf.num_connections]

                pyaxel_divide(pyaxel)

                pyaxel.bytes_done = st.get('bytes_done', 0)
                for conn, byte in zip(pyaxel.conn, st.get('current_byte', 0)):
                    conn.current_byte = byte

                pyaxel_message(pyaxel, 'State file found: %d bytes downloaded, %d remaining' % \
                              (pyaxel.bytes_done, pyaxel.size - pyaxel.bytes_done))

                try:
                    pyaxel.outfd = open(pyaxel.file_name, 'wb')
                except IOError:
                    pyaxel_message(pyaxel, 'Error opening local file: %s' % pyaxel.file_name)
                    return 0
        except pickle.UnpicklingError:
            pass
        except (IOError, EOFError):
            pass

    if pyaxel.outfd == -1:
        pyaxel_divide(pyaxel)

        try:
            pyaxel.outfd = open(pyaxel.file_name, 'wb')
            pyaxel.outfd.truncate(pyaxel.size)
        except IOError:
            pyaxel_message(pyaxel, 'Error opening local file: %s' % pyaxel.file_name)
            return 0

    return 1

def pyaxel_start(pyaxel):
    # TODO assign mirrors
    for i, conn in enumerate(pyaxel.conn):
        conn_set(conn, pyaxel.url[0])
        conn.conf = pyaxel.conf
        if i:
            conn.supported = 1

    pyaxel_message(pyaxel, 'Starting download.')

    for conn in pyaxel.conn:
        if conn.current_byte <= conn.last_byte:
            conn.state = 1
            conn.setup_thread = threading.Thread(target=setup_thread, args=(conn,))
            conn.setup_thread.daemon = True
            conn.setup_thread.start()
            conn.last_transfer = time.time()

    pyaxel.start_time = time.time()
    pyaxel.ready = 0

def pyaxel_do(pyaxel):
    if time.time() > pyaxel.next_state:
        pyaxel_save(pyaxel)
        pyaxel.next_state = time.time() + pyaxel.conf.save_state_interval

    if all(conn.enabled < 1 for conn in pyaxel.conn):
        time.sleep(1)

    for conn in pyaxel.conn:
        if conn.enabled == 1:
            try:
                conn.last_transfer = time.time()
                fetch_size = min(conn.last_byte + 1 - conn.current_byte, pyaxel.conf.buffer_size)
                try:
                    data = conn.http.fd.read(fetch_size)
                except socket.error:
                    pyaxel_message(pyaxel, 'Error on connection %d' % pyaxel.conn.index(conn))
                    conn_disconnect(conn)
                    conn.enabled = -1
                    continue
                size = len(data)
                if size == 0:
                    if conn.current_byte < conn.last_byte:# and pyaxel.size != INT_MAX:
                        pyaxel_message(pyaxel, 'Connection %d unexpectedly closed.' % pyaxel.conn.index(conn))
                    else:
                        pyaxel_message(pyaxel, 'Connection %d finished.' % pyaxel.conn.index(conn))
                    if not pyaxel.conn[0].supported:
                        pyaxel.ready = 1
                    conn.enabled = 0
                    conn_disconnect(conn)
                    continue
                if size != fetch_size:
                    pyaxel_message(pyaxel, 'Error on connection %d.' % pyaxel.conn.index(conn))
                    conn.enabled = -1
                    conn_disconnect(conn)
                    continue
                remaining = conn.last_byte + 1 - conn.current_byte + 1
                if remaining < size:
                    pyaxel_message(pyaxel, 'Connection %d finished.' % pyaxel.conn.index(conn))
                    conn.enabled = 0
                    conn_disconnect(conn)
                    size = remaining
                try:
                    pyaxel.outfd.seek(conn.current_byte)
                    pyaxel.outfd.write(data)
                except IOError:
                    pyaxel_message(pyaxel, 'Write error!')
                    pyaxel.ready = -1
                    return
                conn.current_byte += size
                pyaxel.bytes_done += size
            except Exception, err:
                pyaxel_message(pyaxel, 'Unexpected error on connection %d: %s' % (pyaxel.conn.index(conn), err))
                conn_disconnect(conn)
                conn.enabled = -1
#                pdb.set_trace()

    if pyaxel.ready:
        return

    # TODO limit reconnect attempt
    for conn in pyaxel.conn:
        if conn.enabled == -1 and conn.current_byte < conn.last_byte:
            if conn.state == 0:
                conn.setup_thread.join()
                pyaxel_message(pyaxel, 'Restarting connection %d.' % pyaxel.conn.index(conn))
                # TODO try another URL
                conn_set(conn, pyaxel.url[0])
                conn.state = 1
                conn.setup_thread = threading.Thread(target=setup_thread, args=(conn,))
                conn.setup_thread.daemon = True
                conn.setup_thread.start()
                conn.last_transfer = time.time()
            elif conn.state == 1: # not necessary when using socket.setdefaulttimeout
                if time.time() > conn.last_transfer + pyaxel.conf.reconnect_delay:
                    conn_disconnect(conn)
                    conn.state = 0

    # TODO calculate current average speed and finish_time

    if pyaxel.bytes_done == pyaxel.size:
        pyaxel_message(pyaxel, 'Download complete.')
        pyaxel.ready = 1

def pyaxel_divide(pyaxel):
    pyaxel.conn[0].current_byte = 0
    pyaxel.conn[0].last_byte = pyaxel.size / pyaxel.conf.num_connections - 1
    for i in xrange(1, pyaxel.conf.num_connections):
        pyaxel.conn[i].current_byte = pyaxel.conn[i-1].last_byte + 1
        pyaxel.conn[i].last_byte = pyaxel.conn[i].current_byte + pyaxel.size / pyaxel.conf.num_connections
    pyaxel.conn[pyaxel.conf.num_connections-1].last_byte = pyaxel.size - 1

def pyaxel_close(pyaxel):
    for conn in pyaxel.conn:
        conn.enabled = 0

    if pyaxel.ready == 1:
        if os.path.exists('%s.st' % pyaxel.file_name):
            os.remove('%s.st' % pyaxel.file_name)
    elif pyaxel.bytes_done > 0:
        pyaxel_save(pyaxel)

    pyaxel.ready = -1
    #del pyaxel.message[:]

    if pyaxel.outfd != -1:
        pyaxel.outfd.close()
        pyaxel.outfd = -1
    for conn in pyaxel.conn:
        conn_disconnect(conn)

    #del pyaxel.conn[:]

def pyaxel_message(pyaxel, msg):
    if not pyaxel.message:
        pyaxel.message = []
    pyaxel.message.append(msg)

def print_messages(pyaxel):
    print '\n'.join(pyaxel.message)
    del pyaxel.message[:]

def pyaxel_save(pyaxel):
    # No use for such a file if the server doesn't support resuming anyway
    if not pyaxel.conn[0].supported:
        return

    try:
        with open('%s.st' % pyaxel.file_name, 'wb') as fd:
            state = {
                'num_connections': pyaxel.conf.num_connections,
                'bytes_done': pyaxel.bytes_done,
                'current_byte': [conn.current_byte for conn in pyaxel.conn]
            }
            pickle.dump(state, fd)
    except IOError:
        pass


class conn_t:
    def __init__(self):
        self.conf = None
        self.current_byte = None
        self.dir = ''
        self.disposition = None
        self.enabled = -1
        self.file = ''
        self.host = ''
        self.http = http_t()
        self.last_byte = None
        self.local_if = ''
        self.message = ''
        self.path = ''
        self.port = None
        self.proto = -1
        self.pwd = ''
        self.retries = 0
        self.scheme = ''
        self.setup_thread = None
        self.size = 0
        self.state = -1
        self.supported = 0
        self.usr = ''


def conn_set(conn, url):
    parts = urlparse.urlparse(url)

    if not parts.netloc:
        return 0
    else:
        conn.host = parts.netloc

    if not parts.port:
        conn.port = 80
    else:
        conn.port = parts.port

    if not parts.scheme:
        conn.scheme = SCHEME_DEFAULT
        conn.proto = PROTO_DEFAULT
    else:
        if 'http' in parts.scheme:
            conn.proto = PROTO_HTTP
            conn.scheme = parts.scheme
        else:
            return 0

    if not parts.path.startswith('/'):
        return 0
    else:
        conn.dir, conn.file = parts.path.rsplit('/', 1)
        conn.dir += '/'
        if conn.proto == PROTO_HTTP:
            conn.dir = http_decode(conn.dir)
        if not conn.file:
            return 0
        if parts.query:
            conn.file += '?%s' % parts.query

    conn.usr = parts.username
    conn.pwd = parts.password

    return conn.port > 0

def conn_init(conn):
    proxy = None

    conn.proxy = proxy is not None

    if conn.proto == PROTO_HTTP:
        conn.http.local_if = conn.local_if
        if not http_init(conn.http, conn.proto, conn.host, proxy, conn.port,
            conn.usr, conn.pwd):
            conn.message = conn.http.headers
            conn_disconnect(conn)
            return 0
    else:
        return 0

    conn.message = conn.http.headers

    return 1

def conn_info(conn):
    # fuck ftp for now
    if conn.proto != PROTO_HTTP:
        return 0

    conn.current_byte = 0
    if not conn_setup(conn):
        return 0
    if not conn_exec(conn):
        conn.message = conn.http.headers
        return 0
    conn_disconnect(conn)
    if not conn_set(conn, http_header(conn.http, 'location')):
        return 0
    # relative URL?
    # missing netloc?

    conn.disposition = http_header(conn.http, 'content-disposition')
    if conn.disposition:
        conn.disposition = conn.disposition.split('filename=')
        if len(conn.disposition) == 2 and conn.disposition[1].startswith(('"',"'")):
            conn.disposition = conn.disposition[1][1:-1]
        else:
            conn.disposition = None

    # TODO check transfer-encoding
    conn.size = int(http_header(conn.http, 'content-length') or 0)
#    if conn.http.status == 206 and conn.size >= 0:
#        conn.supported = 1
#        conn.size += 1
#    elif conn.http.status in (200, 206):
#        conn.supported = 0
#        conn.size = INT_MAX
    if conn.http.status in (200, 206) and conn.size > 0:
        if conn.http.status == 206:
            conn.supported = 1
        else:
            conn.supported = 0
    else:
        conn.message = 'Unknown HTTP error.'
        return 0

    return 1

def conn_setup(conn):
    # TODO add conn headerstry
    # TODO use conf_t
    if not conn.http.fd:
        if not conn_init(conn):
            return 0

    s = conn_url(conn)
#    conn.http.first_byte = conn.current_byte
#    conn.http.last_byte = conn.last_byte
    http_setup(conn.http, s)
    http_addheader(conn.http, 'User-Agent', STD_HEADERS['User-Agent'])
    if conn.last_byte:
        http_addheader(conn.http, 'Range', 'bytes=%d-%d' % (conn.current_byte, conn.last_byte))
    else:
        http_addheader(conn.http, 'Range', 'bytes=%d-' % conn.current_byte)

    return 1

def conn_exec(conn):
    if not http_exec(conn.http):
        return 0

    return conn.http.status / 100 == 2

def conn_url(conn):
    return '%s://%s%s%s' % (conn.scheme, conn.host, conn.dir, conn.file)

def conn_disconnect(conn):
    http_disconnect(conn.http)


class http_t:
    def __init__(self):
        self.auth = ''
        self.fd = None
#        self.first_byte = None
        self.headers = ''
        self.host = ''
        self.local_if = None
#        self.last_byte = None
        self.opener = None
        self.proto = None
        self.proxy = None
        self.request = ''
        self.status = None


def http_connect(http, proto, host, proxy=None, port=80, usr=None, pwd=None):
    pass
def http_init(http, proto, host, proxy=None, port=80, usr=None, pwd=None):
    # TODO handle proxy
    # TODO handle auth
    http.host = host
    http.proto = proto
    http.proxy = 0
    http.opener = urllib2.build_opener(urllib2.HTTPHandler(debuglevel=dbg_lvl),
                                       urllib2.HTTPSHandler(debuglevel=dbg_lvl),
                                       urllib2.HTTPCookieProcessor())

    return 1

def http_setup(http, lurl):
    http.request = urllib2.Request(lurl, origin_req_host=http.host)
def http_get(http, lurl):
    http.request = urllib2.Request(lurl, origin_req_host=http.host)

    if http.first_byte:
        if http.last_byte:
            http_addheader(http, 'Range', 'bytes=%d-%d' % (http.first_byte, http.last_byte))
        else:
            http_addheader(http, 'Range', 'bytes=%d-' % http.first_byte)

def http_addheader(http, key, val):
    http.request.add_header(key, val)

def http_header(http, name):
    return http.headers.get(name)

def http_exec(http):
    try:
        response = http.opener.open(http.request, timeout=20)
        http.headers = response.info()
        http.headers['Location'] = response.geturl()
        http.status = response.code
        http.fd = response
    except urllib2.HTTPError, e:
        http.headers = str(e)
        http.status = e.code
        return 0
    except urllib2.URLError, e:
        http.headers = str(e.reason)
        http.status = None
        return 0

    return 1

def http_disconnect(http):
    if http.fd:
        http.fd.close()
        http.fd = None

def http_decode(s):
    # safe="%/:=&?~#+!$,;'@()*[]|"
    return urllib.quote(s)

def http_encode(s):
    return urllib.unquote(s)

def setup_thread(conn):
    if conn_setup(conn):
        conn.last_transfer = time.time()
        if conn_exec(conn):
            conn.last_transfer = time.time()
            conn.state = 0
            conn.enabled = 1
            return 1

    conn_disconnect(conn)
    conn.state = 0
    return 0


def main(argv=None):
    if argv is None:
        argv = sys.argv

    from optparse import OptionParser
    parser = OptionParser(usage="Usage: %prog [options] url")
    parser.add_option("-q", "--quiet", dest="verbose",
                      default=False, action="store_true",
                      help="leave stdout alone")
    parser.add_option("-p", "--print", dest="http_debug",
                      default=False, action="store_true",
                      help="print HTTP info")
    parser.add_option("-n", "--num-connections", dest="num_connections",
                      type="int", default=1,
                      help="specify maximum number of connections",
                      metavar="x")
    parser.add_option("-s", "--max-speed", dest="max_speed",
                      type="int", default=0,
                      help="specify maximum speed (bytes per second)",
                      metavar="x")

    (options, args) = parser.parse_args()

    if len(args) != 1:
        parser.print_help()
    else:
        try:
            # TODO search mirrors
            url = args[0]
            conf = conf_t()

            conf_init(conf)
            if not conf_load(conf, PYAXEL_PATH + PYAXEL_CONFIG):
                return 1

            for prop in options.__dict__:
                    if not callable(options.__dict__[prop]):
                        setattr(conf, prop, getattr(options, prop))

            conf.verbose = bool(conf.verbose)
            conf.http_debug = bool(conf.http_debug)
            conf.num_connections = options.num_connections

            axel = pyaxel_new(conf, 0, url)
            if axel.ready == -1:
                print_messages(axel)
                return 1

            print_messages(axel)

            # TODO check permissions, destination opt, etc.
            if not bool(os.stat(os.getcwd()).st_mode & stat.S_IWUSR):
                print 'Can\'t access protected directory: %s' % os.getcwd()
                return 1
#            if not os.access(axel.file_name, os.F_OK):
#                print 'Couldn\'t access %s' % axel.file_name
#                return 0
#            if not os.access('%s.st' % axel.file_name, os.F_OK):
#                print 'Couldn\'t access %s.st' % axel.file_name
#                return 0

            if not pyaxel_open(axel):
                print_messages(axel)
                return 1

            pyaxel_start(axel)
            print_messages(axel)

            while not axel.ready:
                pyaxel_do(axel)
                if axel.message:
                    print_messages(axel)

            # TODO print elapsed time
            pyaxel_close(axel)
        except KeyboardInterrupt:
            print
            return 1
        except:
            return 1

        return 0

if __name__ == "__main__":
    print 'pyaxel %s-%s' % (PYAXEL_VERSION, PYAXEL_SVN)
    sys.exit(main())
