// WARN all socket connections made through non-secure layer

var ports = {};
var job_map = {/* [job.id] = connection.id */};
var settings = new Settings(window.localStorage, {
    'data.paversion': '1.1.0',
    'data.version': 0,
    'prefs.delay': 20,
    'prefs.downloads': 2,
    'prefs.host': '127.0.0.1',
    'prefs.log': 0,
    'prefs.options': 0,
    'prefs.output': 1,
    'prefs.path': '',
    'prefs.port': 8002,
    'prefs.reconnect': 5,
    'prefs.speed': 0,
    'prefs.splits': 4
});
var activity_log;

function init() {
    if (!window.localStorage['data.seenInstall']) {
        window.localStorage['data.seenInstall'] = true;
        window.localStorage['data.lastUpdate'] = Date.now();
    }

    var request = new XMLHttpRequest();
    request.open('GET', chrome.extension.getURL('manifest.json'), true);
    request.onreadystatechange = function() {
        if (request.readyState == XMLHttpRequest.DONE) {
            if (request.status == 200) {
                var manifest = JSON.parse(request.responseText);
                window.localStorage['data.version'] = manifest.version;
            }
        }
    }
    request.send();

//    history.init();

    DownloadBadge.backimg = new Image(19, 19);
    DownloadBadge.backimg.src = 'images/19.png';
    DownloadBadge.foreimg = new Image(38, 10);
    DownloadBadge.foreimg.src = 'images/bits.png';
    canvas = document.createElement('canvas');
    canvas.width = 19;
    canvas.height = 19;
    context = canvas.getContext('2d');
    animation = new Animation(120, 1700, DownloadBadge);

    client.events.connect('error', error_handler);
    client.events.connect('message', message_handler);
    client.events.connect('connected', connect_handler);
    client.events.connect('disconnected', disconnect_handler);
    client.maxEstablished = settings.getObject('prefs.downloads');
    client.serverAddress = formatString('ws://{0}:{1}',
        settings.getItem('prefs.host'), settings.getItem('prefs.port'));

    chrome.contextMenus.create({
        'documentUrlPatterns' : ['http://*/*', 'https://*/*', 'ftp://*/*'],
        'title': 'Download link',
        'contexts': ['link'],
        'onclick': function(info, tab) {
            runCommand('add', info.linkUrl);
        }
    });
    chrome.contextMenus.create({
        'documentUrlPatterns' : ['http://*/*', 'https://*/*', 'ftp://*/*'],
        'title': 'Queue link',
        'contexts': ['link'],
        'onclick': function(info, tab) {
            runCommand('add', info.linkUrl, true);
        }
    });
    chrome.extension.onConnect.addListener(addPort);
//    chrome.extension.onConnectExternal.addListener(addPort);

    activity_log = settings.getObject('prefs.log');
}

function notifyPorts(msg) {
    for (var port in ports)
        ports[port].postMessage(msg);
};

function addPort(port) {
    var name = port.name || port.sender.id;
    if (ports[name])
        ports[name].disconnect();
    ports[name] = port;
    port.onMessage.addListener(function(list_args, portImpl) {
        var result = runCommand.apply(null, list_args);
        if (result)
            port.postMessage(result);
    });
    port.onDisconnect.addListener(removePort);
}

function removePort(port) {
    delete ports[port.name || port.sender.id];
}

function runCommand(cmd, var_args) {
    switch (arguments[0]) {
    case 'add':
        if (!arguments[1])
            return;

        var expr = matchPropertyExpression('name', arguments[1]);
        if (jobqueue.search('unassigned').some(expr) && jobqueue.search('active').some(expr))
            return;

        if (/\.meta4$/i.test(parseUri(arguments[1]).fileName)) {
            var args = arguments;
            io.http(arguments[1], function(xml) {
                try {
                    var namespace = 'urn:ietf:params:xml:ns:metalink';
                    var doc = xml.getElementsByTagNameNS(namespace,'metalink');
                    var files = Array.prototype.slice.call(doc[0].getElementsByTagNameNS(namespace,'file'));
                    for (var i = 0; i < files.length; i++) {
                        var download = jobqueue.new();

                        download.search = Array.prototype.slice.call(files[i].getElementsByTagNameNS(namespace,'url'));
                        for (var j = 0; j < download.search.length; j++)
                            download.search[j] = download.search[j].textContent;

                        var hash = Array.prototype.slice.call(files[i].getElementsByTagNameNS(namespace,'hash'));
                        for (var j = 0; j < hash.length; j++) {
                            if (hash[j].attributes.getNamedItem('type').value === 'md5') {
                                download.checksum = hash[j].textContent;
                                break;
                            }
                        }

                        download.date = today();
                        download.url = args[1];
                        download.status = DownloadStatus.QUEUED;
                        jobqueue.add(download, args[2]);
                        notifyPorts([download]);
                        if (!args[2])
                            client.establish();
                    }
                }
                catch (err) {
                    console.log(err.stack)
                }
            });
        }
        else {
            var download = jobqueue.new();
            download.date = today();
            download.url = arguments[1];
            download.search = arguments[1];
            download.status = DownloadStatus.QUEUED;
            jobqueue.add(download, arguments[2]);
            notifyPorts([download]);
            if (!arguments[2])
                client.establish();
        }
        break;

    case 'cancel':
        client.send(job_map[arguments[1]], {
            'cmd': ServerCommand.ABORT
        });
        break;

    case 'pause':
        client.send(job_map[arguments[1]], {
            'cmd': ServerCommand.STOP
        });
        break;

    case 'remove':
        jobqueue.remove(arguments[1]);
        notifyPorts(jobqueue.search('all'));
        break;

    case 'resume':
        var download = jobqueue.search(arguments[1]);
        if (download)
            client.send(job_map[arguments[1]], {
                'cmd': ServerCommand.START,
                'arg': {
                    'url': download.search,
                    'conf': getDownloadConfig()
                }
            });
        break;

    case 'retry':
        var download = jobqueue.search('completed', arguments[1]) ||
            jobqueue.search('unassigned', arguments[1]);
        if (download) {
            download.status = DownloadStatus.QUEUED;
            download.date = today();
            delete download.log;
            delete download.chunks;
            delete download.progress;
            jobqueue.retry(download.id);
            notifyPorts([download]);
            if (jobqueue.size())
                client.establish();
        }
        break;

    case 'purge':
        jobqueue.purge();
        notifyPorts(jobqueue.search('all'));
        break;

    case 'search':
        return jobqueue.search(arguments[1]);
        break;

    default:
        console.error('unknown command \'%s\'', arguments[0]);
        break;
    }
}

function connect_handler(connection) {
    var job = jobqueue.get();
    if (!job) {
        connection.send({'cmd': ServerCommand.QUIT});
        return;
    }

    job_map[job.id] = connection.id;

    connection.payload = job;
    connection.send({'cmd': ServerCommand.IDENT});
}

function message_handler(connection, response) {
    var download = connection.payload;

    switch (response.event) {
    case MessageEvent.INITIALIZING:
        download.status = DownloadStatus.CONNECTING;
        jobqueue.jobStarted(download);
        break;

    case MessageEvent.ACK:
        download.status = DownloadStatus.QUEUED;
        connection.send({
            'cmd': ServerCommand.START,
            'arg': {
                'url': download.search,
                'conf': getDownloadConfig()
            }
        });
        break;

    case MessageEvent.OK:
        download.status = DownloadStatus.INITIALIZING;
        download.name = response.name;
        download.size = response.size;
        download.type = response.type;
        download.chunks = response.chunks;
        download.progress = response.progress;
        jobqueue.jobStarted(download);
        break;

    case MessageEvent.PROCESSING:
        download.status = DownloadStatus.IN_PROGRESS;
        download.progress = response.progress;
        download.speed = response.rate;
        animation.start();
        break;

    case MessageEvent.STOPPED:
        download.status = DownloadStatus.PAUSED;
        break;

    case MessageEvent.CLOSING:
        download.status = DownloadStatus.CLOSING;
        break;

    case MessageEvent.COMPLETED:
        if ('checksum' in download) {
            connection.send({
                'cmd': ServerCommand.CHECK,
                'arg': {
                    'type': 'md5',
                    'checksum': download.checksum
                }
            });
        }
        else {
            download.status = DownloadStatus.COMPLETE;
            jobqueue.jobCompleted(download);
            var job = jobqueue.get();
            if (!job)
                connection.send({'cmd': ServerCommand.QUIT});
            else {
                delete job_map[download.id];
                job_map[job.id] = connection.id;
                connection.payload = job;
                connection.send({
                    'cmd': ServerCommand.START,
                    'arg': {
                        'url': job.search,
                        'conf': getDownloadConfig()
                    }
                });
            }
        }
        break;

    case MessageEvent.VERIFIED:
        download.status = DownloadStatus.COMPLETE;
        jobqueue.jobCompleted(download);
        var job = jobqueue.get();
        if (!job)
            connection.send({'cmd': ServerCommand.QUIT});
        else {
            delete job_map[download.id];
            job_map[job.id] = connection.id;
            connection.payload = job;
            connection.send({
                'cmd': ServerCommand.START,
                'arg': {
                    'url': job.search,
                    'conf': getDownloadConfig()
                }
            });
        }
        break;

    case MessageEvent.INCOMPLETE:
        download.status = DownloadStatus.CANCELLED;
        jobqueue.jobStopped(download);
        var job = jobqueue.get();
        if (!job)
            connection.send({'cmd': ServerCommand.QUIT});
        else {
            delete job_map[download.id];
            job_map[job.id] = connection.id;
            connection.payload = job;
            connection.send({
                'cmd': ServerCommand.START,
                'arg': {
                    'url': job.search,
                    'conf': getDownloadConfig()
                }
            });
        }
        break;

    case MessageEvent.RESERVED:
        download.status = DownloadStatus.VERIFYING;
        break;

    case MessageEvent.BAD_REQUEST:
        console.error('server response:', response.log);
    case MessageEvent.ERROR:
        connection.send({'cmd': ServerCommand.ABORT});
    case MessageEvent.INVALID:
        download.status = DownloadStatus.ERROR;
        jobqueue.jobFailed(download);
        var job = jobqueue.get();
        if (!job)
            connection.send({'cmd': ServerCommand.QUIT});
        else {
            delete job_map[download.id];
            job_map[job.id] = connection.id;
            connection.payload = job;
            connection.send({
                'cmd': ServerCommand.START,
                'arg': {
                    'url': job.search,
                    'conf': getDownloadConfig()
                }
            });
        }
        break;
    }

    download.log = activity_log && response.log;

    notifyPorts([download]);
}

function disconnect_handler(connection) {
    // TODO reflect connection state

    if (connection.payload) {
        delete job_map[connection.payload.id];
        delete connection.payload.log;
        if (connection.payload.status == DownloadStatus.PAUSED)
            connection.payload.status = DownloadStatus.CANCELLED;
        notifyPorts([connection.payload]);
    }
    else
        notifyPorts(jobqueue.search('all'));

    if (jobqueue.size())
        client.establish();
}

function error_handler(connection) {
    // TODO reflect connection state

    if (connection.payload) {
        delete job_map[connection.payload.id];
        delete connection.payload.log;
        notifyPorts([connection.payload]);
    }
    else
        notifyPorts(jobqueue.search('all'));
}

function displayPage(file) {
    chrome.tabs.query({
        'windowId': chrome.windows.WINDOW_ID_CURRENT,
        'url': chrome.extension.getURL(file)
    }, function(tabs) {
        if (tabs.length == 0) chrome.tabs.create({
            'active': true,
            'url': chrome.extension.getURL(file)
        });
        else chrome.tabs.update(tabs[0].id, {
            'active': true
        });
    });
}

function getPreference(key, obj) {
    return obj ? settings.getObject(key) : settings.getItem(key);
}

function setPreference(key, val) {
    val === null ? settings.unset(key) : settings.setObject(key, val);
}

function getDownloadConfig() {
    return {
        'alternate_output': settings.getObject('prefs.output'),
        'download_path': settings.getItem('prefs.path'),
        'reconnect_delay': settings.getObject('prefs.delay'),
        'max_speed': settings.getObject('prefs.speed'),
        'max_reconnect': settings.getObject('prefs.reconnect'),
        'num_connections': settings.getObject('prefs.splits')
    };
}


settings.connect('update', function(event) {
    var keys = event.key.split('.');
    if (keys[0] == 'prefs') {
        switch (keys[1]) {
        case 'downloads':
            client.maxEstablished = +event.newVal;
            break;

        case 'host':
            client.serverAddress = formatString('ws://{0}:{1}',
                event.newVal, settings.getObject('prefs.port'));
            break;

        case 'port':
            client.serverAddress = formatString('ws://{0}:{1}',
                settings.getItem('prefs.host'), +event.newVal);
            break;

        case 'log':
            activity_log = +event.newVal;
            break;
        }
    }
});

(function() {
	if (/loaded|complete/i.test(document.readyState))
		init();
	else if (/loading/i.test(document.readyState))
		document.addEventListener('DOMContentLoaded', init, false);
	else
		window.setTimeout(init, 0);
})();
