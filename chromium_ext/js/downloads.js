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
    if (typeof content !== 'undefined') {
        if (typeof content === 'string')
            elm.appendChild(createTextNode(content));
        else
            elm.innerHTML = content;
    }
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

Display.showResults = function(list) {
    list.forEach(function(state) {
        Display.update(state);
    });
};

Display.update = function(state) {
    var id = state.id;
    if (id in Display.panels) Display.panels[id].update(state);
    else Display.panels[id] = new Panel(state);
};

var Panel = function(state) {
    this.state = state;
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
    pies.foreground.style.webkitMask = '-webkit-canvas(canvas_' + state.id + ')';
    for (var i in pies)
        this.pieNode.appendChild(pies[i]);
    this.pies = pies;
    this.showIndicators(false);

    this.labels.progress.innerHTML = '&nbsp;';
    this.dateNode.innerHTML = state.date;

    if (state.status === DownloadStatus.IN_PROGRESS ||
        state.status === DownloadStatus.PAUSED ||
        state.status === DownloadStatus.CONNECTING) {
        Display.activeNode.insertAdjacentElement('afterEnd', this.rootNode);
    }

    this.adjustDocPosition(state.status);
    this.update(state);
};

Panel.prototype = {
    update: function(state) {
        state.log && console.log(state.log);

        var status = state.status;
        var canvas = this.canvas;
        var labels = this.labels;
        var controls = this.controls;

        var starting = status === DownloadStatus.INITIALIZING;
        var active = status === DownloadStatus.IN_PROGRESS;
        var idle = status === DownloadStatus.PAUSED;
        var done = status === DownloadStatus.COMPLETE;
        var inactive = status === DownloadStatus.QUEUED || status === DownloadStatus.CANCELLED;

        var prev_status = this.state.status;
        this.state = state;

        if (prev_status !== status) {
            this.adjustDocPosition(status);
            labels.size.innerHTML = formatBytes(state.fsize);
            labels.status.innerHTML = this.getStatusText();
        }

        // draw pie progress indicator
        if (idle || active) {
            this.showIndicators(true);
            var pie = Indicators.Pie;
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
        else if (inactive || done) {
            this.showIndicators(false);
            labels.percent.innerHTML = '';
            labels.rate.innerHTML = '';
            show(labels.percent, false);
            show(labels.rate, false);
            show(labels.size, false);
        }

        // draw progress bars
        if (!this.progress_bars) {
            if (state.chunks && state.chunks.length > 0) {
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
                state.progress.forEach(function(e, i) {
                    this.progress_bars[i].value = e;
                }, this);
            }
        }

        // show link controls
        show(controls.pause, active);
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
            return 'Waiting for response';
        }
    },

    clear: function() {
        this.rootNode.innerHTML = '';
    }
};

var port = null;

function send(cmd, var_args) {
    port.postMessage(Array.prototype.slice.call(arguments, 0));
}

document.addEventListener('DOMContentLoaded', function() {
    Display.init();
    port = chrome.extension.connect({'name':'downloads'});
    port.onMessage.addListener(Display.showResults);
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
        Display.clear();
        send('clear');
    }
    send('search', 'all');
}, false);

(new Image()).src = 'images/64.png';
