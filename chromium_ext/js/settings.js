var connhandler = {
    onconnevent: function(sender, response) {
        var event = response.event;
        if (event === ConnectionEvent.CONNECTED) {
            sender.send({
                cmd: "IDENT",
                arg: {
                    type: "MGR",
                    dlpath: Preferences.getItem("prefs.path"),
                    splits: Preferences.getObject("prefs.splits"),
                    bw: Preferences.getObject("prefs.bandwidth")
                }
            });
        }
        else if (event === ConnectionEvent.DISCONNECTED) {
        }
        else if (event === ConnectionEvent.ERROR) {
            showTooltip(false, "Not connected!");
        }
    },

    onmsgevent: function(sender, response) {
        var event = response.event;
        if (event === MessageEvent.ACK) {
            showTooltip(true, "Preferences saved");
            sender.disconnect();
        }
    }
};

var timeout = null;
function showTooltip(type, msg) {
    setTimeout(function() {
        var node = document.querySelector("#infoTip");
        node.innerHTML = msg;
        CSS.addClass.call(node, "slide");
        if (type) {
            CSS.addClass.call(node, "success");
            CSS.removeClass.call(node, "failure");
        }
        else {
            CSS.addClass.call(node, "failure");
            CSS.removeClass.call(node, "success");
        }
        if (timeout)
            clearTimeout(timeout);
        timeout = setTimeout(function() {
            CSS.removeClass.call(node, "slide");
        }, 5000);
    }, 400);
}

function check_number_input(input) {
    var val = Number(input.value.trim());
    if (val === 0) return;
    var min = Number(input.min);
    var max = Number(input.max);
    if (isNaN(val)) {// chrome bug: input accepts 'e' for number-type inputs
        showTooltip(false, "Value must be a number.")
        input.value = Preferences.getItem("prefs.{0}".format(input.id));
    }
    else if (val < min)
        showTooltip(false, "Min value is {0}.".format(min));
    else if (val > max)
        showTooltip(false, "Max value is {0}.".format(max));
}

document.addEventListener("DOMContentLoaded", function() {
    var hostname = document.querySelector('#host');
    var portnum = document.querySelector('#port');
    var save_btn = document.querySelector('#save');
    var maxsplits = document.querySelector('#splits');
    var location = document.querySelector('#location');
    var maxdownloads = document.querySelector('#downloads');
    var bandwidth_inp = document.querySelector('#bandwidth');
    var tab0 = document.querySelector('#tab0');
    var tab1 = document.querySelector('#tab1');
    var tab2 = document.querySelector('#tab2');
    var tabs = [tab0,tab1,tab2];
    tab0.panel = document.querySelector('#panel0');
    tab1.panel = document.querySelector('#panel1');
    tab2.panel = document.querySelector('#panel2');

    var version = document.querySelector('#version');
    version.innerHTML = Preferences.getItem("data.version");

    hostname.value = Preferences.getItem("prefs.host");
    portnum.value = Preferences.getItem("prefs.port");
    location.value = Preferences.getItem("prefs.path");
    maxsplits.value = Preferences.getItem("prefs.splits");
    maxdownloads.value = Preferences.getItem("prefs.downloads");
    bandwidth_inp.value = Preferences.getItem("prefs.bandwidth");

    save_btn.onclick = function() {
        var host = hostname.value.trim();
        var port = Number(portnum.value.trim());
        var path = location.value.trim();
        var bandwidth = Number(bandwidth_inp.value.trim());
        var splits = clamp(Number(maxsplits.value.trim()), Number(maxsplits.min), Number(maxsplits.max));
        var downloads = clamp(Number(maxdownloads.value.trim()), Number(maxdownloads.min), Number(maxdownloads.max));

        if (path === "" || regex.valid_path.test(path))
            Preferences.setItem("prefs.path", path);
        if (host !== "" && regex.valid_ip.test(host))
            Preferences.setItem("prefs.host", host);
        Preferences.setItem("prefs.port", port);
        Preferences.setItem("prefs.splits", splits);
        Preferences.setItem("prefs.downloads", downloads);
        Preferences.setItem("prefs.bandwidth", bandwidth);

        var connection = ConnectionFactory.createConnection();
        connection.connevent.attach(connhandler.onconnevent);
        connection.msgevent.attach(connhandler.onmsgevent);
        connection.connect();
    }

    document.querySelector('#test').onclick = function() {
        var host = hostname.value.trim();
        if (host === "" || !regex.valid_ip.test(host)) return;
        var text = document.querySelector('#connstatus');
        var connection = ConnectionFactory.createConnection("ws://{0}:{1}".format(host, Number(portnum.value.trim())));
        connection.connevent.attach(function(sender, response) {
            var event = response.event;
            if (event === ConnectionEvent.CONNECTED) {
                sender.send({
                    cmd:"IDENT",
                    arg: {
                        type: "ECHO",
                        msg: "test"
                    }
                });
            }
            else if (event === ConnectionEvent.DISCONNECTED) {
                text.innerHTML = "Success";
                CSS.removeClass.call(text, "invalid");
            }
            else if (event === ConnectionEvent.ERROR) {
                text.innerHTML = "Failure";
                CSS.addClass.call(text, "invalid");
            }
        });
        connection.connect();
    }

    function activatetab() {
        tabs.forEach(function(e) {
            CSS.removeClass.call(e, "curr");
            CSS.removeClass.call(e.panel, "curr");
        }, this);
        CSS.addClass.call(this, "curr");
        CSS.addClass.call(this.panel, "curr");
    }

    CSS.addClass.call(tab0, "curr");
    CSS.addClass.call(tab0.panel, "curr");
    tab0.onclick = activatetab;
    tab1.onclick = activatetab;
    tab2.onclick = activatetab;

    function clamp_val() {
        this.value = clamp(Number(this.value.trim()), Number(this.min), Number(this.max));
    }

    maxsplits.onblur = clamp_val;
    maxdownloads.onblur = clamp_val;

    bandwidth_inp.onblur = function() {
        var val = Number(this.value.trim());
        if (val === "" || isNaN(val) || val < 0)
            this.value = Preferences.getItem("prefs.bandwidth");
        else
            this.value = val; // webkit makes it zero for us
    }
    portnum.onblur = function() {
        var val = Number(this.value.trim());
        if (val === "" || isNaN(val) || val <= 0)
            this.value = Preferences.getItem("prefs.port");
    }
}, false);
