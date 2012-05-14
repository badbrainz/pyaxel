/* helpers */
var metercounter = 0;

function createLink(onclick, value) {
    var link = document.createElement('a');
    link.onclick = onclick;
    link.href = '#';
    link.innerHTML = value;
    return link;
}

function createElementWithClassName(type, className, content) {
    var elm = document.createElement(type);
    elm.className = className;
    elm.innerHTML = content || '';
    return elm;
}

function createMeter(min, max, val) {
    var elm = document.createElement('meter');
    elm.innerHTML = '_mc' + metercounter++;
    //elm.min = min;
    //elm.max = max;
    elm.value = val || 0;
    elm.style.display = 'inline-block';
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
    //if (data.reset)
    //    Display.clear()
    data.list.forEach(function(state) {
        Display.update(state);
    });
};

Display.update = function(state) {
    var id = state.id;
    if (!! Display.panels[id]) Display.panels[id].update(state);
    else Display.panels[id] = new Display.Panel(state);
};

/* Panel */
Display.Panel = function(state) {
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

    var status_text = this.getStatusText();
    this.labels = {
        url: createElementWithClassName('div', 'url', state.url),
        status: createElementWithClassName('div', 'status', status_text),
        progress: createElementWithClassName('div', 'progress', state.progress)
    };
    for (var i in this.labels) {
        labelsNode.appendChild(this.labels[i]);
    }
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

    this.controls = {
        pause: createLink(this.pause.bind(this), 'Pause'),
        resume: createLink(this.resume.bind(this), 'Resume'),
        cancel: createLink(this.cancel.bind(this), 'Cancel'),
        remove: createLink(this.remove.bind(this), 'Remove')
    };
    for (var i in this.controls) {
        controlsNode.appendChild(this.controls[i]);
    }

    this.pies = {
        background: createElementWithClassName('div', 'background'),
        foreground: createElementWithClassName('div', 'foreground')
    };
    this.showIndicators(false);
    this.pies.foreground.style.webkitMask = '-webkit-canvas(canvas_' + state.id + ')';
    for (var i in this.pies) {
        this.pieNode.appendChild(this.pies[i]);
    }

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

Display.Panel.prototype = {
    update: function(state) {
        this.state = state;
        var status = state.status;

        if (this.status !== status) {
            this.status = status;
            this.adjustDocPosition(status);
            this.labels.size.innerHTML = state.size;
            this.labels.name.innerHTML = state.fname;
            this.labels.status.innerHTML = this.getStatusText();
        }

        var idle = status === DownloadStatus.PAUSED;
        var active = status === DownloadStatus.IN_PROGRESS;
        var inactive = status === DownloadStatus.QUEUED || status === DownloadStatus.COMPLETE || status === DownloadStatus.CANCELLED;

        if (status === DownloadStatus.INITIALIZING) {
            this.showIndicators(true);
        }

        this.labels.percent.innerHTML = state.percentage + '% of&nbsp;';
        this.labels.rate.innerHTML = '&nbsp;-&nbsp;' + state.speed + 'b/s&nbsp;';

        // draw pie progress indicator
        if (idle || active) {
            var pie = Indicators.Pie;
            this.canvas.clearRect(0, 0, pie.width, pie.height);
            this.canvas.beginPath();
            this.canvas.moveTo(pie.centerX, pie.centerY);
            this.canvas.arc(pie.centerX, pie.centerY, pie.radius, pie.base, pie.base + pie.base2 * state.percentage, false);
            this.canvas.lineTo(pie.centerX, pie.centerY);
            this.canvas.fill();
            this.canvas.closePath();
        }
        else if (inactive) {
            this.showIndicators(false);
            this.labels.rate.innerHTML = '';
        }

        // draw progress bars
        if (!this.progress_bars) {
            if (state.chunks.length > 0) {
                this.labels.progress.innerHTML = '';
                var progressbar_count = state.chunks.length;
                var percent = Math.floor((1 / progressbar_count) * 100);
                this.progress_bars = state.chunks.map(function(e) {
                    var node = this.labels.progress.appendChild(createProgress(e, 0));
                    node.style.width = percent + '%';
                    return node;
                }, this);
                this.labels.progress.style.width = Indicators.Bar.width + 'px';
            }
        }

        if (this.progress_bars) {
            this.progress_bars.forEach(function(e, i) {
                e.value = state.progress[i];
            });
        }

        // show link controls
        show(this.controls.pause, active && !idle);
        show(this.controls.resume, idle);
        show(this.controls.cancel, active || idle);
        show(this.controls.remove, inactive);
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

function send(cmd, args) {
    port.postMessage({
        cmd: cmd,
        args: args
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