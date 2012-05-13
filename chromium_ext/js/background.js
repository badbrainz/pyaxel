var preferences = new PropertyStorage(window.localStorage, {
	'data.version': 0,
	'data.paversion': '1.0.2',
	'prefs.host': '127.0.0.1',
	'prefs.downloads': 2,
	'prefs.bandwidth': 0,
	'prefs.port': 8002,
	'prefs.splits': 4,
	'prefs.path': ''
});

function loadManifestInfo() {
	var manifest = null;
	var request = new XMLHttpRequest();
	request.open('GET', chrome.extension.getURL('manifest.json'), false);
	request.onreadystatechange = function() {
		if (this.readyState == XMLHttpRequest.DONE) {
			manifest = JSON.parse(this.responseText);
			preferences.setItem('data.version', manifest.version);
		}
	};
	request.send();
}

function checkversion() {
	var request = new XMLHttpRequest();
	request.open('GET', 'http://pyaxelws.googlecode.com/hg/version.txt', false);
	request.onreadystatechange = function() {
		if (this.readyState == XMLHttpRequest.DONE) {
			var data = JSON.parse(this.responseText);
			if (preferences.getItem('data.paversion') !== data.version) {
				preferences.setItem('data.paversion', data.version); // don't annoy the user next time
				setTimeout(function() {
					var item = {
						title: 'Your version of pyaxelws appears to be outdated.',
						dllink: 'http://goo.gl/AEoTH',
						chlink: 'http://goo.gl/9fcSt',
						version: data.version
					};
					var value;
					var query = '?';
					for (var key in item) {
						if (value = item[key]) query += formatString('{0}={1}&', key, encodeURIComponent(value));
					}
					var url = chrome.extension.getURL('notification.html') + query;
					window.webkitNotifications.createHTMLNotification(url).show();
				}, 10000);
			}
		}
	};
	request.send();
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

var Animation = (function() {
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

	function CanvasWrapper(speed, duration, props) {
		this._timer = new Timer(paramedFunction(drawFrame, this, props), speed);
		this._timeoutID = null;
		this.duration = duration;
		this.props = props;
	}

	CanvasWrapper.prototype = {

		start: function() {
			this._timer.start();
			if (this._timeoutID) clearTimeout(this._timeoutID);
			this._timeoutID = setTimeout(this.stop.bind(this), this.duration);
		},

		stop: function() {
			this._timer.stop();
			drawBackground(this.props);
			this.props.paint();
		}
	};

	return CanvasWrapper;
})();

function initAnim() {
	DownloadBadge.backimg = document.getElementById('python');
	DownloadBadge.foreimg = document.getElementById('bits');
	canvas = document.getElementById('canvas');
	context = canvas.getContext('2d');
	animation = new Animation(120, 1700, DownloadBadge);
}

function init() {
	//	DownloadHistory.init();
	loadManifestInfo();
	checkversion();
	initAnim();
}

// Background

var Background = {};
Background.ports = {};

Background.addPort = function(port) {
	Background.ports[port.sender.tab.id] = port;

	port.onMessage.addListener(function(msg) {
		var cmd = msg.cmd;
		if (cmd === 'cancel') DownloadManager.cancelJob(msg.args);
		else if (cmd === 'remove') DownloadManager.remove(msg.args);
		else if (cmd === 'pause') DownloadManager.pauseJob(msg.args);
		else if (cmd === 'resume') DownloadManager.resumeJob(msg.args);
		else if (cmd === 'update') port.postMessage({
			reset: true,
			list: DownloadManager.getFullList()
		});
		else if (cmd === 'add') Background.queueDownload(msg.args);
		else if (cmd === 'clear') DownloadManager.eraseInactiveJobs();
	});

	port.onDisconnect.addListener(Background.removePort);
};

Background.removePort = function(port) {
	delete Background.ports[port.sender.tab.id];
};

Background.notify = function(list, reset) {
	for (var port in Background.ports)
	Background.ports[port].postMessage({
		reset: reset || false,
		list: list
	});
	animation.start();
};

Background.queueDownload = function(url) {
	DownloadManager.addJob(url);
};

// Chrome

chrome.contextMenus.create({
	//	"targetUrlPatterns" : []
	'title': 'Save Link Using PyAxelWS',
	'contexts': ['link'],
	'onclick': function(info, tab) {
		Background.queueDownload(info.linkUrl);
	}
});

chrome.extension.onConnect.addListener(function(port) {
	Background.addPort(port);
});

// EXPORTS

function getPreference(key, obj) {
	return obj ? preferences.getObject(key) : preferences.getItem(key);
}

function setPreference(key, val) {
	val === null ? preferences.unset(key) : preferences.setObject(key, val);
}
