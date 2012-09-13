var io = {};

io.ajax = function(url, callback) {
    var req = new XMLHttpRequest();
    req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE)
            if (req.status == 200)
                callback(req.responseText);
    }
    req.open('GET', url, true);
    req.send();
};
