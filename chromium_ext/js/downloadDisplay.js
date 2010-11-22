/* helpers */
var metercounter = 0;
function createLink(onclick, value) {
    var link = document.createElement("a");
    link.onclick = onclick;
    link.href = '#';
    link.innerHTML = value;
    return link;
}

function createElementWithClassName(type, className, content) {
    var elm = document.createElement(type);
    elm.className = className;
    elm.innerHTML = content || "";
    return elm;
}

function createMeter(min, max, val) {
    var elm = document.createElement("meter");
    elm.innerHTML = "_mc" + metercounter++;
    //elm.min = min;
    //elm.max = max;
    elm.value = val || 0
    elm.style.display = "inline-block"
    return elm;
}

function createProgress(max, val) {
    var elm = document.createElement("progress");
    elm.max = max;
    elm.style.display = "inline-block"
    return elm;
}

function createCanvas(id, width, height) {
    return document.getCSSCanvasContext('2d', 'canvas_' + id, width, height);
}

function show(elem, show) {
    elem.style.display = show ? "inline-block" : "none"
}

/* Indicators struct */
var Indicators = {}

Indicators.Pie = {
    width   : 48,
    height  : 48,
    radius  : 24,
    centerX : 24,
    centerY : 24,
    base    : -0.5 * Math.PI,
    base2   : 0.02 * Math.PI,
    dir     : false,
}

Indicators.Bar = {
    width   : 600
}

/* Display */
var Display = {}
Display.parent = null;
Display.activeNode = null
Display.queuedNode = null
Display.completedNode = null
Display.cancelledNode = null
Display.panels = {};

Display.init = function() {
    Display.parent = document.querySelector("#display")
    Display.activeNode = document.querySelector("#active");
    Display.queuedNode = document.querySelector("#queued")
    Display.completedNode = document.querySelector("#completed")
    Display.cancelledNode = document.querySelector("#cancelled")
}

Display.remove = function(id) {
    Display.parent.removeChild(Display.panels[id].rootNode)
    delete Display.panels[id]
    // update display
}

Display.clear = function() {
    for (var id in Display.panels) {
        Display.panels[id].clear()
        Display.remove(id)
    }
}

Display.showResults = function(data) {
    //if (data.reset)
    //    Display.clear()
    data.list.forEach(function(state) {
        Display.update(state)
    })
}

Display.update = function(state) {
    var id = state.id;
    if (!!Display.panels[id])
        Display.panels[id].update(state);
    else
        Display.panels[id] = new Display.Panel(state);
}

/* Panel */
Display.Panel = function(state) {
    this.state = state;
    this.status = "";

    this.progress_bars = null;

    this.canvas = createCanvas(state.id, Indicators.Pie.width, Indicators.Pie.height);

    this.pieNode        = createElementWithClassName("div",      "pie");
    this.dateNode       = createElementWithClassName("div",     "date");
    this.rootNode       = createElementWithClassName("div",    "panel");
    this.statusNode     = createElementWithClassName("div",   "status");
    var labelsNode      = createElementWithClassName("div",   "labels");
    var controlsNode    = createElementWithClassName("div", "controls");

    this.statusNode.appendChild(this.pieNode);
    this.rootNode.appendChild(this.dateNode);
    this.rootNode.appendChild(this.statusNode);
    this.statusNode.appendChild(labelsNode);

    var status_text = this.getStatusText();
    this.labels = {
        url         : createElementWithClassName("div",      "url",      state.url),
        status      : createElementWithClassName("div", "status",      status_text),
        progress    : createElementWithClassName("div", "progress", state.progress)
    };
    for (var i in this.labels) {
        labelsNode.appendChild(this.labels[i]);
    }
    labelsNode.appendChild(controlsNode);
    this.labels.name = createElementWithClassName("div", "name", state.name);
    this.labels.size = createElementWithClassName("div", "size", state.size);
    this.labels.percent = createElementWithClassName("div", "percent", state.percent);
    this.labels.rate = createElementWithClassName("div", "rate", state.speed);
    var title = createElementWithClassName("div", "title");
    title.appendChild(this.labels.percent);
    title.appendChild(this.labels.size);
    title.appendChild(this.labels.rate);
    title.appendChild(this.labels.name);
    labelsNode.insertAdjacentElement("afterBegin", title);

    this.controls = {
        pause   : createLink(bind(this,  this.pause),  "Pause"),
        resume  : createLink(bind(this, this.resume), "Resume"),
        cancel  : createLink(bind(this, this.cancel), "Cancel"),
        remove  : createLink(bind(this, this.remove), "Remove")
    };
    for (var i in this.controls) {
        controlsNode.appendChild(this.controls[i]);
    }

    this.pies = {
        background  : createElementWithClassName("div", "background"),
        foreground  : createElementWithClassName("div", "foreground")
    };
    this.showIndicators(false);
    this.pies.foreground.style.webkitMask = '-webkit-canvas(canvas_' + state.id + ')';
    for (var i in this.pies) {
        this.pieNode.appendChild(this.pies[i]);
    }

    this.labels.name.innerHTML = state.url.replace(/^.*\//, "")
    this.labels.progress.innerHTML = "&nbsp;"
    this.dateNode.innerHTML = state.date;

    if (state.status === DownloadStatus.IN_PROGRESS || state.status === DownloadStatus.PAUSED || status === DownloadStatus.CONNECTING)  {
        this.labels.name.innerHTML = state.fname;
        Display.activeNode.insertAdjacentElement("afterEnd", this.rootNode);
        this.showIndicators(true);
    }

    this.update(state);
}

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

        this.labels.percent.innerHTML = state.percentage + "% of&nbsp;";
        this.labels.rate.innerHTML = "&nbsp;-&nbsp;" + state.speed + "b/s&nbsp;";

        // draw pie progress indicator
        if (idle || active) {
            this.canvas.clearRect(0, 0, Indicators.Pie.width, Indicators.Pie.height);
            this.canvas.beginPath();
            this.canvas.moveTo(Indicators.Pie.centerX, Indicators.Pie.centerY);
            this.canvas.arc(Indicators.Pie.centerX, Indicators.Pie.centerY,
                            Indicators.Pie.radius,
                            Indicators.Pie.base, Indicators.Pie.base + Indicators.Pie.base2 * state.percentage,
                            false);

            this.canvas.lineTo(Indicators.Pie.centerX, Indicators.Pie.centerY);
            this.canvas.fill();
            this.canvas.closePath();
        }
        else if (inactive) {
            this.showIndicators(false);
        }

        // draw progress bars
        if (!this.progress_bars) {
            if (state.chunks.length > 0) {
                this.labels.progress.innerHTML = ""
                var progressbar_count = state.chunks.length
                var percent = Math.floor((1/progressbar_count)*100)
                this.progress_bars = state.chunks.map(function(e) {
                    var node = this.labels.progress.appendChild(createProgress(e, 0))
                    node.style.width = percent + "%"
                    return node
                }, this)
                this.labels.progress.style.width = Indicators.Bar.width + "px"
            }
        }

        if (this.progress_bars) {
            this.progress_bars.forEach(function(e, i) {
                e.value = state.progress[i]
            })
        }

        // show link controls
        show(this.controls.pause, active && !idle)
        show(this.controls.resume, idle)
        show(this.controls.cancel, active || idle)
        show(this.controls.remove, inactive)
    },

    adjustDocPosition: function(status) {
        if (status === DownloadStatus.QUEUED)
            Display.queuedNode.insertAdjacentElement("afterEnd", this.rootNode);

        else if (status === DownloadStatus.CONNECTING || status === DownloadStatus.INITIALIZING)
            Display.activeNode.insertAdjacentElement("afterEnd", this.rootNode);

        else if (status === DownloadStatus.COMPLETE)
            Display.completedNode.insertAdjacentElement("afterEnd", this.rootNode);

        else if (status === DownloadStatus.CANCELLED)
            Display.cancelledNode.insertAdjacentElement("afterEnd", this.rootNode);
    },

    showIndicators: function(show) {
        var str = show ? "block" : "none";
        this.pies.foreground.style.display = str;
        this.pies.background.style.display = str;
        this.labels.progress.style.display = str;
    },

    cancel: function() {
        send("cancel", this.state.id)
        return false;
    },

    pause: function() {
        send("pause", this.state.id)
        return false;
    },

    resume: function() {
        send("resume", this.state.id)
        return false;
    },

    remove: function() {
        send("remove", this.state.id)
        Display.remove(this.state.id)
        return false;
    },

    getStatusText: function() {
        switch (this.state.status) {
            case DownloadStatus.QUEUED:
                return "Queued";
            case DownloadStatus.CONNECTING:
                return "Connecting";
            case DownloadStatus.INITIALIZING:
                return "Initializing";
            case DownloadStatus.IN_PROGRESS:
                return "In progress";
            case DownloadStatus.COMPLETE:
                return "Completed";
            case DownloadStatus.CANCELLED:
                return "Cancelled";
            case DownloadStatus.PAUSED:
                return "Paused";
            case DownloadStatus.ERROR:
                return "Error";
            case DownloadStatus.UNDEFINED:
                return "Undefined";
        }
    },

    clear: function() {
        // remove listeners
        this.rootNode.innerHTML = ""
    }
};

/* port connection */
var port = null;

function send(cmd, args) {
    port.postMessage({cmd:cmd, args:args})
}

document.addEventListener("DOMContentLoaded", function() {
    Display.init()
    port = chrome.extension.connect();
    port.onMessage.addListener(Display.showResults);
    document.querySelector('#submit').onclick = function() {
        var input = document.querySelector('#uri');
        var uri = input.value.trim();
        if (regex.valid_uri.test(uri)) {
            var tokens = parseUri(uri);
            if (/^(?:https?|ftp)$/.test(tokens.protocol) && tokens.domain.length > 0 && tokens.fileName.length > 0) {
                input.value = "";
                send("add", uri);
            }
        }
    }
    document.querySelector('#clear').onclick = function() {
        Display.clear();
        send("clear", null);
    }
    send("update", null);
}, false);
