function checkVersion() {
    //  var request = new XMLHttpRequest();
    //  request.open('GET', chrome.extension.getURL('manifest.json'), true);
    //  request.onreadystatechange = function() {
    //      if (request.readyState == XMLHttpRequest.DONE) {
    //          if (request.status == 200) {
    //              var manifest = JSON.parse(request.responseText);
    //              preferences.setItem('data.version', manifest.version);
    //              // check python script version
    //              request.open('GET', 'http://pyaxelws.googlecode.com/hg/version.txt', true);
    //              request.onreadystatechange = function() {
    //                  if (request.readyState == XMLHttpRequest.DONE) {
    //                      if (request.status == 200) {
    //                          var data = JSON.parse(request.responseText);
    //                          var build = data.version.split('.');
    //                          var loc_build = preferences.getItem('data.paversion').split('.');
    //                          if (loc_build[0] < build[0] || loc_build[1] < build[1] || loc_build[2] < build[2]) {
    //                              preferences.setItem('data.paversion', data.version); // assume responsible user
    //                              window.setTimeout(function() {
    //                                  var item = {
    //                                      title: 'Your version of pyaxelws appears to be outdated.',
    //                                      dllink: 'http://goo.gl/AEoTH',
    //                                      chlink: 'http://goo.gl/9fcSt',
    //                                      version: data.version
    //                                  };
    //                                  var value;
    //                                  var query = '?';
    //                                  for (var key in item)
    //                                      query += formatString('{0}={1}&', key, encodeURIComponent(item[key]));
    //                                  var url = chrome.extension.getURL('notification.html') + query;
    //                                  window.webkitNotifications.createHTMLNotification(url).show();
    //                              }, 10000);
    //                          }
    //                      }
    //                  }
    //              };
    //              request.send();
    //          }
    //      }
    //  };
    //  request.send();
    // issue request for version to server
    var host = getPreference('prefs.host');
    var port = getPreference('prefs.port');
    var address = formatString('ws://{0}:{1}', host, port);
    var connection = new Connection(address, Infinity);
    connection.connevent.attach(function(sender, response) {
        var event = response.event;
        if (event === ConnectionEvent.CONNECTED) {
            sender.send({
                cmd: ServerCommand.IDENT,
                arg: {
                    type: 'MGR',
                    info: ['version']
                }
            });
        }
    });
    connection.msgevent.attach(function(sender, response) {
        var event = response.event;
        if (event === MessageEvent.ACK) {
            var version = response.version;
            console.log(version);
        }
        sender.disconnect();
    });
    connection.connect();
}

function displayPage(file) {
    var url = chrome.extension.getURL(file);
    chrome.tabs.query({
        windowId: chrome.windows.WINDOW_ID_CURRENT,
        url: url
    }, function(tabs) {
        if (tabs.length == 0) chrome.tabs.create({
            active: true,
            url: url
        });
        else chrome.tabs.update(tabs[0].id, {
            active: true
        });
    });
}

// Badge Animation
var animation = null;
var context = null;
var canvas = null;
var width = 19;
var height = 19;
var clip = {
    x: 0,
    y: 0,
    z: 19,
    w: 10,
    px: 0,
    py: 4,
    sx: 19,
    sy: 10
};

var DownloadBadge = {
    foreimg: null,
    backimg: null,
    update: function() {
        var x = clip.x;
        clip.x = x === width - 1 ? 0 : x + 1;
    },
    paint: function() {
        chrome.browserAction.setIcon({
            imageData: context.getImageData(0, 0, width, height)
        });
    }
};

function drawBackground(obj) {
    context.clearRect(0, 0, width, height);
    context.drawImage(obj.backimg, 0, 0);
}

function drawForeground(obj) {
    var c = clip;
    context.drawImage(obj.foreimg, c.x, c.y, c.z, c.w, c.px, c.py, c.sx, c.sy);
}

function drawFrame(obj) {
    obj.update();
    drawBackground(obj);
    drawForeground(obj);
    obj.paint();
}

function Animation(speed, duration, props) {
    this._timer = new Timer(paramedFunction(drawFrame, this, props), speed);
    this.duration = duration;
    this.props = props;
}

Animation.prototype.start = function() {
    this._timer.start();
    if (this._timeout) window.clearTimeout(this._timeout);
    this._timeout = window.setTimeout(this.stop.bind(this), this.duration);
};

Animation.prototype.stop = function() {
    this._timer.stop();
    if (this._timeout) {
        window.clearTimeout(this._timeout);
        delete this._timeout;
    }
    drawBackground(this.props);
    this.props.paint();
};

function initAnim() {
    // python
    DownloadBadge.backimg = new Image(19, 19);
    DownloadBadge.backimg.src = 'images/19.png';
//    DownloadBadge.backimg = document.getElementById('python');

    // bits
//    DownloadBadge.foreimg = document.getElementById('bits');
    DownloadBadge.foreimg = new Image(38, 10);
    DownloadBadge.foreimg.src = 'images/bits.png';

//    canvas = document.getElementById('canvas');
    canvas = document.createElement('canvas');
    canvas.width = 19;
    canvas.height = 19;
    context = canvas.getContext('2d');
    animation = new Animation(120, 1700, DownloadBadge);
}

function init() {
    //  DownloadHistory.init();
    checkVersion();
    initAnim();
}

// Exports

function getPreference(key, obj) {
    throw 'Not implemented';
}

function setPreference(key, val) {
    throw 'Not implemented';
}

// Background
(function() {
    if (/win/i.test(window.navigator.platform)) {
        if (!window.localStorage['data.seenInstall']) {
            window.localStorage['data.seenInstall'] = true;
            chrome.tabs.create({
                'url': chrome.extension.getURL('alert.html'),
                'active': true
            });
        }
        return;
    }

    var preferences = new PropertyStorage(window.localStorage, {
        'data.version': 0,
        'data.paversion': '1.1.0',
        'prefs.host': '127.0.0.1',
        'prefs.downloads': 2,
        'prefs.bandwidth': 0,
        'prefs.port': 8002,
        'prefs.splits': 4,
        'prefs.path': ''
    });

    ConnectionManager.maxEstablished = preferences.getObject('prefs.downloads');
    ConnectionManager.host = preferences.getItem('prefs.host');
    ConnectionManager.port = preferences.getObject('prefs.port');

    preferences.connect('update', function(event) {
        var key = event.key;
        var keys = event.key.split('.')[0];
        switch (keys[1]) {
        case 'downloads':
            ConnectionManager.maxEstablished = +event.newVal;
            break;
        case 'host':
            ConnectionManager.host = event.newVal;
            break;
        case 'port':
            ConnectionManager.port = +event.newVal;
            break;
        }
    });

    var CommandHandler = {
        'add': function(arg) {
            DownloadManager.addJob(arg);
        },
        'pause': function(arg) {
            DownloadManager.pauseJob(arg);
        },
        'resume': function(arg) {
            DownloadManager.resumeJob(arg);
        },
        'cancel': function(arg) {
            DownloadManager.cancelJob(arg);
        },
        'retry': function(arg) {
            DownloadManager.retryJob(arg);
        },
        'remove': function(arg) {
            DownloadManager.removeJob(arg);
        },
        'update': function(arg) {
            return {
                reset: true,
                list: DownloadManager.getFullList()
            };
        },
        'clear': function(arg) {
            DownloadManager.eraseInactiveJobs();
        }
    };

    var ports = Object.create(null);

    function addPort(port) {
        ports[port.sender.tab.id] = port;

        port.onMessage.addListener(function(msg) {
            var cmd = msg.cmd;
            var arg = msg.arg;
            if (cmd in CommandHandler) {
                var result = CommandHandler[cmd](arg);
                if (result) port.postMessage(result);
            }
        });

        port.onDisconnect.addListener(removePort);
    }

    function removePort(port) {
        delete ports[port.sender.tab.id];
    }

    window['Background'] = {
        notify: function(list, reset) {
            var msg = {
                list: list
            };
            for (var port in ports) ports[port].postMessage(msg);

            animation.start();
        }
    };

    window['getPreference'] = function(key, obj) {
        return obj ? preferences.getObject(key) : preferences.getItem(key);
    }

    window['setPreference'] = function(key, val) {
        val === null ? preferences.unset(key) : preferences.setObject(key, val);
    }

    var ready = document.readyState;
	if (/loaded|complete/i.test(ready))
		init();
	else if (/loading/i.test(ready))
		document.addEventListener('DOMContentLoaded', init, false);
	else
		window.setTimeout(init, 0);

    // Chrome
    chrome.contextMenus.create({
        'documentUrlPatterns' : ['http://*/*', 'https://*/*', 'ftp://*/*'],
        'title': 'Download link',
        'contexts': ['link'],
        'onclick': function(info, tab) {
            DownloadManager.addJob(info.linkUrl);
        }
    });

    chrome.contextMenus.create({
        'documentUrlPatterns' : ['http://*/*', 'https://*/*', 'ftp://*/*'],
        'title': 'Queue link',
        'contexts': ['link'],
        'onclick': function(info, tab) {
            DownloadManager.addJob(info.linkUrl, true);
        }
    });

    chrome.extension.onConnect.addListener(addPort);
})();
