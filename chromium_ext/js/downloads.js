/* helpers */
var metercounter = 0;

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
    typeof content !== 'undefined' && elm.appendChild(createTextNode(content));
    return elm;
}

//function createMeter(min, max, val) {
//    var elm = document.createElement('meter');
//    elm.innerHTML = 'mc_' + metercounter++;
//    //elm.min = min;
//    //elm.max = max;
//    elm.value = val || 0;
//    elm.style.display = 'inline-block';
//    return elm;
//}

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

/* Indicators */
var Indicators = {};

Indicators.Pie = {
    width: 48,
    height: 48,
    radius: 24,
    centerX: 24,
    centerY: 24,
    base: -0.5 * Math.PI,
    base2: 0.02 * Math.PI,
    dir: false
};

Indicators.Bar = {
    width: 600
};

/* Display */
var Display = {};
Display.panels = {};

Display.init = function() {
    Display.activeNode = document.getElementById('active');
    Display.queuedNode = document.getElementById('queued');
    Display.completedNode = document.getElementById('completed');
    Display.cancelledNode = document.getElementById('cancelled');
};

Display.remove = function(id) {
    var displayNode = document.getElementById('display');
    displayNode.removeChild(Display.panels[id].rootNode)
    delete Display.panels[id];
};

Display.clear = function() {
    for (var id in Display.panels) {
        Display.panels[id].clear();
        Display.remove(id);
    }
};

Display.showResults = function(data) {
    data.list.forEach(function(state) {
        Display.update(state);
    });
};

Display.update = function(state) {
    var id = state.id;
    if (id in Display.panels) Display.panels[id].update(state);
    else Display.panels[id] = new Panel(state);
};

/* Panel */
var Panel = function(state) {
    this.state = state;
    this.status = '';

    this.progress_bars = null;

    this.canvas = createCanvas(state.id, Indicators.Pie.width, Indicators.Pie.height);

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
        status: createElementWithClassName('div', 'status', this.getStatusText()),
        progress: createElementWithClassName('div', 'progress', state.progress)
    };
    labels.url.className = 'url';
    for (var i in labels)
        labelsNode.appendChild(labels[i]);
    this.labels = labels;
    labelsNode.appendChild(controlsNode);

    var title = createElementWithClassName('div', 'title');
    this.labels.name = createElementWithClassName('div', 'name', state.name);
    this.labels.size = createElementWithClassName('div', 'size dyninfo', state.size);
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
    this.controls = controls;

    var pies = {
        background: createElementWithClassName('div', 'background'),
        foreground: createElementWithClassName('div', 'foreground')
    };
    pies.foreground.style.webkitMask = '-webkit-canvas(canvas_' + state.id + ')';
    for (var i in pies)
        this.pieNode.appendChild(pies[i]);
    this.pies = pies;
    this.showIndicators(false);

    this.labels.name.innerHTML = state.url.replace(/^.*\//, '');
    this.labels.progress.innerHTML = '&nbsp;';
    this.dateNode.innerHTML = state.date;

    if (state.status === DownloadStatus.IN_PROGRESS || state.status === DownloadStatus.PAUSED || status === DownloadStatus.CONNECTING) {
        this.labels.name.innerHTML = state.fname;
        Display.activeNode.insertAdjacentElement('afterEnd', this.rootNode);
        this.showIndicators(true);
    }

    this.update(state);
};

Panel.prototype = {
    update: function(state) {
        this.state = state;
        var status = state.status;
        var canvas = this.canvas;
        var labels = this.labels;
        var controls = this.controls;

        if (this.status !== status) {
            this.status = status;
            this.adjustDocPosition(status);
            labels.size.innerHTML = state.size;
            labels.name.innerHTML = state.fname;
            labels.status.innerHTML = this.getStatusText();
        }

        var starting = status === DownloadStatus.INITIALIZING;
        var active = status === DownloadStatus.IN_PROGRESS;
        var idle = status === DownloadStatus.PAUSED;
        var done = status === DownloadStatus.COMPLETE;
        var inactive = status === DownloadStatus.QUEUED || status === DownloadStatus.CANCELLED;

        if (starting) {
            this.showIndicators(true);
        }

        // draw pie progress indicator
        if (idle || active) {
            var pie = Indicators.Pie;
            canvas.clearRect(0, 0, pie.width, pie.height);
            canvas.beginPath();
            canvas.moveTo(pie.centerX, pie.centerY);
            canvas.arc(pie.centerX, pie.centerY, pie.radius, pie.base, pie.base + pie.base2 * state.percentage, false);
            canvas.lineTo(pie.centerX, pie.centerY);
            canvas.fill();
            canvas.closePath();
            labels.percent.innerHTML = done ? '' : state.percentage + '% of&nbsp;';
            labels.rate.innerHTML = '&nbsp;-&nbsp;' + state.speed + 'b/s&nbsp;';
        }
        else if (inactive || done) {
            this.showIndicators(false);
            labels.percent.innerHTML = '';
            labels.rate.innerHTML = '';
        }

        // draw progress bars
        if (!this.progress_bars) {
            if (state.chunks.length > 0) {
                labels.progress.innerHTML = '';
                var progressbar_count = state.chunks.length;
                var percent = Math.floor((1 / progressbar_count) * 100);
                this.progress_bars = state.chunks.map(function(e) {
                    var node = labels.progress.appendChild(createProgress(e, 0));
                    node.style.width = percent + '%';
                    return node;
                }, this);
                labels.progress.style.width = Indicators.Bar.width + 'px';
            }
        }
        if (this.progress_bars) {
            if (done || inactive) {
                this.progress_bars.forEach(function(e, i) {
                    e.parentNode.removeChild(e);
                });
                delete this.progress_bars;
            }
            else {
                this.progress_bars.forEach(function(e, i) {
                    e.value = state.progress[i];
                });
            }
        }

        // show link controls
        show(controls.pause, active);
//        show(controls.pause, active && !idle);
        show(controls.resume, idle);
        show(controls.retry, inactive);
        show(controls.cancel, active || idle);
        show(controls.remove, inactive || done);
    },

    adjustDocPosition: function(status) {
        switch (status) {
        case DownloadStatus.QUEUED:
            Display.queuedNode.insertAdjacentElement('afterEnd', this.rootNode);
            break;
        case DownloadStatus.CONNECTING:
        case DownloadStatus.INITIALIZING:
            Display.activeNode.insertAdjacentElement('afterEnd', this.rootNode);
            break;
        case DownloadStatus.COMPLETE:
            Display.completedNode.insertAdjacentElement('afterEnd', this.rootNode);
            break;
        case DownloadStatus.CANCELLED:
            Display.cancelledNode.insertAdjacentElement('afterEnd', this.rootNode);
            break;
        }
    },

    showIndicators: function(show) {
        var str = show ? 'block' : 'none';
        this.pies.foreground.style.display = str;
        this.pies.background.style.display = str;
        this.labels.progress.style.display = str;
    },

    cancel: function() {
        send('cancel', this.state.id);
        return false;
    },

    retry: function() {
        send('retry', this.state.id);
        //Display.remove(this.state.id);
        return false;
    },

    pause: function() {
        send('pause', this.state.id);
        return false;
    },

    resume: function() {
        send('resume', this.state.id);
        return false;
    },

    remove: function() {
        send('remove', this.state.id);
        Display.remove(this.state.id);
        return false;
    },

    getStatusText: function() {
        switch (this.state.status) {
        case DownloadStatus.QUEUED:
            return 'Queued';
        case DownloadStatus.CONNECTING:
            return 'Connecting';
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
        case DownloadStatus.ERROR:
            return 'Error';
        case DownloadStatus.UNDEFINED:
            return 'Undefined';
        }
    },

    clear: function() {
        // remove listeners
        this.rootNode.innerHTML = '';
    }
};

/* port connection */
var port = null;

function send(cmd, arg) {
    port.postMessage({
        cmd: cmd,
        arg: arg
    });
}

document.addEventListener('DOMContentLoaded', function() {
    Display.init();
    port = chrome.extension.connect();
    port.onMessage.addListener(Display.showResults);
    document.getElementById('submit').onclick = function() {
        var input = document.getElementById('uri');
        send('add', input.value.trim());
        input.value = '';
    }
    document.getElementById('clear').onclick = function() {
        Display.clear();
        send('clear');
    }
    send('update');
}, false);
