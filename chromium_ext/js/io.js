var io = {};

io.http = function(url, callback, text) {
    var xhr = new XMLHttpRequest();
    var timeout = window.setTimeout(function() {
        xhr.abort();
        console.error('Request timeout:', url);
    }, 10000);
    xhr.onreadystatechange = function() {
        if (xhr.readyState == XMLHttpRequest.DONE) {
            window.clearTimeout(timeout);
            if (xhr.status == 200)
                callback(!text ? xhr.responseXML : xhr.responseText);
            else
                console.error('HTTP error:', xhr.statusText);
        }
    }
    if (!text)
        xhr.overrideMimeType('text/xml');
    xhr.open('GET', url, true);
    xhr.send();
};
