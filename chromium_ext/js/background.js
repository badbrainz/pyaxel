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
                    webkitNotifications.createNotification(
                      "images/48.png",
                      "Your version of pyaxelws is outdated!",
                      "v{0} {1}".format(data.version, "http://goo.gl/scuqi")
                    ).show();
                }, 10000);
            }
        }
    };
    request.send();
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
}

Background.queueDownload = function(url) {
    DownloadManager.addJob(url);
}

chrome.extension.onConnect.addListener(function(port) {
    Background.addPort(port);
});

function init() {
    //DownloadHistory.init();
    loadManifestInfo();
    checkversion();
}

init();
