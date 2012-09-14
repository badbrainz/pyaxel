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
