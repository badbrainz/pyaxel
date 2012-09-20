/* transfer codes (internal) */
var DownloadStatus = {
    QUEUED: 0,
    INITIALIZING: 1,
    IN_PROGRESS: 2,
    COMPLETE: 3,
    CANCELLED: 4,
    PAUSED: 5,
    UNDEFINED: 6,
    CONNECTING: 7,
    ERROR: 8,
    CLOSING: 9,
    VERIFYING: 10
};

/* serv commands */
var ServerCommand = {
    IDENT: 0,
    START: 1,
    STOP: 2,
    ABORT: 3,
    QUIT: 4,
    CHECK: 5
};

/* serv reply codes */
var MessageEvent = {
    INITIALIZING: 0,
    ACK: 1,
    OK: 2,
    PROCESSING: 3,
    COMPLETED: 4,
    CLOSING: 5,
    INCOMPLETE: 6,
    STOPPED: 7,
    INVALID: 8,
    BAD_REQUEST: 9,
    ERROR: 10,
    UNDEFINED: 11,
    RESERVED: 12,
    VERIFIED: 13
};

/* socket readyState codes */
var WebSocketEvent = {
    CONNECTING: 0,
    OPEN: 1,
    CLOSING: 2,
    CLOSED: 3
};

/* internal */
var ConnectionEvent = {
    CONNECTED: 0,
    DISCONNECTED: 1,
    ERROR: 2
};

function id() {
    return id._++;
}
id._ = 0;

function sum(list) {
    var sum = 0;
    for (var i = 0, il = list.length; i < il; sum += list[i++]);
    return sum;
}

function clamp(val, min, max) {
    return Math.max(min, Math.min(max, val));
}

function formatString(tpl, args) {
    var vals = Array.prototype.slice.call(arguments, 1);
    return arguments[0].replace(/\{\d+\}/g, function(capture) {
        return vals[capture.match(/\d+/)];
    });
}

function formatBytes(bytes) {
    if (!bytes) return '';
    var s = ['bytes', 'kb', 'MB', 'GB', 'TB', 'PB'];
    var e = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, Math.floor(e))).toFixed(2) + ' ' + s[e];
}

function addQueryPart(url, map) {
    var query = url[url.length - 1] !== '?' ? '?' : '';
    for (var key in map)
        query += formatString('{0}={1}&', key, encodeURIComponent(map[key]));
    return url + query;
}

function getValues(hash) {
    var list = [];
    for (var key in hash) list.push(hash[key]);
    return list;
}

function copy(target, props) {
    if (props) {
        for (var prop in props) {
            var p = props[prop];
            if (p && p.constructor && p.constructor === Object)
                target[prop] = arguments.callee({}, p);
            else target[prop] = p;
        }
    }
    return target;
}

function paramedFunction(args) {
    var callback = arguments[0];
    var scope = arguments[1];
    var args = Array.prototype.slice.call(arguments, 2);
    return function() {
        callback.apply(scope, args);
    }
}

function matchPropertyExpression(key, val) {
    return function(obj) {
        return obj[key] === val;
    }
}

function today() {
    var date = new Date();
    var months = [
        "Jan","Feb","Mar","Apr","May","Jun",
        "Jul","Aug","Sep","Oct","Nov","Dec"
    ];
    return months[date.getMonth()] + " " + date.getDate() + ", " + date.getFullYear();
}

function typeOf(obj) {
    var v;
    if (v = /(undefined|string|number|boolean)/.exec(typeof obj)) return v[1];
    var type = Object.prototype.toString.call( /** @type {Object} */ (obj)).toLowerCase();
    return /\b([a-z]+).$/i.exec(type)[1];
}

var Url = {
    encode: function(string) {
        return escape(this._utf8_encode(string));
    },

    decode: function(string) {
        return this._utf8_decode(unescape(string));
    },

    _utf8_encode: function(string) {
        string = string.replace(/\r\n/g, '\n');
        var utftext = '';
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

    _utf8_decode: function(utftext) {
        var string = '';
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
};
