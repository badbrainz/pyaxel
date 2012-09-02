var Job = function(url) {
    this.id = id();
    this.url = url;
};

var jobqueue = {};
jobqueue.catalog = {};
jobqueue.catalog.all = {};
jobqueue.catalog.active = {};
jobqueue.catalog.completed = {};
jobqueue.catalog.unassigned = {};
jobqueue.jobs = new Queue();

jobqueue.new = function(url) {
    return new Job(url);
};

jobqueue.add = function(item, queue) {
    var job = (item instanceof Job && item) || jobqueue.new(item);
    jobqueue.catalog.all[job.id] = job;
    jobqueue.catalog.unassigned[job.id] = job;
    if (!queue)
        jobqueue.jobs.put(job);
};

jobqueue.cancel = function(id) {
    delete jobqueue.catalog.unassigned[id];
    delete jobqueue.catalog.active[id];

    jobqueue.catalog.completed[id] = jobqueue.catalog.all[id];
};

jobqueue.retry = function(id) {
    if (!(id in jobqueue.catalog.completed ||
        id in jobqueue.catalog.unassigned))
        return;

    var job = jobqueue.catalog.completed[id] ||
        jobqueue.catalog.unassigned[id];

    delete jobqueue.catalog.completed[id];
    delete jobqueue.catalog.unassigned[id];

    jobqueue.add(job);
};

jobqueue.remove = function(id) {
    delete jobqueue.catalog.all[id];
    delete jobqueue.catalog.active[id];
    delete jobqueue.catalog.completed[id];
    delete jobqueue.catalog.unassigned[id];
};

jobqueue.clear = function() {
    for (var k in jobqueue.catalog.completed) {
        delete jobqueue.catalog.completed[k];
        delete jobqueue.catalog.all[k];
    }
};

jobqueue.search = function(id) {
    if (typeof id === 'string') {
        if (id in jobqueue.catalog)
            return getValues(jobqueue.catalog[id]);
        return [];
    }
    return jobqueue.catalog.all[id];
};

jobqueue.get = function() {
    var job = jobqueue.jobs.get();
    if (job) {
        if (!(job.id in jobqueue.catalog.unassigned))
            return jobqueue.get();
        delete jobqueue.catalog.unassigned[job.id];
    }
    return job;
};

jobqueue.size = function() {
    return jobqueue.jobs.size();
};

jobqueue.jobStarted = function(job) {
    jobqueue.catalog.active[job.id] = job;
};

jobqueue.jobStopped = function(job) {
    delete jobqueue.catalog.unassigned[job.id];
    delete jobqueue.catalog.active[job.id];
    jobqueue.catalog.completed[job.id] = job;
};

jobqueue.jobCompleted = function(job) {
    delete jobqueue.catalog.active[job.id];
    jobqueue.catalog.completed[job.id] = job;
};

jobqueue.jobFailed = function(job) {
    delete jobqueue.catalog.active[job.id];
    jobqueue.catalog.completed[job.id] = job;
};
