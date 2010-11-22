var ConnectionManager = {}

ConnectionManager.activeCount = 0;
ConnectionManager.activeCalls = {}

ConnectionManager.establishConnection = function() {
    if (ConnectionManager.activeCount >= Preferences.getObject("prefs.downloads"))
        return;

    if (!DownloadManager.hasJobs())
        return;

    ConnectionManager.activeCount++;

    var connection = ConnectionFactory.createConnection();
    connection.connevent.attach(ConnectionManager.onconnevent);
    connection.msgevent.attach(ConnectionManager.onmsgevent);
    connection.connect();
}

ConnectionManager.abort = function(id) {
    if (id in ConnectionManager.activeCalls)
        ConnectionManager.activeCalls[id].abort();
}

ConnectionManager.pause = function(id) {
    if (id in ConnectionManager.activeCalls)
        ConnectionManager.activeCalls[id].pause();
}

ConnectionManager.resume = function(id) {
    if (id in ConnectionManager.activeCalls)
        ConnectionManager.activeCalls[id].resume();
}

ConnectionManager.assignOrDisconnect = function(connection) {
    var job = DownloadManager.getJob();
    if (job) {
        delete ConnectionManager.activeCalls[connection.download.id];
        ConnectionManager.activeCalls[job.id] = connection;
        connection.prepare(job);
        connection.resume();
    }
    else connection.disconnect();
}

ConnectionManager.onmsgevent = function(sender, response) {
    var download = sender.download;
    var event = response.event;

    if (event === MessageEvent.INITIALIZING) {
        download.status = DownloadStatus.CONNECTING; // fix this
        DownloadManager.jobStarted(download);
    }

    else if (event === MessageEvent.ACK) {
        sender.resume();
    }

    else if (event === MessageEvent.OK) {
        download.status = DownloadStatus.INITIALIZING;
        download.size = formatBytes(response.size);
        download.fname = response.name;
        download.fsize = response.size;
        download.ftype = response.type;
        download.chunks = response.chunks;
        download.progress = response.progress;
        DownloadManager.jobStarted(download);
    }

    else if (event === MessageEvent.BAD_REQUEST) {
        download.status = DownloadStatus.CANCELLED;
        DownloadManager.jobCompleted(download);
        sender.abort();
        console.log("Bad request:", response.data)
    }

    else if (event === MessageEvent.ERROR) {
        if (download) {
            download.status = DownloadStatus.CANCELLED;
            DownloadManager.jobCompleted(download);
        }
        sender.abort();
        console.log("Error:", response.data)
    }

    else if (event === MessageEvent.PROCESSING) {
        download.status = DownloadStatus.IN_PROGRESS;
        download.percentage = Math.floor(response.data.prog.sum() * 100 / download.fsize);
        download.progress = response.data.prog;
        download.speed = response.data.rate;
    }

    else if (event === MessageEvent.INCOMPLETE) {
        download.status = DownloadStatus.CANCELLED;
        DownloadManager.jobCompleted(download);
        ConnectionManager.assignOrDisconnect(sender);
    }

    else if (event === MessageEvent.END) {
        download.status = DownloadStatus.COMPLETE;
        DownloadManager.jobCompleted(download);
        ConnectionManager.assignOrDisconnect(sender);
    }

    else if (event === MessageEvent.STOPPED) {
        download.status = DownloadStatus.PAUSED;
    }

    DownloadManager.update(download);
}

ConnectionManager.onconnevent = function(sender, response) {
    var event = response.event;
    var download = sender.download;

    if (event === ConnectionEvent.CONNECTED) {
        var job = DownloadManager.getJob();
        if (!job) { // user removed job before connection was established
            sender.destroy();
            return;
        }

        ConnectionManager.activeCalls[job.id] = sender;
        sender.prepare(job);
        sender.send({cmd:"IDENT",arg:{type:"WKR"}});
    }

    else if (event === ConnectionEvent.DISCONNECTED) {
        delete ConnectionManager.activeCalls[download.id];
        ConnectionManager.activeCount--;
        ConnectionManager.establishConnection();
    }

    else if (event === ConnectionEvent.ERROR) {
        if (download && download.id in ConnectionManager.activeCalls)
            delete ConnectionManager.activeCalls[download.id];
        sender.destroy();
        ConnectionManager.activeCount--;
        console.log("Connection error...");
    }
}
