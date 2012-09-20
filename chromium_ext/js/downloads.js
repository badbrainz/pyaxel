function createTextNode(value) {
    value = typeof value !== 'undefined' ? value : '';
    return document.createTextNode(value);
}

function createLink(onclick, value, href) {
    var link = document.createElement('a');
    typeof onclick === 'function' && (link.onclick = onclick);
    link.href = href || '#';
    href && (link.target = '_blank');
    link.appendChild(createTextNode(value));
    return link;
}

function createFakeLink(onclick, value) {
    var link = document.createElement('div');
    link.onclick = onclick;
    link.appendChild(createTextNode(value));
    return link;
}

function createElementWithClassName(type, className, content) {
    var elm = document.createElement(type);
    elm.className = className;
    if (typeof content !== 'undefined') {
        if (typeof content === 'string')
            elm.appendChild(createTextNode(content));
        else
            elm.innerHTML = content;
    }
    return elm;
}

function createProgress(max, val) {
    var elm = document.createElement('progress');
    elm.max = max;
    elm.style.display = 'inline-block';
    return elm;
}

function createCanvas(id, width, height) {
    return document.getCSSCanvasContext('2d', 'canvas_' + id, width, height);
}

function show(elem, show) {
    elem.style.display = show ? 'inline-block' : 'none';
}

function getStatusText(status) {
    switch (status) {
    case DownloadStatus.QUEUED:
        return 'Queued';
    case DownloadStatus.INITIALIZING:
        return 'Initializing';
    case DownloadStatus.IN_PROGRESS:
        return 'In progress';
    case DownloadStatus.COMPLETE:
        return 'Completed';
    case DownloadStatus.CANCELLED:
        return 'Cancelled';
    case DownloadStatus.PAUSED:
        return 'Paused';
    case DownloadStatus.UNDEFINED:
        return 'Undefined';
    case DownloadStatus.CONNECTING:
        return 'Connecting';
    case DownloadStatus.ERROR:
        return 'Error';
    case DownloadStatus.CLOSING:
        return 'Disconnecting...';
    }
}

var indicators = {};

indicators.Pie = {
    width: 48,
    height: 48,
    radius: 24,
    centerX: 24,
    centerY: 24,
    base: -0.5 * Math.PI,
    base2: 0.02 * Math.PI,
    dir: false
};

indicators.Bar = {
    width: 600
};

var panels = {};
var display = {};

display.init = function() {
    display.activeNode = document.getElementById('active');
    display.queuedNode = document.getElementById('queued');
    display.completedNode = document.getElementById('completed');
    display.cancelledNode = document.getElementById('cancelled');
};

display.remove = function(id) {
    document.getElementById('display').removeChild(panels[id].rootNode)
    delete panels[id];
};

display.clear = function() {
    for (var id in panels) {
        panels[id].clear();
        display.remove(id);
    }
};

display.showResults = function(list) {
    list.forEach(display.update);
};

display.update = function(state) {
    var id = state.id;
    if (id in panels) panels[id].update(state);
    else panels[id] = new Panel(state);
};

function Panel(state) {
    this.state = state;
    this.progress_bars = null;

    this.canvas = createCanvas(state.id, indicators.Pie.width, indicators.Pie.height);

    this.pieNode = createElementWithClassName('div', 'pie');
    this.rootNode = createElementWithClassName('div', 'panel');
    this.statusNode = createElementWithClassName('div', 'status');
    var labelsNode = createElementWithClassName('div', 'labels');
    var controlsNode = createElementWithClassName('div', 'controls');
    this.dateNode = createElementWithClassName('div', 'date dyninfo');

    this.statusNode.appendChild(this.pieNode);
    this.rootNode.appendChild(this.dateNode);
    this.rootNode.appendChild(this.statusNode);
    this.statusNode.appendChild(labelsNode);

    var labels = {
        url: createLink(null, state.url, state.url),
        status: createElementWithClassName('div', 'status', getStatusText(state.status)),
        progress: createElementWithClassName('div', 'progress', state.progress)
    };
    labels.url.className = 'url';
    for (var i in labels)
        labelsNode.appendChild(labels[i]);
    this.labels = labels;
    labelsNode.appendChild(controlsNode);

    var title = createElementWithClassName('div', 'title');
    this.labels.name = createElementWithClassName('div', 'name', state.fname);
    this.labels.size = createElementWithClassName('div', 'size dyninfo', formatBytes(state.fsize));
    this.labels.rate = createElementWithClassName('div', 'rate dyninfo', state.speed);
    this.labels.percent = createElementWithClassName('div', 'percent dyninfo', state.percent);
    title.appendChild(this.labels.percent);
    title.appendChild(this.labels.size);
    title.appendChild(this.labels.rate);
    title.appendChild(this.labels.name);
    labelsNode.insertAdjacentElement('afterBegin', title);

    var controls = {
        pause: createFakeLink(this.pause.bind(this), 'Pause'),
        resume: createFakeLink(this.resume.bind(this), 'Resume'),
        retry: createFakeLink(this.retry.bind(this), 'Retry'),
        cancel: createFakeLink(this.cancel.bind(this), 'Cancel'),
        remove: createFakeLink(this.remove.bind(this), 'Remove')
    };
    for (var i in controls)
        controlsNode.appendChild(controls[i]);
    this.controlsNode = controlsNode;
    this.controls = controls;

    var pies = {
        background: createElementWithClassName('div', 'background'),
        foreground: createElementWithClassName('div', 'foreground')
    };
    pies.foreground.style.webkitMask = formatString('-webkit-canvas(canvas_{0})', state.id);
    for (var i in pies)
        this.pieNode.appendChild(pies[i]);
    this.pies = pies;
    this.showindicators(false);

    this.labels.progress.innerHTML = '&nbsp;';
    this.dateNode.innerHTML = state.date;

    this.adjustDocPosition(state.status);
    this.update(state);
}

Panel.prototype.update = function(state) {
    state.log && console.log(state.log);

    var status = state.status;
    var labels = this.labels;

    var active = status === DownloadStatus.IN_PROGRESS;
    var idle = status === DownloadStatus.PAUSED;
    var ending = status === DownloadStatus.CLOSING;
    var done = status === DownloadStatus.COMPLETE;
    var inactive = status === DownloadStatus.QUEUED ||
        status === DownloadStatus.CANCELLED || status === DownloadStatus.ERROR;

    var prev_status = this.state.status;
    this.state = state;

    if (prev_status !== status) {
        this.adjustDocPosition(status);
        labels.size.innerHTML = formatBytes(state.fsize);
        labels.status.innerHTML = getStatusText(status);
        labels.name.innerHTML = state.fname || '';
    }

    if (idle || active) {
        this.showindicators(true);
        var pie = indicators.Pie;
        var canvas = this.canvas;
        canvas.clearRect(0, 0, pie.width, pie.height);
        canvas.beginPath();
        canvas.moveTo(pie.centerX, pie.centerY);
        var percent = state.fsize ? Math.floor(sum(state.progress) * 100 / state.fsize) : 0;
        canvas.arc(pie.centerX, pie.centerY, pie.radius, pie.base, pie.base + pie.base2 * percent, false);
        canvas.lineTo(pie.centerX, pie.centerY);
        canvas.fill();
        canvas.closePath();
        labels.percent.innerHTML = done ? '' : percent + '% of';
        labels.rate.innerHTML = '-&nbsp;' + state.speed + 'b/s';
        show(labels.percent, true);
        show(labels.rate, active);
        show(labels.size, true);
    }
    else if (inactive || done || ending) {
        this.showindicators(false);
        labels.percent.innerHTML = '';
        labels.rate.innerHTML = '';
        show(labels.percent, false);
        show(labels.rate, false);
        show(labels.size, false);
    }

    if (!this.progress_bars) {
        if (state.chunks && state.chunks.length > 0) {
            labels.progress.innerHTML = '';
            var progressbar_count = state.chunks.length;
            var percent = Math.floor((1 / progressbar_count) * 100);
            this.progress_bars = state.chunks.map(function(e) {
                var node = labels.progress.appendChild(createProgress(e, 0));
                node.style.width = percent + '%';
                return node;
            });
            labels.progress.style.width = indicators.Bar.width + 'px';
        }
    }
    if (this.progress_bars) {
        if (done || inactive) {
            this.progress_bars.forEach(function(e) {
                e.parentNode.removeChild(e);
            });
            delete this.progress_bars;
        }
        else {
            state.progress.forEach(function(e, i) {
                this.progress_bars[i].value = e;
            }, this);
        }
    }

    var controls = this.controls;
    show(controls.pause, active);
    show(controls.resume, idle);
    show(controls.retry, inactive);
    show(controls.cancel, active || idle);
    show(controls.remove, inactive || done);
}

Panel.prototype.adjustDocPosition = function(status) {
    switch (status) {
    case DownloadStatus.QUEUED:
        display.queuedNode.insertAdjacentElement('afterEnd', this.rootNode);
        break;
    case DownloadStatus.CONNECTING:
    case DownloadStatus.INITIALIZING:
    case DownloadStatus.IN_PROGRESS:
    case DownloadStatus.PAUSED:
    case DownloadStatus.CLOSING:
        display.activeNode.insertAdjacentElement('afterEnd', this.rootNode);
        break;
    case DownloadStatus.COMPLETE:
        display.completedNode.insertAdjacentElement('afterEnd', this.rootNode);
        break;
    case DownloadStatus.CANCELLED:
    case DownloadStatus.ERROR:
        display.cancelledNode.insertAdjacentElement('afterEnd', this.rootNode);
        break;
    }
};

Panel.prototype.showindicators = function(show) {
    var str = show ? 'block' : 'none';
    this.pies.foreground.style.display = str;
    this.pies.background.style.display = str;
    this.labels.progress.style.display = str;
};

Panel.prototype.cancel = function() {
    send('cancel', this.state.id);
};

Panel.prototype.retry = function() {
    send('retry', this.state.id);
    //display.remove(this.state.id);
};

Panel.prototype.pause = function() {
    send('pause', this.state.id);
};

Panel.prototype.resume = function() {
    send('resume', this.state.id);
};

Panel.prototype.remove = function() {
    send('remove', this.state.id);
    display.remove(this.state.id);
};

Panel.prototype.clear = function() {
    this.rootNode.innerHTML = '';
};

var port = null;

function send(cmd, var_args) {
    try {
        port.postMessage(Array.prototype.slice.call(arguments, 0));
    }
    catch (err) {}
}

document.addEventListener('DOMContentLoaded', function() {
    display.init();
    port = chrome.extension.connect({'name':'downloads'});
    port.onMessage.addListener(display.showResults);
    document.getElementById('uri').onkeypress = function(e) {
        if (e.keyCode == 13) {
            var input = document.getElementById('uri');
            send('add', input.value.trim());
            input.value = '';
        }
    }
    document.getElementById('submit').onclick = function() {
        var input = document.getElementById('uri');
        send('add', input.value.trim());
        input.value = '';
    }
    document.getElementById('clear').onclick = function() {
        display.clear();
        send('purge');
    }
    send('search', 'all');
}, false);

(new Image()).src = 'images/64.png';
