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

function checkVersion() {
	var request = new XMLHttpRequest();
	request.open('GET', chrome.extension.getURL('manifest.json'), true);
	request.onreadystatechange = function() {
		if (request.readyState == XMLHttpRequest.DONE) {
			if (request.status == 200) {
				var manifest = JSON.parse(request.responseText);
				preferences.setItem('data.version', manifest.version);
				// check python script version
				request.open('GET', 'http://pyaxelws.googlecode.com/hg/version.txt', true);
				request.onreadystatechange = function() {
					if (request.readyState == XMLHttpRequest.DONE) {
						if (request.status == 200) {
							var data = JSON.parse(request.responseText);
							var build = data.version.split('.');
							var loc_build = preferences.getItem('data.paversion').split('.');
							if (loc_build[0] < build[0] || loc_build[1] < build[1] || loc_build[2] < build[2]) {
								preferences.setItem('data.paversion', data.version); // assume responsible user
								window.setTimeout(function() {
									var item = {
										title: 'Your version of pyaxelws appears to be outdated.',
										dllink: 'http://goo.gl/AEoTH',
										chlink: 'http://goo.gl/9fcSt',
										version: data.version
									};
									var value;
									var query = '?';
									for (var key in item)
										query += formatString('{0}={1}&', key, encodeURIComponent(item[key]));
									var url = chrome.extension.getURL('notification.html') + query;
									window.webkitNotifications.createHTMLNotification(url).show();
								}, 10000);
							}
						}
					}
				};
				request.send();
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
	// python
	DownloadBadge.backimg = document.getElementById('python');

	// bits
	DownloadBadge.foreimg = document.getElementById('bits');

	canvas = document.getElementById('canvas');
	context = canvas.getContext('2d');
	animation = new Animation(120, 1700, DownloadBadge);
}

function init() {
	//	DownloadHistory.init();
	checkVersion();
	initAnim();
}

// Background
var CommandHandler = {
	'add': function(arg) {
		Background.queueDownload(arg);
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

var Background = {};
Background.ports = {};

Background.addPort = function(port) {
	Background.ports[port.sender.tab.id] = port;

	port.onMessage.addListener(function(msg) {
		var cmd = msg.cmd;
		var arg = msg.arg;
		if (cmd in CommandHandler) {
			var result = CommandHandler[cmd](arg);
			if (result) port.postMessage(result);
		}
	});

	port.onDisconnect.addListener(Background.removePort);
};

Background.removePort = function(port) {
	delete Background.ports[port.sender.tab.id];
};

Background.notify = function(list, reset) {
	var msg = {
		reset: reset || false,
		list: list
	};
	for (var port in Background.ports)
		Background.ports[port].postMessage(msg);

	animation.start();
};

Background.queueDownload = function(href) {
	var tokens = parseUri(href);
	if (regex.valid_uri.test(href) && /^https?|ftp$/.test(tokens.protocol) && tokens.domain.length && tokens.fileName.length) {
		var request = new XMLHttpRequest();
		request.open('HEAD', href, true);
		request.onreadystatechange = function() {
			if (request.readyState == XMLHttpRequest.DONE) {
				if (request.status == 200)
					DownloadManager.addJob(href);
			}
		}
		request.send();
	}
	else console.log('error: invalid request:', href);
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
