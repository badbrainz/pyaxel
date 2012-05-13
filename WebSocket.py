import asynchat
import hashlib
import base64
import struct
import array


class Stream(asynchat.async_chat):
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

    def _get_input(self):
        data = "".join(self.in_buffer)
        del self.in_buffer[:]
        return data

    def _clear(self):
        del self.app_data[:]
        del self.in_buffer[:]
        try:
            del self.frame_header
        except AttributeError:
            pass

    def collect_incoming_data(self, data):
        self.in_buffer.append(data)

    def found_terminator(self):
        self.strat()

    def handle_close(self):
        self._clear()
        self.handler.stream_closed()
        #self.discard_buffers()

    def handle_error(self):
        self.close()
        self.handle_close()

    def disconnect(self):
        self.handle_response(b"", 0x08)
        self.terminate()

    def terminate(self):
        self.close()
        self.handle_close()

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
            self.log_info("malformed request:\n%s" % data, "error")
            self.terminate()
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
            self.terminate()
            return

        final = hi & 0x80
        opcode = hi & 0x0F
        #mask = lo & 0x80
        length = lo & 0x7F
        control = opcode & 0x0B

        if not control and opcode == 0x02:
            self.log_info("unsupported data format", "error")
            self.terminate()
            return

        if final:
            if control >= 0x08:
                # TODO handle ping/pong
                if length > 0x7D:
                    self.log_info("bad frame", "error")
                    self.terminate()
                    return
        else:
            if not control:
                if opcode == 0x01:
                    if self.frame_header:
                        # no interleave
                        self.log_info("unsupported message format", "error")
                        self.terminate()
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
            msg = "".join(self.app_data)
            self.handler.message_recieved(msg)
            self._clear()

        self.set_terminator(2)
        self.strat = self.parse_frame_header
