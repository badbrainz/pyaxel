var Download = function(url, id) {
    this.id = id;
    this.url = url;
    this.fsize = 0;
    this.size = "0b";
    this.fname = "";
    this.ftype = "";
    this.chunks = [];
    this.progress = [];
    this.percentage = 0;
    this.speed = "0K";
    this.date = (new Date()).today();
    this.status = DownloadStatus.UNDEFINED;
}

var DownloadManager = {}

DownloadManager.uniqueID = 1;
DownloadManager.catalog = {};
DownloadManager.activeCatalog = {};
DownloadManager.completedCatalog = {};
DownloadManager.unassignedCatalog = {};
//DownloadManager.processedJobs = new Queue();
DownloadManager.unassignedJobs = new Queue();

DownloadManager.addJob = function(url) {
    // no copies
    function duplicate(e) { return url === e.url; }
    if (DownloadManager.getUnassignedJobs().some(duplicate) || DownloadManager.getActiveJobs().some(duplicate))
        return;

    var id = "dl_" + DownloadManager.uniqueID++;
    var download = new Download(url, id);
    download.status = DownloadStatus.QUEUED;

    DownloadManager.catalog[id] = download;
    DownloadManager.unassignedCatalog[id] = download;
    DownloadManager.unassignedJobs.put(download);

    ConnectionManager.establishConnection();

    DownloadManager.update(download);
}

DownloadManager.cancelJob = function(id) {
    if (id in DownloadManager.unassignedCatalog) // may be in queued state
        delete DownloadManager.unassignedCatalog[id];

    if (id in DownloadManager.activeCatalog) // may be in processing state
        delete DownloadManager.activeCatalog[id];

    DownloadManager.completedCatalog[id] = DownloadManager.catalog[id];

    ConnectionManager.abort(id);
}

DownloadManager.pauseJob = function(id) {
    ConnectionManager.pause(id);
}

DownloadManager.resumeJob = function(id) {
    ConnectionManager.resume(id);
}

DownloadManager.remove = function(id) {
    if (id in DownloadManager.catalog)
        delete DownloadManager.catalog[id];

    if (id in DownloadManager.unassignedCatalog)
        delete DownloadManager.unassignedCatalog[id];

    if (id in DownloadManager.activeCatalog)
        delete DownloadManager.activeCatalog[id];

    if (id in DownloadManager.completedCatalog)
        delete DownloadManager.completedCatalog[id];

    DownloadManager.updateFullList();
}

DownloadManager.getJob = function() {
    var job = DownloadManager.unassignedJobs.get();
    if (job) {
        if (!(job.id in DownloadManager.unassignedCatalog))
            return DownloadManager.getJob();
        delete DownloadManager.unassignedCatalog[job.id];
        //DownloadManager.activeCatalog[job.id] = job;
    }
    return job;
}

DownloadManager.getJobCount = function() {
    return DownloadManager.unassignedJobs.size();
}

DownloadManager.hasJobs = function() {
    return !DownloadManager.unassignedJobs.empty();
}

DownloadManager.getUnassignedJobs = function() {
    return getValues(DownloadManager.unassignedCatalog);
}

DownloadManager.getCompletedJobs = function() {
    return getValues(DownloadManager.completedCatalog);
}

DownloadManager.getActiveJobs = function() {
    return getValues(DownloadManager.activeCatalog);
}

DownloadManager.getAllJobs = function() {
    return getValues(DownloadManager.catalog);
}

DownloadManager.eraseInactiveJobs = function() {
    //DownloadManager.completedCatalog = {};
    for (var k in DownloadManager.completedCatalog) {
        delete DownloadManager.completedCatalog[k];
        delete DownloadManager.catalog[k];
    }
    DownloadManager.updateFullList();
}

DownloadManager.jobCompleted = function(job) {
    delete DownloadManager.activeCatalog[job.id];
    DownloadManager.completedCatalog[job.id] = job;
}

DownloadManager.jobStarted = function(job) {
    DownloadManager.activeCatalog[job.id] = job;
}

DownloadManager.jobFailed = function(job) {
    //DownloadManager.activeCatalog[job.id] = job;
}

DownloadManager.update = function(job) {
    Background.notify([job]);
}

DownloadManager.updateActiveList = function() {
    Background.notify(DownloadManager.getActiveJobs());
}

DownloadManager.updateCompletedList = function() {
    Background.notify(DownloadManager.getCompletedJobs());
}

DownloadManager.updateFullList = function() {
    Background.notify(DownloadManager.getAllJobs(), true);
}

DownloadManager.getFullList = function() {
    return [].concat(DownloadManager.getCompletedJobs(), DownloadManager.getUnassignedJobs(), DownloadManager.getActiveJobs());
}

