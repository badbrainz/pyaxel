var ConnectionManager = {};

ConnectionManager.activeCount = 0;
ConnectionManager.activeCalls = {};
ConnectionManager.maxEstablished = 1;
ConnectionManager.host = '127.0.0.1';
ConnectionManager.port = 8002;

ConnectionManager.establishConnection = function() {
    if (ConnectionManager.activeCount >= ConnectionManager.maxEstablished)
        return;

    if (!DownloadManager.hasJobs())
        return;

    ConnectionManager.activeCount++;

    var host = getPreference('prefs.host');
    var port = getPreference('prefs.port');
    var address = formatString('ws://{0}:{1}', ConnectionManager.host, ConnectionManager.port);
    var connection = new Connection(address);
    connection.connevent.attach(ConnectionManager.onconnevent);
    connection.msgevent.attach(ConnectionManager.onmsgevent);
    connection.connect();
};

ConnectionManager.abort = function(id) {
    if (id in ConnectionManager.activeCalls)
        ConnectionManager.activeCalls[id].abort();
};

ConnectionManager.pause = function(id) {
    if (id in ConnectionManager.activeCalls)
        ConnectionManager.activeCalls[id].pause();
};

ConnectionManager.resume = function(id) {
    if (id in ConnectionManager.activeCalls)
        ConnectionManager.activeCalls[id].resume();
};

ConnectionManager.assignOrDisconnect = function(connection) {
    var job = DownloadManager.getJob();
    if (job) {
        delete ConnectionManager.activeCalls[connection.download.id];
        ConnectionManager.activeCalls[job.id] = connection;
        connection.prepare(job);
        connection.resume();
    }
    else connection.disconnect();
};

ConnectionManager.onmsgevent = function(sender, response) {
    var download = sender.download;

    switch (response.event) {
    case MessageEvent.INITIALIZING:
        download.status = DownloadStatus.CONNECTING; // fix this
        DownloadManager.jobStarted(download);
        break;

    case MessageEvent.ACK:
        sender.resume();
        break;

    case MessageEvent.OK:
        download.status = DownloadStatus.INITIALIZING;
        download.size = formatBytes(response.size);
        download.fname = response.name;
        download.fsize = response.size;
        download.ftype = response.type;
        download.chunks = response.chunks;
        download.progress = response.progress;
        DownloadManager.jobStarted(download);
        break;

    case MessageEvent.BAD_REQUEST:
        download.status = DownloadStatus.CANCELLED;
        DownloadManager.jobCompleted(download);
        sender.abort();
        break;

    case MessageEvent.ERROR:
        if (download) {
            download.status = DownloadStatus.CANCELLED;
            DownloadManager.jobCompleted(download);
        }
        sender.abort();
        break;

    case MessageEvent.PROCESSING:
        download.status = DownloadStatus.IN_PROGRESS;
        download.percentage = download.fsize ? Math.floor(sum(response.progress) * 100 / download.fsize) : 0;
        download.progress = response.progress;
        download.speed = response.rate;
        break;

    case MessageEvent.INCOMPLETE:
        download.status = DownloadStatus.CANCELLED;
        DownloadManager.jobCompleted(download);
        ConnectionManager.assignOrDisconnect(sender);
        break;

    case MessageEvent.END:
        download.status = DownloadStatus.COMPLETE;
        DownloadManager.jobCompleted(download);
        ConnectionManager.assignOrDisconnect(sender);
        break;

    case MessageEvent.STOPPED:
        download.status = DownloadStatus.PAUSED;
        break;
    }

    DownloadManager.update(download);
};

ConnectionManager.onconnevent = function(sender, response) {
    var download = sender.download;

    switch (response.event) {
    case ConnectionEvent.CONNECTED:
        var job = DownloadManager.getJob();

        // user removed job before connection was established.
        // NOTE ui shouldn't allow it anyway.
        if (!job) {
            sender.destroy();
            return;
        }

        ConnectionManager.activeCalls[job.id] = sender;
        sender.prepare(job);
        sender.send({
            cmd: ServerCommand.IDENT,
            arg: {
                type: 'WKR'
            }
        });
        break;

    case ConnectionEvent.DISCONNECTED:
        delete ConnectionManager.activeCalls[download.id];
        sender.destroy();
        ConnectionManager.activeCount--;
        ConnectionManager.establishConnection();
        break;

    case ConnectionEvent.ERROR:
        if (download && download.id in ConnectionManager.activeCalls)
            delete ConnectionManager.activeCalls[download.id];
        sender.destroy();
        ConnectionManager.activeCount--;
        break;
    }
};
