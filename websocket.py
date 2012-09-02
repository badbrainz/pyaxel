import asynchat
import struct
import hashlib
import base64
import array

GOAWAY = 1001

class AsyncChat(asynchat.async_chat):
    """this class implements version 13 of the WebSocket protocol,
    http://tools.ietf.org/html/rfc6455.
    specs:
        - unicode text framing
    """

    def __init__(self, sock, handler):
        asynchat.async_chat.__init__(self, sock)
        self.handler = handler
        self.in_buffer = []
        self.payload_buffer = []
        self.handshaken = False
        self.state = self.parse_request_header
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

    def parse_request_header(self, data):
        crlf = '\x0D\x0A'

        # TODO validate GET
        fields = dict([l.split(': ', 1) for l in data.split(crlf)[1:]])
        required = ('Host', 'Upgrade', 'Connection', 'Sec-WebSocket-Key',
                    'Sec-WebSocket-Version')
        if not all(map(lambda f: f in fields, required)):
            self.last_error = (1002, 'malformed request')
            self.handle_error()
            return

        sha1 = hashlib.sha1()
        sha1.update(fields['Sec-WebSocket-Key'])
        sha1.update('258EAFA5-E914-47DA-95CA-C5AB0DC85B11')
        challenge = base64.b64encode(sha1.digest())

        self.push('HTTP/1.1 101 Switching Protocols' + crlf)
        self.push('Upgrade: websocket' + crlf)
        self.push('Connection: Upgrade' + crlf)
        self.push('Sec-WebSocket-Accept: %s' % challenge + crlf * 2)

        self.handshaken = True
        self.set_terminator(2)
        self.state = self.parse_frame_header

    def parse_frame_header(self, data):
        hi, lo = struct.unpack('BB', data)

        # no extensions
        if hi & 0x70:
            self.last_error = (1003, 'no extensions support')
            self.handle_error()
            return

        final = hi & 0x80
        opcode = hi & 0x0F
        #mask = lo & 0x80
        length = lo & 0x7F
        control = opcode & 0x0B

        if not control and opcode == 0x02:
            self.last_error = (1003, 'unsupported data format')
            self.handle_error()
            return

        if final:
            if control >= 0x08:
                # TODO handle ping/pong
                if length > 0x7D:
                    self.last_error = (1002, 'bad frame')
                    self.handle_error()
                    return
        else:
            if not control:
                if opcode == 0x01:
                    if self.frame_header:
                        # no interleave
                        self.last_error = (1003, 'unsupported message format')
                        self.handle_error()
                        return

        self.frame_header = []
        self.frame_header.append(final)
        self.frame_header.append(opcode)
        #self.frame_header.append(mask)
        self.frame_header.append(length)

        if length <= 0x7D:
            self.state = self.parse_payload_masking_key
            self.set_terminator(4)
        elif length == 0x7E:
            self.state = self.parse_payload_extended_len
            self.set_terminator(2)
        else:
            self.state = self.parse_payload_extended_len
            self.set_terminator(8)

    def parse_payload_extended_len(self, data):
        fmt = '>H' if self.frame_header[2] == 0x7E else '>Q'
        self.frame_header[2] = struct.unpack(fmt, data)[0]
        self.state = self.parse_payload_masking_key
        self.set_terminator(4)

    def parse_payload_masking_key(self, data):
        self.frame_header.append(data)
        self.state = self.parse_payload_data
        self.set_terminator(self.frame_header[2])

    def parse_payload_data(self, data):
        bytes = array.array('B', data)
        mask = array.array('B', self.frame_header[3])
        bytes = [chr(b ^ mask[i % 4]) for i, b in enumerate(bytes)]
        self.payload_buffer.extend(bytes)
        if self.frame_header[0]:
            msg = ''.join(self.payload_buffer)
            del self.payload_buffer[:]
            del self.frame_header
            self.handler.chat_message(msg)
        self.set_terminator(2)
        self.state = self.parse_frame_header

    def collect_incoming_data(self, data):
        self.in_buffer.append(data)

    def found_terminator(self):
        self.state(''.join(self.in_buffer))
        del self.in_buffer[:]

    def handle_close(self):
        self._cleanup()
        self.handler.chat_closed()

    def handle_error(self):
        if hasattr(self, 'last_error'):
            status, reason = self.last_error
            msg = struct.pack('>H%ds' % len(reason), status, reason)
            self.handle_response(msg, 0x08)
        self.close()
        self.handle_close()

    def disconnect(self, status=1000, reason=''):
        if self.handshaken:
            msg = struct.pack('>H%ds' % len(reason), status, reason)
            self.handle_response(msg, 0x08)
            self.close()
            self._cleanup()

    def _cleanup(self):
        del self.payload_buffer[:]
        del self.in_buffer[:]
        if hasattr(self, 'last_error'):
            del self.last_error
        if hasattr(self, 'frame_header'):
            del self.frame_header
        self.handshaken = False
