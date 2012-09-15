var io = {};

io.http = function(url, callback, type) {
    var req = new XMLHttpRequest();
    req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE)
            if (req.status == 200)
                callback(!type ? req.responseXML : req.responseText);
    }
    req.open('GET', url, true);
    req.send();
};
