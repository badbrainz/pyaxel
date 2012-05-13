var background = chrome.extension.getBackgroundPage();
var timeout = null;

var connhandler = {
    onconnevent: function(sender, response) {
        var event = response.event;
        if (event === ConnectionEvent.CONNECTED) {
            sender.send({
                cmd: ServerCommand.IDENT,
                arg: {
                    type: 'MGR',
                    dlpath: background.getPreference('prefs.path'),
                    splits: background.getPreference('prefs.splits', true),
                    bw: background.getPreference('prefs.bandwidth', true)
                }
            });
        }
        else if (event === ConnectionEvent.DISCONNECTED) {} else if (event === ConnectionEvent.ERROR) {
            showTooltip(false, 'Not connected');
        }
    },

    onmsgevent: function(sender, response) {
        var event = response.event;
        if (event === MessageEvent.ACK) {
            showTooltip(true, 'Preferences saved');
            sender.disconnect();
        }
    }
};

function showTooltip(type, msg) {
    setTimeout(function() {
        var node = document.querySelector('#infoTip');
        node.innerText = msg;
        node.classList.add('slide');
        if (type) {
            node.classList.add('success');
            node.classList.remove('failure');
        }
        else {
            node.classList.add('failure');
            node.classList.remove('success');
        }
        if (timeout) clearTimeout(timeout);
        timeout = setTimeout(function() {
            node.classList.remove('slide');
        }, 5000);
    }, 400);
}

function check_number_input(input) {
    var val = Number(input.value.trim());
    if (val === 0) return;
    var min = Number(input.min);
    var max = Number(input.max);
    if (isNaN(val)) { // chrome bug: input accepts 'e' for number-type inputs
        showTooltip(false, 'Value must be a number');
        input.value = background.getPreference(formatString('prefs.{0}', input.id));
    }
    else if (val < min) showTooltip(false, formatString('Min value is {0}', min));
    else if (val > max) showTooltip(false, formatString('Max value is {0}', max));
}

document.addEventListener('DOMContentLoaded', function() {
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
    var tabs = [tab0, tab1, tab2];
    tab0.panel = document.querySelector('#panel0');
    tab1.panel = document.querySelector('#panel1');
    tab2.panel = document.querySelector('#panel2');

    var version = document.querySelector('#version');
    version.innerText = background.getPreference('data.version');

    hostname.value = background.getPreference('prefs.host');
    portnum.value = background.getPreference('prefs.port');
    location.value = background.getPreference('prefs.path');
    maxsplits.value = background.getPreference('prefs.splits');
    maxdownloads.value = background.getPreference('prefs.downloads');
    bandwidth_inp.value = background.getPreference('prefs.bandwidth');

    save_btn.onclick = function() {
        var host = hostname.value.trim();
        var port = Number(portnum.value.trim());
        var path = location.value.trim();
        var bandwidth = Number(bandwidth_inp.value.trim());
        var splits = clamp(Number(maxsplits.value.trim()), Number(maxsplits.min), Number(maxsplits.max));
        var downloads = clamp(Number(maxdownloads.value.trim()), Number(maxdownloads.min), Number(maxdownloads.max));

        if (path === '' || regex.valid_path.test(path)) background.setPreference('prefs.path', path);
        if (host !== '' && regex.valid_ip.test(host)) background.setPreference('prefs.host', host);
        background.setPreference('prefs.port', port);
        background.setPreference('prefs.splits', splits);
        background.setPreference('prefs.downloads', downloads);
        background.setPreference('prefs.bandwidth', bandwidth);

        var connection = ConnectionFactory.createConnection(formatString('ws://{0}:{1}', background.getPreference('prefs.host'), port));
        connection.connevent.attach(connhandler.onconnevent);
        connection.msgevent.attach(connhandler.onmsgevent);
        connection.connect();
    }

    document.querySelector('#echo').onclick = function(e) {
        var host = hostname.value.trim();
        if (host === '' || !regex.valid_ip.test(host)) return;
        var button = e.target;
        var connection = ConnectionFactory.createConnection(formatString('ws://{0}:{1}', host, Number(portnum.value.trim())));
        connection.connevent.attach(function(sender, response) {
            var event = response.event;
            if (event === ConnectionEvent.CONNECTED) {
                sender.send({
                    cmd: ServerCommand.IDENT,
                    arg: {
                        type: 'ECHO',
                        msg: +new Date
                    }
                });
            }
            else if (event === ConnectionEvent.DISCONNECTED) {
                showTooltip(true, 'Connection successful');
            }
            else if (event === ConnectionEvent.ERROR) {
                showTooltip(false, 'Connection failed');
            }
            button.removeAttribute('disabled');
        });
        connection.connect();
        button.setAttribute('disabled', 'disabled');
    }

    function activatetab() {
        tabs.forEach(function(e) {
            e.classList.remove('curr');
            e.panel.classList.remove('curr');
        }, this);
        this.classList.add('curr');
        this.panel.classList.add('curr');
    }

    tab0.classList.add('curr');
    tab0.panel.classList.add('curr');
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
        if (val === '' || isNaN(val) || val < 0) this.value = background.getPreference('prefs.bandwidth');
        else this.value = val; // webkit makes it zero for us
    }
    portnum.onblur = function() {
        var val = Number(this.value.trim());
        if (val === '' || isNaN(val) || val <= 0) this.value = background.getPreference('prefs.port');
    }
}, false);
