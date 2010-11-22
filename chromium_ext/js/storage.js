var Preferences = function() {
  var storage = window.localStorage,
  defaults = {
    "data.version": null,
    "prefs.host": "127.0.0.1",
    "prefs.port": 8002,
    "prefs.downloads": 2,
    "prefs.bandwidth": 0,
    "prefs.splits": 4,
    "prefs.path": ""
  };
  return {
    key: function(s) {
      if (s >= storage.length) { return null }
      else { return storage.key(s) }
    },
    getItem: function(s) {
      var i = storage.getItem(s !== null ? s : "null");
      return (i !== null ? i : defaults.hasOwnProperty(s) ? defaults[s] : null);
    },
    setItem: function(s, t) {
      storage.setItem(s !== null ? s : "null", t !== null ? t : "null");
    },
    removeItem: function(s) {
      storage.removeItem(s !== null ? s : "null");
    },
    clear: function() {
      storage.clear();
    },
    contains: function(s) {
      return storage.getItem(s !== null ? s : "null") !== null;
    },
    keys: function() {
      var t = [];
      for (var i = 0, j = storage.length; i < j; i++) { t.push(storage.key(i)) }
      return t;
    },
    getObject: function(u) {
      var i = Preferences.getItem(u);
      return i !== null ? JSON.parse(typeof i !== "string" ? JSON.stringify(i) : i) : null;
    },
    setObject: function(v, w) {
      var u = JSON.stringify(w);
      storage.setItem(v !== null ? v : "null", u);
    },
    length: function() {
      return storage.length;
    }
  };
}();
