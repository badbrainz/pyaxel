function notifyUpdate() {
    if (Date.now() - preferences.getItem('data.lastUpdate') >= 1000 * 60) {
        // TODO send request
        window.localStorage['data.lastUpdate'] = Date.now();
        var request = new XMLHttpRequest();
        request.open('GET', chrome.extension.getURL('manifest.json'), true);
        request.onreadystatechange = function() {
            if (request.readyState == XMLHttpRequest.DONE) {
                if (request.status == 200) {
                    var manifest = JSON.parse(request.responseText);
                    preferences.setItem('data.version', manifest.version);
                     check python script version
                    request.open('GET', 'http:pyaxelws.googlecode.com/hg/version.txt', true);
                    request.onreadystatechange = function() {
                    console.log(request)
                        if (request.readyState == XMLHttpRequest.DONE) {
                            if (request.status == 200) {
                                sendNotification(text);
                                var data = JSON.parse(request.responseText);
                                var build = data.version.split('.');
                                var loc_build = window.localStorage['data.paversion'].split('.');
                                if (loc_build[0] < build[0] || loc_build[1] < build[1] || loc_build[2] < build[2]) {
                                    window.localStorage['data.paversion'] = data.version;
                                    window.setTimeout(sendNotification, 10000, addQueryPart(url, {
                                        title: 'Your version of pyaxelws appears to be outdated.',
                                        dllink: 'http:goo.gl/AEoTH',
                                        chlink: 'http:goo.gl/9fcSt',
                                        version: data.version
                                    }));
                                }
                            }
                        };
                        request.send();
                    }
                }
            }
            request.send();
        }
    }
}
