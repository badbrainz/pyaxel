/**
 NOTE
 * sending through closed socket increases bufferedAmount.
 */
var Connection = function(endpoint, retries, seconds) {
    this.connevent = new Event(this);
    this.msgevent = new Event(this);
    this.endpoint = endpoint;
    this.retries = ~~retries || 0;
    this.interval = (~~seconds || 5) * 1e3;
};

Connection.prototype = {
    connect: function() {
        if (this.websocket)
            return;

        var nethandler = this.networkEventHandler;

        var sock = new WebSocket(this.endpoint);
        sock.addEventListener('open', nethandler.onopen.bind(this), false);
        sock.addEventListener('close', nethandler.onclose.bind(this), false);
        sock.addEventListener('error', nethandler.onerror.bind(this), false);
        sock.addEventListener('message', nethandler.onmessage.bind(this), false);

        this.websocket = sock;
        this.tid = window.setInterval(nethandler.ontimeout.bind(this), this.interval);
        if (this.retries)
            this.attempt = 1;
    },

    send: function(msg) {
        if (!this.websocket)
            return;

        if (this.websocket.readyState === WebSocket.OPEN)
            this.websocket.send(JSON.stringify(msg));
    },

    prepare: function(payload) {
        this.download = payload;
    },

    resume: function() {
        var msg = {
            cmd: ServerCommand.START,
            arg: {
                url: this.download.url
            }
        };
        if (this.download.fname !== '')
            msg.arg.name = this.download.fname;
        this.send(msg);
    },

    pause: function() {
        var msg = {
            cmd: ServerCommand.STOP
        };
        this.send(msg);
    },

    abort: function() {
        var msg = {
            cmd: ServerCommand.ABORT
        };
        this.send(msg);
    },

    disconnect: function() {
        var msg = {
            cmd: ServerCommand.QUIT
        };
        this.send(msg);
    },

    destroy: function() {
        if (this.websocket) {
            if (this.websocket.readyState === WebSocket.OPEN)
                this.disconnect();
            delete this.websocket;
        }
        if (this.tid) {
            window.clearInterval(this.tid);
            delete this.tid;
        }
        this.download = null;
    },

    networkEventHandler: {
        onopen: function() {
            this.established = true;
            this.connevent.notify({
                event: ConnectionEvent.CONNECTED
            });
        },

        onmessage: function(event) {
            this.msgevent.notify(JSON.parse(event.data));
        },

        onerror: function(event) {
            this.connevent.notify({
                event: ConnectionEvent.ERROR,
                msg: event,
                args: arguments
            });
        },

        onclose: function(event) {
            var event = this.established ? ConnectionEvent.DISCONNECTED : ConnectionEvent.ERROR;
            delete this.established;
            if (this.tid) {
                window.clearInterval(this.tid);
                delete this.tid;
            }
            this.connevent.notify({
                event: event,
                args: arguments
            });
        },

        ontimeout: function() {
//            if (!websocket || websocket.readyState !== WebSocket.OPEN) {
            if (!this.established) {
                window.clearInterval(this.tid);
                delete this.tid;
//                if (this.attempt)
                this.connevent.notify({
                    event: ConnectionEvent.ERROR
                });
            }
        }
    }
};
