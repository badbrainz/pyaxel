var Connection = function(endpoint, retries, timeout) {
    this.connevent = new Event(this);
    this.msgevent = new Event(this);
    this.timeout = timeout * 1e3;
    this.intervalID = null;
    this.retries = retries;
    this.websocket = null;
    this.download = null;
    this.established = false;
    this.endpoint = endpoint;
}

Connection.prototype = {
    connect: function() {
        this.websocket = new WebSocket(this.endpoint);
        this.websocket.onopen = bind(this, this.networkEventHandler.onopen);
        this.websocket.onclose = bind(this, this.networkEventHandler.onclose);
        this.websocket.onerror = bind(this, this.networkEventHandler.onerror);
        this.websocket.onmessage = bind(this, this.networkEventHandler.onmessage);
        this.intervalID = setInterval(bind(this, function() {
            if (!this.websocket || this.websocket.readyState === ConnectionState.CLOSED) {
                clearInterval(this.intervalID);
                this.connevent.notify({event:ConnectionEvent.ERROR});
            }
        }), this.timeout);
    },

    send: function(msg) {
        if (!this.websocket)
            return;
        this.websocket.send(JSON.stringify(msg));
        /*/
        var args = [];

        for (var i=1, len=arguments.length; i<len; i++)
          args.push(arguments[i]);

        if (this[method])
          this[method].apply(args);
        //else if (this.nomethod)
        //  this.nomethod(args);
        //*/
    },

    prepare: function(download) {
        this.download = download;
    },

    abort: function() {
        var msg = {
            cmd : ServerCommand.ABORT,
            arg : ""
        };
        this.send(msg);
    },

    pause: function() {
        var msg = {
            cmd : ServerCommand.PAUSE,
            arg : ""
        };
        this.send(msg);
    },

    resume: function() {
        var msg = {
            cmd : ServerCommand.START,
            arg : {
                url : this.download.url
            }
        };
        if (this.download.fname !== "")
            msg.arg.name = this.download.fname;
        this.send(msg);
    },

    disconnect: function() {
        //this.websocket.close();
        //*/
        var msg = {
            cmd : ServerCommand.QUIT,
            arg : ""
        };
        this.send(msg);
        //*/
    },

    destroy: function() {
        if (this.websocket) {
            this.disconnect();
            delete this.websocket;
            this.websocket = null;
        }
        if (this.intervalID)
            clearInterval(this.intervalID);
    },

    networkEventHandler: {
        onopen: function() {
            this.established = true;
            this.connevent.notify({event:ConnectionEvent.CONNECTED});
        },
        onmessage: function(msg) {
            this.msgevent.notify(JSON.parse(msg.data));
        },
        /* */
        onerror: function(msg) {
            this.connevent.notify({event:ConnectionEvent.ERROR, msg:msg});
        },
        onclose: function() {
            var event = this.established ? ConnectionEvent.DISCONNECTED : ConnectionEvent.ERROR;
            this.connevent.notify({event:event});
        }
    }
};
