#!/usr/bin/env python

import ConfigParser
import contextlib
import httplib
import os
import socket
import stat
import StringIO
import sys
import threading
import time
import urllib
import urllib2
import urlparse

try:
    import cPickle as pickle
except:
    import pickle

from collections import deque

PYAXEL_SRC_VERSION = '1.0.0'

PYAXEL_PATH = os.path.dirname(os.path.abspath(__file__)) + os.path.sep
PYAXEL_CONFIG = 'pyaxel.cfg'
PYAXEL_DEST = PYAXEL_PATH

PROTO_FTP = 1
PROTO_HTTP = 2
PROTO_DEFAULT = PROTO_HTTP
SCHEME_DEFAULT = 'http'

DEFAULT_USER_AGENT = 'Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US; rv:1.9.2) '\
    'Gecko/20100115 Firefox/3.6'

INT_MAX = sys.maxsize

dbg_lvl = 0


class conf_t():
    alternate_output = 0
    buffer_size = 5120
    default_filename = 'default'
    max_speed = 0
    max_reconnect = 5
    num_connections = 1
    reconnect_delay = 20
    save_state_interval = 10
    user_agent = DEFAULT_USER_AGENT

class confparser_c(ConfigParser.RawConfigParser):

    fakesec = 'section'

    def read(self, filename):
        # WARN string-only arg
        try:
            with open(filename, 'r') as fd:
                text = StringIO.StringIO('[%s]\n' % confparser_c.fakesec + fd.read())
                self.readfp(text, filename)
        except (IOError, EOFError, ConfigParser.ParsingError):
            return 0
        return 1

    def getopt(self, opt, default=None):
        try: return self.get(confparser_c.fakesec, opt)
        except: return default


def conf_init(conf):
    if not conf_load(conf, PYAXEL_PATH + PYAXEL_CONFIG):
        return 0

    # TODO proxy?

    return 1

def conf_load(conf, path):
    parser = confparser_c()
    if not parser.read(path):
        return 0

    conf.alternate_output = int(parser.getopt('alternate_output', conf.alternate_output))
    conf.buffer_size = int(parser.getopt('buffer_size', conf.buffer_size))
    conf.default_filename = str(parser.getopt('default_filename', conf.default_filename))
    conf.max_speed = int(parser.getopt('max_speed', conf.max_speed))
    conf.max_reconnect = int(parser.getopt('max_reconnect', conf.max_reconnect))
    conf.num_connections = int(parser.getopt('num_connections', conf.num_connections))
    conf.reconnect_delay = int(parser.getopt('reconnect_delay', conf.reconnect_delay))
    conf.save_state_interval = int(parser.getopt('save_state_interval', conf.save_state_interval))
    conf.user_agent = str(parser.getopt('user_agent', conf.user_agent))

    return 1


class pyaxel_t:
    #buffer = ''
    bytes_done = 0
    bytes_per_second = 0
    bytes_start = 0
    conf = None
    conn = []
    delay_time = 0
    file_name = ''
    finish_time = 0
    last_error = ''
    message = []
    next_state = 0
    outfd = -1
    ready = None
    save_state_interval = 0
    size = 0
    start_time = None
    url = None


def pyaxel_new(conf, count, url):
    pyaxel = pyaxel_t()
    pyaxel.conf = conf

    if conf.max_speed > 0:
        if conf.max_speed / conf.buffer_size < 1:
            pyaxel_message(pyaxel, 'Buffer resized for this speed.')
            conf.buffer_size = conf.max_speed
        pyaxel.delay_time = 10000 / conf.max_speed * conf.buffer_size * conf.num_connections
    #pyaxel.buffer = ''

    pyaxel.url = deque()
    if count == 0:
        pyaxel.url.append(url)
    else:
        pyaxel.url.extend([search.url for search in url[:count]])

    pyaxel.conn = [conn_t() for i in xrange(conf.num_connections)]
    pyaxel.conn[0].conf = conf

    if not conn_set(pyaxel.conn[0], pyaxel.url[0]):
        pyaxel_error(pyaxel, 'Could not parse URL.')
        pyaxel.ready = -1
        return pyaxel

    if not conn_init(pyaxel.conn[0]):
        pyaxel_error(pyaxel, pyaxel.conn[0].message)
        pyaxel.ready = -1
        return pyaxel

    if not conn_info(pyaxel.conn[0]):
        pyaxel_error(pyaxel, pyaxel.conn[0].message)
        pyaxel.ready = -1
        return pyaxel

    pyaxel.file_name = pyaxel.conn[0].disposition or pyaxel.conn[0].file_name
    pyaxel.file_name = pyaxel.file_name.replace('/', '_')
    pyaxel.file_name = http_decode(pyaxel.file_name) or conf.default_filename

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
        pyaxel.conf.num_connections = 1
        pyaxel.conn = pyaxel.conn[:1]
        pyaxel_divide(pyaxel)
    else:
        try:
            with open('%s.st' % pyaxel.file_name, 'rb') as fd:
                try:
                    st = pickle.load(fd)
                except pickle.UnpicklingError:
                    # TODO break from context
                    pass

                pyaxel.conf.num_connections = st['num_connections']

                if pyaxel.conf.num_connections > len(pyaxel.conn):
                    pyaxel.conn.extend([conn_t() for i in xrange(pyaxel.conf.num_connections - len(pyaxel.conn))])
                elif pyaxel.conf.num_connections < len(pyaxel.conn):
                    pyaxel.conn = pyaxel.conn[:pyaxel.conf.num_connections]

                pyaxel_divide(pyaxel)

                pyaxel.bytes_done = st['bytes_done']
                for conn, byte in zip(pyaxel.conn, st['current_byte']):# check this
                    conn.current_byte = byte

                pyaxel_message(pyaxel, 'State file found: %d bytes downloaded, %d remaining' %
                              (pyaxel.bytes_done, pyaxel.size - pyaxel.bytes_done))

                try:
                    flags = os.O_CREAT | os.O_WRONLY
                    if hasattr(os, 'O_BINARY'):
                        flags |= os.O_BINARY
                    pyaxel.outfd = os.open(pyaxel.file_name, flags)
                except os.error:
                    pyaxel_error(pyaxel, 'Error opening local file: %s' % pyaxel.file_name)
                    return 0
        except (IOError, EOFError):
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
            pyaxel_error(pyaxel, 'Error opening local file: %s' % pyaxel.file_name)
            return 0

    return 1

def pyaxel_start(pyaxel):
    # TODO assign mirrors
    for i, conn in enumerate(pyaxel.conn):
        conn_set(conn, pyaxel.url[0])
        pyaxel.url.rotate(1)
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
    pyaxel.bytes_start = pyaxel.bytes_done
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
                    os.lseek(pyaxel.outfd, conn.current_byte, os.SEEK_SET)
                    os.write(pyaxel.outfd, data)
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

    if pyaxel.ready:
        return

    for conn in pyaxel.conn:
        if conn.enabled == -1 and conn.current_byte < conn.last_byte:
            if conn.state == 0:
                conn.setup_thread.join()
                pyaxel_message(pyaxel, 'Restarting connection %d.' % pyaxel.conn.index(conn))
                # TODO try another URL
                conn_set(conn, pyaxel.url[0])
                pyaxel.url.rotate(1)
                conn.state = 1
                conn.setup_thread = threading.Thread(target=setup_thread, args=(conn,))
                conn.setup_thread.daemon = True
                conn.setup_thread.start()
                conn.last_transfer = time.time()
            elif conn.state == 1: # not necessary when using socket.setdefaulttimeout
                if time.time() > conn.last_transfer + pyaxel.conf.reconnect_delay:
                    conn_disconnect(conn)
                    conn.state = 0

    pyaxel.bytes_per_second = (pyaxel.bytes_done - pyaxel.bytes_start) / (time.time() - pyaxel.start_time)
    pyaxel.finish_time = pyaxel.start_time + (pyaxel.size - pyaxel.bytes_start) / pyaxel.bytes_per_second

    if pyaxel.conf.max_speed > 0:
        if pyaxel.bytes_per_second / pyaxel.conf.max_speed > 1.05:
            pyaxel.delay_time += 0.01
        elif pyaxel.bytes_per_second / pyaxel.conf.max_speed < 0.95 and pyaxel.delay_time >= 0.01:
            pyaxel.delay_time -= 0.01
        elif pyaxel.bytes_per_second / pyaxel.conf.max_speed < 0.95:
            pyaxel.delay_time = 0
        time.sleep(pyaxel.delay_time)

    if pyaxel.bytes_done == pyaxel.size:
        pyaxel_message(pyaxel, 'Download complete.')
        pyaxel.ready = 1

def pyaxel_divide(pyaxel):
    pyaxel.conn[0].first_byte = 0
    pyaxel.conn[0].current_byte = 0
    pyaxel.conn[0].last_byte = pyaxel.size / pyaxel.conf.num_connections - 1
    for i in xrange(1, pyaxel.conf.num_connections):
        pyaxel.conn[i].current_byte = pyaxel.conn[i-1].last_byte + 1
        pyaxel.conn[i].first_byte = pyaxel.conn[i].current_byte
        pyaxel.conn[i].last_byte = pyaxel.conn[i].current_byte + pyaxel.size / pyaxel.conf.num_connections - 1
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
        os.close(pyaxel.outfd)
        pyaxel.outfd = -1
    for conn in pyaxel.conn:
        conn_disconnect(conn)

    #del pyaxel.conn[:]

def pyaxel_message(pyaxel, msg):
    if not pyaxel.message:
        pyaxel.message = []
    pyaxel.message.append(msg)

def pyaxel_error(pyaxel, msg):
    pyaxel.last_error = msg
    pyaxel_message(pyaxel, msg)

def pyaxel_print(pyaxel):
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
    conf = None
    current_byte = None
    directory = ''
    disposition = None
    enabled = -1
    file_name = ''
    host = ''
    http = None
    last_byte = None
    local_if = ''
    message = ''
    path = ''
    port = None
    proto = -1
    pwd = ''
    query = ''
    retries = 0
    scheme = ''
    setup_thread = None
    size = 0
    first_byte = None
    state = -1
    supported = 0
    usr = ''

    def __init__(self):
        self.http = http_t()


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
        conn.directory, conn.file_name = parts.path.rsplit('/', 1)
        conn.directory += '/'
        if conn.proto == PROTO_HTTP:
            conn.directory = http_decode(conn.directory)
        if not conn.file_name:
            return 0
        if parts.query:
            conn.query = '?' + parts.query

    conn.usr = parts.username
    conn.pwd = parts.password

    return conn.port > 0

def conn_init(conn):
    proxy = None

    conn.proxy = proxy is not None

    if conn.proto == PROTO_HTTP:
        conn.http.local_if = conn.local_if
        if not http_init(conn.http, conn.proto, conn.host, proxy, conn.port, conn.usr, conn.pwd):
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
    if not conn_exec(conn): # WARN could potentially stall for as long as 20s
        conn.message = conn.http.headers
        return 0
    conn_disconnect(conn)
    if not conn_set(conn, http_header(conn.http, 'location')):
        conn.message = 'Invalid URL.';
        return 0
    # relative URL?
    # missing netloc?

    conn.disposition = http_header(conn.http, 'content-disposition')
    if conn.disposition:
        conn.disposition = conn.disposition.split('filename=')
        if len(conn.disposition) == 2 and conn.disposition[1].startswith(('"','\'')):
            conn.disposition = conn.disposition[1][1:-1]
        else:
            conn.disposition = None

    # TODO check transfer-encoding
    conn.size = int(http_header(conn.http, 'content-length') or 0)
    if conn.http.status in (200, 206) and conn.size > 0:
        if conn.http.status == 206:
            conn.supported = 1
#            conn.size += 1
        else:
            conn.supported = 0
#            conn.size = INT_MAX
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
    http_addheader(conn.http, 'User-Agent', conn.conf.user_agent)
    http_addheader(conn.http, 'Accept-Encoding', 'gzip,deflate,sdch')
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
    return '%s://%s%s%s%s' % (conn.scheme, conn.host, conn.directory, conn.file_name, conn.query)

def conn_disconnect(conn):
    http_disconnect(conn.http)


class http_t:
    auth = ''
    fd = None
#    first_byte = None
    headers = ''
    host = ''
    local_if = None
#    last_byte = None
    opener = None
    proto = None
    proxy = None
    request = ''
    status = None


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
    # safe='%/:=&?~#+!$,;'@()*[]|'
    return urllib.unquote_plus(s)

def http_encode(s):
    return urllib.quote_plus(s)

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


class search_c:
    url = ''


def main(argv=None):
    if argv is None:
        argv = sys.argv

    from optparse import OptionParser
    from optparse import IndentedHelpFormatter
    fmt = IndentedHelpFormatter(indent_increment=4, max_help_position=40, width=77, short_first=1)
    parser = OptionParser(usage='Usage: %prog [options] url[+]', formatter=fmt, version=PYAXEL_SRC_VERSION)
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
    parser.add_option('-S', '--search', action='callback',
                      callback=lambda o,s,v,p: setattr(p.values, o.dest, v.split(',')),
                      type='string', metavar='x,',
                      help='search for mirrors and download from x servers')

    options, args = parser.parse_args()

    if len(args) == 0:
        parser.print_help()
    else:
        try:
            axel = None
            conf = conf_t()

            conf_init(conf)
            if not conf_load(conf, PYAXEL_PATH + PYAXEL_CONFIG):
                return 1

            options = vars(options)
            for prop in options:
                if hasattr(conf, prop) and options[prop] != None:
                    setattr(conf, prop, options[prop])

            if hasattr(options, 'search'):
                # TODO
                #   search mirrors
                pass
            if len(args) == 1:
                axel = pyaxel_new(conf, 0, args[0])
            else:
                # TODO resource comparison?
                search = []
                for arg in args:
                    search.append(search_c())
                    search[-1].url = arg
                axel = pyaxel_new(conf, len(search), search)

            if axel.ready == -1:
                pyaxel_print(axel)
                return 1

            pyaxel_print(axel)

            if not hasattr(conf, 'download_path') or not conf.download_path:
                conf.download_path = PYAXEL_PATH
            if not conf.download_path.endswith(os.path.sep):
                conf.download_path += os.path.sep

            axel.file_name = conf.download_path + axel.file_name

            # TODO check permissions, destination opt, etc.
            if not bool(os.stat(conf.download_path).st_mode & stat.S_IWUSR):
                print 'Can\'t access protected directory: %s' % conf.download_path
                return 1

            if not pyaxel_open(axel):
                pyaxel_print(axel)
                return 1

            pyaxel_start(axel)
            pyaxel_print(axel)

            while not axel.ready:
                prev = axel.bytes_done
                pyaxel_do(axel)

                if conf.alternate_output:
                    if not axel.message and prev != axel.bytes_done:
                        print_alternate_output(axel)
                else:
                    # TODO use wget-style
                    if not axel.message and prev != axel.bytes_done:
                        print_alternate_output(axel)

                if axel.message:
                    if conf.alternate_output:
                        sys.stdout.write('\r\x1b[K')
                    else:
                        sys.stdout.write('\n')
                    pyaxel_print(axel)
                    if not axel.ready:
                        if conf.alternate_output != 1:
                            # TODO use wget-style
                            if not axel.message and prev != axel.bytes_done:
                                print_alternate_output(axel)
                        else:
                            print_alternate_output(axel)
                elif axel.ready:
                    sys.stdout.write('\n')

            pyaxel_close(axel)
            sys.stdout.flush()
        except KeyboardInterrupt:
            print
            return 1
        except Exception, e:
            print e
            print 'Unknown error!'
            return 1

        return 0

# TODO should include little cute dots
def print_alternate_output(pyaxel):
    if pyaxel.bytes_done < pyaxel.size:
        sys.stdout.write('\r\x1b[K')
        sys.stdout.write('Progress: %d%%' % (pyaxel.bytes_done * 100 / pyaxel.size))
        seconds = int(pyaxel.finish_time - time.time())
        minutes = int(seconds / 60)
        seconds -= minutes * 60
        hours = int(minutes / 60)
        minutes -= hours * 60
        days = int(hours / 24)
        hours -= days * 24
        if days:
            sys.stdout.write(' [%dd %dh]' % (days, hours))
        elif hours:
            sys.stdout.write(' [%dh %dm]' % (hours, minutes))
        else:
            sys.stdout.write(' [%dm %ds]' % (minutes, seconds))
    sys.stdout.flush()

if __name__ == '__main__':
    sys.exit(main())
