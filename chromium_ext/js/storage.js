/**
 * @param {Object=} store
 * @param {Object=} defaults
 * @constructor
 * @extends {Broadcaster}
 */
var PropertyStorage = function(store, defaults) {
	Broadcaster.prototype.constructor.apply(this);
	this.addEvent('clear', 'update');
	this.storage = store || {};
	this.defaults = copy({}, defaults || {});
};

PropertyStorage.prototype = Object.create(Broadcaster.prototype);
PropertyStorage.prototype.constructor = PropertyStorage;

/**
 * @param {string} key
 * @param {*=} def
 * @return {string}
 */
PropertyStorage.prototype.getItem = function(key, def) {
	var val = this.storage[key !== null ? key : 'null'];
	return (typeof val !== 'undefined' ? val : key in this.defaults ? this.defaults[key] : def);
};

/**
 * @param {string} key
 * @param {*=} def
 * @return {*}
 */
PropertyStorage.prototype.getObject = function(key, def) {
	var val = this.getItem(key, def);
	return typeof val !== 'undefined' ? JSON.parse(typeof val !== 'string' ? JSON.stringify(val) : val) : val;
};

/**
 * @param {string} key
 * @param {*=} def
 * @return {boolean}
 */
PropertyStorage.prototype.getBoolean = function(key, def) {
	return Boolean(this.getObject(key, def));
};

/**
 * @param {string} key
 * @param {*} val
 */
PropertyStorage.prototype.setItem = function(key, val) {
	key = key !== null ? key : 'null';
	val = val !== null ? val : 'null';
	var o = this.getItem(key);
	this.storage[key] = val;
	this.fireEvent('update', {
		type: 'set',
		key: key,
		newVal: val,
		oldVal: o
	});
};

/**
 * @param {string} key
 * @param {*} val
 */
PropertyStorage.prototype.setObject = function(key, val) {
	this.setItem(key, typeof val === 'string' ? val : JSON.stringify(val));
};

/** @param {string} key */
PropertyStorage.prototype.unset = function(key) {
	if (key in this.storage) {
		var val = this.storage[key];
		delete this.storage[key];
		this.fireEvent('update', {
			type: 'remove',
			key: key,
			oldVal: val,
			newVal: null
		});
	}
};

/**
 * @param {string} key
 * @return {boolean}
 */
PropertyStorage.prototype.contains = function(key) {
	return key in this.storage || key in this.defaults;
};

/** @return {Array} */
PropertyStorage.prototype.keys = function() {
	var storage = this.storage;
	var arr = [];
	for (var key in storage) arr.push(key);
	return arr;
};

PropertyStorage.prototype.clear = function() {
	var keys = this.keys();
	var storage = this.storage;
	for (var i = 0, il = keys.length; i < il; i++) {
		delete storage[keys[i]];
	}
	this.fireEvent('clear');
};

/** @return {number} */
PropertyStorage.prototype.length = function() {
	return this.keys().length;
};
