var Queue = function() {
  this.queue = [];
  this.space = 0;
}

Queue.prototype = {
  size: function() {
    return this.queue.length - this.space;
  },

  put: function(element) {
    this.queue.push(element);
  },

  get: function() {
    var element = undefined;

    if (this.queue.length) {
      element = this.queue[this.space];
      if (++this.space * 2 >= this.queue.length) {
        this.queue = this.queue.slice(this.space);
        this.space = 0;
      }
    }

    return element;
  },

  oldest: function() {
    return this.queue.length ? this.queue[this.space] : undefined;
  }
};
