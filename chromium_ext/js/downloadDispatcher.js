var DownloadDispatcher = {}

DownloadDispatcher.downloadUpdated = function(download) {
    switch (download.status) {
        case DownloadStatus.INITIALIZING:
            DownloadManager.jobStarted(download);
        break;
        case DownloadStatus.COMPLETE:
            DownloadManager.jobCompleted(download);
        break;
        case DownloadStatus.ERROR:
            DownloadManager.jobFailed(download);
        break;
    }

    DownloadManager.update(download);
}
