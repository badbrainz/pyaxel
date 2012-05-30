function Timer(callback, interval) {
    this.interval = interval;
    this.callback = callback;
    this._enabled = false;
    this._duration = 0;
    this._id = null;
}

Timer.prototype = {
    start: function() {
        if (!this._enabled) {
            this._duration = new Date();
            this._enabled = true;
            this._id = window.setInterval(this.callback, this.interval);
        }
    },

    stop: function() {
        if (this._enabled) {
            this._enabled = false;
            window.clearInterval(this._id);
        }
    },

    elapsed: function() {
        return !this._enabled ? 0 : (new Date() - this._duration) / 1000;
    }
};
