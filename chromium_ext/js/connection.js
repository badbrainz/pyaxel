// NOTE data sent over closed socket increases bufferedAmount.

var Connection = function(endpoint, retries, seconds) {
    this.connevent = new Event(this);
    this.msgevent = new Event(this);
    this.endpoint = endpoint;
    this.retries = ~~retries || 0;
    this.interval = (~~seconds || 5) * 1e3;
};

Connection.prototype.connect = function() {
    if (this.websocket)
        return;

    var nethandler = this.networkEventHandler;

    var sock = new WebSocket(this.endpoint);
    sock.addEventListener('open', nethandler.onopen.bind(this), false);
    sock.addEventListener('close', nethandler.onclose.bind(this), false);
    sock.addEventListener('error', nethandler.onerror.bind(this), false);
    sock.addEventListener('message', nethandler.onmessage.bind(this), false);

    this.websocket = sock;
//    this.tid = window.setInterval(nethandler.ontimeout.bind(this), this.interval);
//    if (this.retries)
//        this.attempt = 1;
};

Connection.prototype.send = function(msg) {
    if (!this.websocket)
        return;

    if (this.websocket.readyState === WebSocketEvent.OPEN)
        this.websocket.send(JSON.stringify(msg));
};

Connection.prototype.networkEventHandler = {
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
        var closeType = this.established ? ConnectionEvent.DISCONNECTED : ConnectionEvent.ERROR;
        delete this.established;
        if (this.websocket) {
            if (this.websocket.readyState === WebSocketEvent.OPEN)
                this.send({
                    cmd: ServerCommand.QUIT
                });
            delete this.websocket;
        }
        if (this.tid) {
            window.clearInterval(this.tid);
            delete this.tid;
        }
        this.connevent.notify({
            event: closeType,
            args: arguments
        });
    },

    ontimeout: function() {
        if (!this.established) {
            window.clearInterval(this.tid);
            delete this.tid;
            this.connevent.notify({
                event: ConnectionEvent.ERROR
            });
        }
    }
};
