var ConnectionEvent = {
    CONNECTED       : 0,
    DISCONNECTED    : 1,
    ERROR           : 2
}

var ConnectionState = {
    CONNECTING      : 0,
    OPEN            : 1,
    CLOSING         : 2,
    CLOSED          : 3
}

var DownloadStatus = {
    QUEUED          : 0,
    INITIALIZING    : 1,
    IN_PROGRESS     : 2,
    COMPLETE        : 3,
    CANCELLED       : 4,
    PAUSED          : 5,
    UNDEFINED       : 6,
    CONNECTING      : 7
}

/* svr commands */
var ServerCommand = {
    QUIT            : "QUIT",
    PAUSE           : "STOP",
    START           : "START",
    ABORT           : "ABORT",
    RESUME          : "RESUME"
}

/* srv reply codes */
var MessageEvent = {
    ACK             : 0,
    OK              : 1,
    INVALID         : 2,
    BAD_REQUEST     : 3,
    ERROR           : 4,
    PROCESSING      : 5,
    END             : 6,
    INCOMPLETE      : 7,
    STOPPED         : 8,
    UNDEFINED       : 9,
    INITIALIZING    : 10
}

var Event = function (sender) {
  this.sender = sender;
  this.listeners = [];
}

Event.prototype = {
  attach : function (callback, context) {
    for (var i = 0, il = this.listeners.length; i < il; i++) {
      if (this.listeners[i].callback === callback) return;
    }
    this.listeners.push({"callback": callback, "context": context || callback});
  },
  notify : function (args) {
    for (var i = 0, il = this.listeners.length; i < il; i++) {
      this.listeners[i].callback.call(this.listeners[i].context, this.sender, args);
    }
  }
};

Array.prototype.sum = function() {
    for (var i = 0, il = this.length, sum = 0; i < il; sum += this[i++]);
    return sum;
}

String.prototype.format = function(){
    var pattern = /\{\d+\}/g;
    var args = arguments;
    return this.replace(pattern, function(capture){ return args[capture.match(/\d+/)]; });
}

function bind(scope, fn) {
	return function() { return fn.apply(scope, Array.prototype.slice.call(arguments)); }
}

function formatBytes(bytes) {
    if (bytes === 0) return "0b";
    var s = ['bytes', 'kb', 'MB', 'GB', 'TB', 'PB'];
    var e = Math.floor(Math.log(bytes)/Math.log(1024));
    return (bytes/Math.pow(1024, Math.floor(e))).toFixed(2)+" "+s[e];
}

function clamp(val, min, max){
    return Math.max(min, Math.min(max, val))
}

function getValues(hash) {
    var list = [];
    for (var key in hash)
        list.push(hash[key]);
    return list;
}

var Url = {
    encode: function (string) {
        return escape(this._utf8_encode(string));
    },
    decode: function (string) {
        return this._utf8_decode(unescape(string));
    },
    _utf8_encode: function (string) {
        string = string.replace(/\r\n/g, "\n");
        var utftext = "";
        for (var n = 0; n < string.length; n++) {
            var c = string.charCodeAt(n);
            if (c < 128) {
                utftext += String.fromCharCode(c);
            }
            else if ((c > 127) && (c < 2048)) {
                utftext += String.fromCharCode((c >> 6) | 192);
                utftext += String.fromCharCode((c & 63) | 128);
            }
            else {
                utftext += String.fromCharCode((c >> 12) | 224);
                utftext += String.fromCharCode(((c >> 6) & 63) | 128);
                utftext += String.fromCharCode((c & 63) | 128);
            }
        }
        return utftext;
    },
    _utf8_decode: function (utftext) {
        var string = "";
        var i = 0;
        var c = c1 = c2 = 0;
        while (i < utftext.length) {
            c = utftext.charCodeAt(i);
            if (c < 128) {
                string += String.fromCharCode(c);
                i++;
            }
            else if ((c > 191) && (c < 224)) {
                c2 = utftext.charCodeAt(i + 1);
                string += String.fromCharCode(((c & 31) << 6) | (c2 & 63));
                i += 2;
            }
            else {
                c2 = utftext.charCodeAt(i + 1);
                c3 = utftext.charCodeAt(i + 2);
                string += String.fromCharCode(((c & 15) << 12) | ((c2 & 63) << 6) | (c3 & 63));
                i += 3;
            }
        }
        return string;
    }
}
