// misc
function loadManifestInfo() {
    var manifest = null;
    var request = new XMLHttpRequest();
    request.open("GET", chrome.extension.getURL("manifest.json"), false);
    request.onreadystatechange = function() {
        if (this.readyState == XMLHttpRequest.DONE) {
            manifest = JSON.parse(this.responseText);
            Preferences.setItem("data.version", manifest.version);
        }
    };
    request.send();
}

function checkversion() {
    var request = new XMLHttpRequest();
    request.open("GET", "http://pyaxelws.googlecode.com/hg/version.txt", false);
    request.onreadystatechange = function() {
        if (this.readyState == XMLHttpRequest.DONE) {
            var data = JSON.parse(this.responseText);
            if (Preferences.getItem("data.paversion") !== data.version) {
                Preferences.setItem("data.paversion", data.version); // don't annoy the user next time
                setTimeout(function() {
                    var item = {
			            title : "Your version of pyaxelws appears to be outdated.",
			            dllink: "http://goo.gl/scuqi",
			            chlink: "http://goo.gl/9fcSt",
			            version: data.version
		            };
                    var value;
                    var query = "?";
                    for (var key in item) {
	                    if (value=item[key])
	                        query += "{0}={1}&".format(key, encodeURIComponent(value));
                    }
                    var url = chrome.extension.getURL("notification.html") + query;
                    webkitNotifications.createHTMLNotification(url).show();
                }, 10000);
            }
        }
    };
    request.send();
}

// Animation
var width = 19;
var height = 19;
var canvas = null;
var context = null;
var props = {
    foreimg: null,
    backimg: null,
    clip:  {
        x:0,
        y:0,
        z:19,
        w:10,
        px:0,
        py:4,
        sx:19,
        sy:10
    },
    update: function() {
        var x = props.clip.x;
        props.clip.x = x === width-1 ? 0 : x+1;
    },
    paint: function() {
        chrome.browserAction.setIcon({imageData:context.getImageData(0, 0, width, height)});
    }
};
var animation = null;

function Animation(speed, duration, props) {
    this._startTimer = new Timer(bind(this, this._drawFrame), speed);
    this._timeoutID = null;
    this.duration = duration;
    this.backimg = props.backimg;
    this.foreimg = props.foreimg;
    this.update = props.update;
    this.paint = props.paint;
    this.clip = props.clip;
}

Animation.prototype = {
    _drawBackground: function() {
        context.clearRect(0, 0, width, height);
        context.drawImage(this.backimg, 0, 0);
    },

    _drawForeground: function() {
        var c = this.clip;
        context.drawImage(this.foreimg, c.x, c.y, c.z, c.w, c.px, c.py, c.sx, c.sy);
    },

    _drawFrame: function() {
        this.update();
        this._drawBackground();
        this._drawForeground();
        this.paint();
    },

    start: function() {
        this._startTimer.start()
        if (this._timeoutID)
            clearTimeout(this._timeoutID);
        this._timeoutID = setTimeout(bind(this, this.stop), this.duration);
    },

    stop: function() {
        this._startTimer.stop();
        this._drawBackground();
        this.paint();
    }
}

// context menu
chrome.contextMenus.create({
    //"targetUrlPatterns" : []
    "title"     : "Save Link Using PyAxel",
    "contexts"  : ["link"],
    "onclick"   : function(info, tab) {
        Background.queueDownload(info.linkUrl);
    }
});

// browser action
chrome.browserAction.onClicked.addListener(function(tab) {
  var url = chrome.extension.getURL("downloads.html"), len = url.length;
  chrome.tabs.getAllInWindow(null, function(wndTabs) {
    for (var i = 0, il = wndTabs.length; i < il; i++) {
      if (url === wndTabs[i].url.substr(0,len)) {
        chrome.tabs.update(wndTabs[i].id, {selected:true});
        return;
      }
    }
    chrome.tabs.create({selected:true,url:url});
  });
});

// Background
var Background = {}
Background.ports = {}

Background.addPort = function(port) {
    Background.ports[port.sender.tab.id] = port;

    port.onMessage.addListener(function(msg) {
        if (msg.cmd === "cancel")
            DownloadManager.cancelJob(msg.args);
        else if (msg.cmd === "remove")
            DownloadManager.remove(msg.args);
        else if (msg.cmd === "pause")
            DownloadManager.pauseJob(msg.args);
        else if (msg.cmd === "resume")
            DownloadManager.resumeJob(msg.args);
        else if (msg.cmd === "update")
            port.postMessage({reset:true, list:DownloadManager.getFullList()});
        else if (msg.cmd === "add")
            Background.queueDownload(msg.args);
        else if (msg.cmd === "clear")
            DownloadManager.eraseInactiveJobs();
    });

    port.onDisconnect.addListener(Background.removePort);
}

Background.removePort = function(port) {
    delete Background.ports[port.sender.tab.id];
}

Background.notify = function(list, reset) {
    for (var port in Background.ports)
        Background.ports[port].postMessage({reset:reset||false, list:list});
    animation.start();
}

Background.queueDownload = function(url) {
    DownloadManager.addJob(url);
}

chrome.extension.onConnect.addListener(function(port) {
    Background.addPort(port);
});

function initAnim() {
    props.backimg = document.getElementById("python");
    props.foreimg = document.getElementById("bits");
    canvas = document.getElementById("canvas");
    context = canvas.getContext("2d");
    animation = new Animation(120, 2600, props);
}

function init() {
    //DownloadHistory.init();
    loadManifestInfo();
    checkversion();
    initAnim();
}
