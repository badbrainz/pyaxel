var Download = function(url, id) {
    this.id = id;
    this.url = url;
    this.fsize = 0;
    this.size = '0b';
    this.fname = '';
    this.ftype = '';
    this.chunks = [];
    this.progress = [];
    this.percentage = 0;
    this.speed = '0K';
    this.date = (new Date()).today();
    this.status = DownloadStatus.UNDEFINED;
};

var DownloadManager = {};
DownloadManager.uniqueID = 1;
DownloadManager.catalog = {};
DownloadManager.catalog._ = {};
DownloadManager.catalog.active = {};
DownloadManager.catalog.completed = {};
DownloadManager.catalog.unassigned = {};
DownloadManager.unassignedJobs = new Queue();

DownloadManager.addJob = function(job, wait) {
    var preset = job instanceof Download;
    var url = preset ? job.url : job;

    if (DownloadManager.hasJob(url))
        return;

    if (!preset)
        job = new Download(url, 'dl_' + DownloadManager.uniqueID++);

    job.status = DownloadStatus.QUEUED;
    DownloadManager.catalog._[job.id] = job;
    DownloadManager.catalog.unassigned[job.id] = job;
    if (!wait)
        DownloadManager.unassignedJobs.put(job);

    DownloadManager.update(job);

    ConnectionManager.establishConnection();
};

DownloadManager.cancelJob = function(id) {
    // may be in queued state
    delete DownloadManager.catalog.unassigned[id];

    // may be in processing state
    delete DownloadManager.catalog.active[id];

    DownloadManager.catalog.completed[id] = DownloadManager.catalog._[id];

    ConnectionManager.abort(id);
};

DownloadManager.retryJob = function(id) {
    // accept iff queued or completed
    if (!(id in DownloadManager.catalog.completed ||
        id in DownloadManager.catalog.unassigned))
        return;

    var download = DownloadManager.catalog.completed[id] ||
        DownloadManager.catalog.unassigned[id];

    delete DownloadManager.catalog.completed[id];
    delete DownloadManager.catalog.unassigned[id];

    DownloadManager.addJob(download);
};

DownloadManager.pauseJob = function(id) {
    ConnectionManager.pause(id);
};

DownloadManager.resumeJob = function(id) {
    ConnectionManager.resume(id);
};

DownloadManager.removeJob = function(id) {
    delete DownloadManager.catalog._[id];
    delete DownloadManager.catalog.active[id];
    delete DownloadManager.catalog.completed[id];
    delete DownloadManager.catalog.unassigned[id];

    DownloadManager.updateFullList();
};

DownloadManager.getJob = function() {
    var job = DownloadManager.unassignedJobs.get();
    if (job) {
        if (!(job.id in DownloadManager.catalog.unassigned))
            return DownloadManager.getJob();
        delete DownloadManager.catalog.unassigned[job.id];
        //        DownloadManager.catalog.active[job.id] = job;
    }
    return job;
};

DownloadManager.hasJob = function(url) {
    function duplicate(job) {
        return url === job.url;
    }
    return DownloadManager.getUnassignedJobs().some(duplicate) ||
        DownloadManager.getActiveJobs().some(duplicate);
};

DownloadManager.getUnassignedJobs = function() {
    return getValues(DownloadManager.catalog.unassigned);
};

DownloadManager.getCompletedJobs = function() {
    return getValues(DownloadManager.catalog.completed);
};

DownloadManager.getActiveJobs = function() {
    return getValues(DownloadManager.catalog.active);
};

DownloadManager.getAllJobs = function() {
    return getValues(DownloadManager.catalog._);
};

DownloadManager.getJobCount = function() {
    return DownloadManager.unassignedJobs.size();
};

DownloadManager.hasJobs = function() {
    return !DownloadManager.unassignedJobs.empty();
};

DownloadManager.eraseInactiveJobs = function() {
    //    DownloadManager.catalog.completed = {};
    for (var k in DownloadManager.catalog.completed) {
        delete DownloadManager.catalog.completed[k];
        delete DownloadManager.catalog._[k];
    }
    DownloadManager.updateFullList();
};

DownloadManager.jobStarted = function(job) {
    DownloadManager.catalog.active[job.id] = job;
};

DownloadManager.jobCompleted = function(job) {
    delete DownloadManager.catalog.active[job.id];
    DownloadManager.catalog.completed[job.id] = job;
};

DownloadManager.jobFailed = function(job) {
    //    DownloadManager.catalog.active[job.id] = job;
};

DownloadManager.update = function(job) {
    Background.notify([job]);
};

DownloadManager.updateActiveList = function() {
    Background.notify(DownloadManager.getActiveJobs());
};

DownloadManager.updateCompletedList = function() {
    Background.notify(DownloadManager.getCompletedJobs());
};

DownloadManager.updateFullList = function() {
    Background.notify(DownloadManager.getAllJobs());
};

DownloadManager.getFullList = function() {
    return DownloadManager.getAllJobs();
};
