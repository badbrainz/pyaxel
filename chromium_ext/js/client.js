var client = {};
client.activeCount = 0;
client.activeCalls = {};
client.maxEstablished = 1;
client.serverAddress = '';
client.events = new Broadcaster('connected','disconnected','message','error');

client.establish = function() {
    if (client.activeCount >= client.maxEstablished)
        return;

    var connection = new Connection(client.serverAddress);
    connection.id = id();
    connection.connevent.attach(client.socketHandler.eventConnect);
    connection.msgevent.attach(client.socketHandler.eventMessage);
    connection.connect();
};

client.send = function(id, msg) {
    if (id in client.activeCalls)
        client.activeCalls[id].send(msg);
};

client.socketHandler = {
    eventConnect: function(connection, response) {
        switch (response.event) {
        case ConnectionEvent.CONNECTED:
            client.activeCalls[connection.id] = connection;
            client.activeCount++;
            client.events.send('connected', connection);
            break;

        case ConnectionEvent.DISCONNECTED:
            delete client.activeCalls[connection.id];
            client.activeCount--;
            client.events.send('disconnected', connection);
            break;

        case ConnectionEvent.ERROR:
            delete client.activeCalls[connection.id];
            client.activeCount--;
            client.events.send('error', connection);
            break;
        }
    },

    eventMessage: function(connection, response) {
        client.events.send('message', connection, response);
    }
};
