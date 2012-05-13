var PropertyStorage = function(store, defaults) {
	this.storage = store || {};
	this.defaults = copy({}, defaults || {});
};

PropertyStorage.prototype.getItem = function(key, def) {
	var val = this.storage[key !== null ? key : 'null'];
	return (typeof val !== 'undefined' ? val : key in this.defaults ? this.defaults[key] : def);
};

PropertyStorage.prototype.getObject = function(key, def) {
	var val = this.getItem(key, def);
	return typeof val !== 'undefined' ? JSON.parse(typeof val === 'string' ? val : JSON.stringify(val)) : val;
};

PropertyStorage.prototype.getBoolean = function(key, def) {
	return Boolean(this.getObject(key, def));
};

PropertyStorage.prototype.setItem = function(key, val) {
	key = key !== null ? key : 'null';
	val = val !== null ? val : 'null';
	this.storage[key] = val;
};

PropertyStorage.prototype.setObject = function(key, val) {
	this.setItem(key, typeof val === 'string' ? val : JSON.stringify(val));
};

PropertyStorage.prototype.unset = function(key) {
	if (key in this.storage)
		delete this.storage[key];
};

PropertyStorage.prototype.contains = function(key) {
	return key in this.storage || key in this.defaults;
};

PropertyStorage.prototype.keys = function() {
	var arr = [];
	for (var key in this.storage) arr.push(key);
	return arr;
};

PropertyStorage.prototype.clear = function() {
	var keys = this.keys();
	var storage = this.storage;
	for (var i = 0, il = keys.length; i < il; i++)
		delete storage[keys[i]];
};

PropertyStorage.prototype.length = function() {
	return this.keys().length;
};
