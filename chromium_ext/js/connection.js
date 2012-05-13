var Connection = function(endpoint, retries, seconds) {
    this.connevent = new Event(this);
    this.msgevent = new Event(this);
    this.endpoint = endpoint;
    this.retries = retries;
    this.interval = seconds * 1e3;
    //this.download = null;
};

Connection.prototype = {
    connect: function() {
        this.websocket = new WebSocket(this.endpoint);
        this.websocket.onopen = this.networkEventHandler.onopen.bind(this);
        this.websocket.onclose = this.networkEventHandler.onclose.bind(this);
        this.websocket.onerror = this.networkEventHandler.onerror.bind(this);
        this.websocket.onmessage = this.networkEventHandler.onmessage.bind(this);
        this.intervalID = setInterval((function() {
            if (!this.websocket || this.websocket.readyState !== ConnectionState.OPEN) {
                clearInterval(this.intervalID);
                this.connevent.notify({
                    event: ConnectionEvent.ERROR
                });
            }
        }).bind(this), this.interval);
    },

    send: function(msg) {
        if (!this.websocket) return;
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
        if (this.download.fname !== '') msg.arg.name = this.download.fname;
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
            if (this.websocket.readyState === ConnectionState.OPEN)
                this.disconnect();
            delete this.websocket;
        }
        if (this.intervalID) {
            clearInterval(this.intervalID);
            delete this.intervalID;
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

        onmessage: function(msg) {
            this.msgevent.notify(JSON.parse(msg.data));
        },

        onerror: function(msg) {
            this.connevent.notify({
                event: ConnectionEvent.ERROR,
                msg: msg
            });
        },

        onclose: function() {
            var event = this.established ? ConnectionEvent.DISCONNECTED : ConnectionEvent.ERROR;
            delete this.established;
            if (this.intervalID) {
                clearInterval(this.intervalID);
                delete this.intervalID;
            }
            this.connevent.notify({
                event: event
            });
        }
    }
};
