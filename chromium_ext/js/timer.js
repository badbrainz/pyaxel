function Timer(callback, interval) {
    this.callback = callback;
    this.interval = interval;
}

Timer.prototype.start = function() {
    if (!this.enabled) {
        this.timestamp = Date.now();
        this.enabled = true;
        this.id = window.setInterval(this.callback, this.interval);
    }
};

Timer.prototype.stop = function() {
    if (this.enabled) {
        window.clearInterval(this.id);
        delete this.timestamp;
        delete this.enabled;
        delete this.id;
    }
};

Timer.prototype.elapsed = function() {
    return !this.enabled ? 0 : (Date.now() - this.timestamp) / 1000;
};
