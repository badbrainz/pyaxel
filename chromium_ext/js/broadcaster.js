/** @constructor */

function Event(sender) {

	/** @private */
    this.sender = sender;

    /** @private */
    this.listeners = [];
}

/**
 * @param {Function} callback
 * @param {Object} context
 */
Event.prototype.attach = function(callback, context) {
    for (var i = 0, il = this.listeners.length; i < il; i++) {
        if (this.listeners[i].callback === callback) return;
    }
    this.listeners.push({
        'callback': callback,
        'context': context || callback
    });
};

/** @param {...*} args */
Event.prototype.notify = function(args) {
    for (var i = 0, il = this.listeners.length; i < il; i++) {
        this.listeners[i].callback.call(this.listeners[i].context, this.sender, args);
    }
};

/** @constructor */

function Emitter() {

	/** @private */
	this.listeners = [];
}

/** @param {Function} callback */
Emitter.prototype.attach = function(callback) {
	for (var i = 0, il = this.listeners.length; i < il; i++) {
		if (this.listeners[i] === callback) return;
	}
	this.listeners.push(callback);
};

/** @param {Function} callback */
Emitter.prototype.detach = function(callback) {
	for (var i = 0, il = this.listeners.length; i < il; i++) {
		if (this.listeners[i] === callback) {
			this.listeners.splice(i, 1);
			return;
		}
	}
};

/** @param {...*} args */
Emitter.prototype.notify = function(args) {
	var listeners = this.listeners;
	for (var i = 0, il = listeners.length; i < il; i++) {
		listeners[i].apply(null, arguments);
	}
};

/** @constructor */

function Broadcaster(var_args) {

	/** @private */
	this.events = Object.create(null);

	this.addEvent.apply(this, Array.prototype.slice.call(arguments, 0));
}

/** @param {...string} args */
Broadcaster.prototype.addEvent = function(args) {
	var events = this.events;
	var i = arguments.length;
	while (i--) {
		events[arguments[i]] = events[arguments[i]] || new Emitter();
	}
};

/** @param {...string} args */
Broadcaster.prototype.removeEvent = function(args) {
	var i = arguments.length;
	if (!i) {
		this.events = Object.create(null);
		return;
	}
	var events = this.events;
	while (i--) {
		delete events[arguments[i]];
	}
};

/** @param {...*} args */
Broadcaster.prototype.send = function(args) {
	var name = arguments[0];
	var events = this.events;
	name in events && events[name].notify.apply(events[name], Array.prototype.slice.call(arguments, 1));
};

/**
 * @param {string} name
 * @param {Function} callback
 * @param {boolean=} attach
 */
Broadcaster.prototype.connect = function(name, callback, attach) {
	var events = this.events;
	if (!(name in events)) return;
	if (attach === false) {
		events[name] && events[name].detach(callback);
		return;
	}
	events[name].attach(callback);
};
