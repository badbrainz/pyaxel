var Settings = function(store, defaults) {
	Broadcaster.prototype.constructor.call(this, 'clear', 'update');
	this.storage = store || {};
	this.defaults = copy({}, defaults || {});
};

Settings.prototype = Object.create(Broadcaster.prototype);
Settings.prototype.constructor = Settings;

Settings.prototype.getItem = function(key, def) {
	var val = this.storage[key !== null ? key : 'null'];
	return (typeof val !== 'undefined' ? val : key in this.defaults ?
		this.defaults[key] : def);
};

Settings.prototype.getObject = function(key, def) {
	var val = this.getItem(key, def);
	return typeof val !== 'undefined' ? JSON.parse(typeof val !== 'string' ?
		JSON.stringify(val) : val) : val;
};

Settings.prototype.getBoolean = function(key, def) {
	return Boolean(this.getObject(key, def));
};

Settings.prototype.setItem = function(key, val) {
	key = key !== null ? key : 'null';
	val = val !== null ? val : 'null';
	var o = this.getItem(key);
	this.storage[key] = val;
	this.send('update', {
		type: 'set',
		key: key,
		newVal: val,
		oldVal: o
	});
};

Settings.prototype.setObject = function(key, val) {
	this.setItem(key, typeof val === 'string' ? val : JSON.stringify(val));
};

Settings.prototype.unset = function(key) {
	if (key in this.storage) {
		var val = this.storage[key];
		delete this.storage[key];
		this.send('update', {
			type: 'remove',
			key: key,
			oldVal: val,
			newVal: null
		});
	}
};

Settings.prototype.contains = function(key) {
	return key in this.storage || key in this.defaults;
};

Settings.prototype.keys = function() {
	var storage = this.storage;
	var arr = [];
	for (var key in storage) arr.push(key);
	return arr;
};

Settings.prototype.clear = function() {
	var keys = this.keys();
	var storage = this.storage;
	for (var i = 0, il = keys.length; i < il; i++) {
		delete storage[keys[i]];
	}
	this.send('clear');
};

Settings.prototype.length = function() {
	return this.keys().length;
};
