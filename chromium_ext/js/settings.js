function check_server() {
    var host = settings.hostname.value.trim();
    if (host === '' || !regex.valid_ip.test(host)) return;
    var connection = new Connection(formatString('ws://{0}:{1}/testing', host,
        settings.portnum.value.trim()));
    connection.connevent.attach(function(sender, response) {
        var event = response.event;
        if (event === ConnectionEvent.CONNECTED) {
            sender.send({
                'cmd': ServerCommand.IDENT,
                'arg': {
                    'type': 'ECHO',
                    'msg': +new Date
                }
            });
        }
        else if (event === ConnectionEvent.DISCONNECTED)
            message(1, 'Connection successful');
        else if (event === ConnectionEvent.ERROR)
            message(0, 'Connection failed');
        settings.echo.removeAttribute('disabled');
    });
    connection.connect();
    settings.echo.setAttribute('disabled', 'disabled');
}

function show_tooltip(type, msg) {
    var node = document.querySelector('#infoTip');
    node.innerText = msg;
    node.classList.add('slide');
    switch (type) {
    case 0:
        node.classList.add('failure');
        node.classList.remove('success');
        break;
    case 1:
        node.classList.add('success');
        node.classList.remove('failure');
        break;
    }
}

function hide_tooltip() {
    document.querySelector('#infoTip').classList.remove('slide');
}

function message(type, msg) {
    show_tooltip(type, msg)

    if (settings.noteid !== -1)
        window.clearTimeout(settings.noteid);
    settings.noteid = window.setTimeout(hide_tooltip, 5000);
}

function activate_tab(e) {
    var tabs = settings.tabs;
    for (var i=0; i < tabs.length; i++) {
        if (e.target === tabs[i]) {
            e.target.classList.add('curr');
            settings.panels[i].classList.add('curr');
            continue;
        }
        tabs[i].classList.remove('curr');
        settings.panels[i].classList.remove('curr');
    }
}

function validate_input(e) {
    var v = e.target.value.trim();
    if ('host' === e.target.id) {
        if (v && !regex.valid_ip.test(v))
            return 'Invalid address';
    }

    else if ('path' === e.target.id) {
        if (v && !regex.valid_path.test(v))
            return 'Invalid path';
    }

    else if ('port' === e.target.id || 'speed' === e.target.id) {
        if (!v || isNaN(v) || v < 0)
            return 'Invalid number';
    }

    else if ('splits' === e.target.id || 'downloads' === e.target.id) {
        if (v && isNaN(v) || v < 0)
            return 'Invalid number';
        if (e.target.value < +e.target.min)
            return 'Min value is ' + e.target.min;
        if (e.target.value > +e.target.max)
            return 'Max value is ' + e.target.max;
    }
}

function check_character(e) {
    if (e.keyCode === 13)
        e.target.blur();
    else if (e.keyCode === 27) {
        e.target.value = 1; // bug?
        e.target.value = settings.background.getPreference('prefs.' + e.target.id);
    }
}

function save_input(e) {
    var input = e.target;
    var err = validate_input(e);
    if (!err) {
        settings.background.setPreference('prefs.' + input.id, e.target.value);
        return;
    }
    err.trim() && message(0, err);
    input.value = settings.background.getPreference('prefs.' + input.id);
}

var events = {
    blur: {
        'host': save_input,
        'port': save_input,
        'path': save_input,
        'speed': save_input,
        'splits': save_input,
        'downloads': save_input,
    },

    keyup: {
        'host': check_character,
        'port': check_character,
        'path': check_character,
        'splits': check_character,
        'downloads': check_character,
        'speed': check_character,
    },

    click: {
        'settingstab': activate_tab,
        'manualtab': activate_tab,
        'abouttab': activate_tab,
        'echo': check_server
    }
};

var settings = {
    background: chrome.extension.getBackgroundPage(),
    echo:null,
    hostname:null,
    path:null,
    maxsplits:null,
    maxdownloads:null,
    portnum:null,
    speed_inp:null,
    version:null,
    tabbar:null,
    panels:null,
    tabs:null,
    noteid: -1,

    handleEvent: function(e) {
        if (e.type === 'click') {
            if (!e.target.hasAttribute('disabled') && e.target.id in events.click)
                events.click[e.target.id].call(window, e);
        }

        else if (e.type === 'blur') {
            if (!e.target.hasAttribute('disabled') && e.target.id in events.blur)
                events.blur[e.target.id].call(window, e);
        }

        else if (e.type === 'input') {
            if (!e.target.hasAttribute('disabled') && e.target.id in events.input)
                events.input[e.target.id].call(window, e);
        }

        else if (e.type === 'keyup') {
            if (!e.target.hasAttribute('disabled') && e.target.id in events.keyup)
                events.keyup[e.target.id].call(window, e);
        }

        else if (e.type === 'DOMContentLoaded') {
            with (settings) {
                var d = document;
                hostname = d.querySelector('#host');
                portnum = d.querySelector('#port');
                path = d.querySelector('#path');
                maxsplits = d.querySelector('#splits');
                maxdownloads = d.querySelector('#downloads');
                speed_inp = d.querySelector('#speed');
                tabbar = d.querySelector('#tabbar');
                version = d.querySelector('#version');
                echo = d.querySelector('#echo');
                tabs = [d.querySelector('#settingstab'),
                    d.querySelector('#manualtab'),
                    d.querySelector('#abouttab')];
                panels = [d.querySelector('#settingspanel'),
                    d.querySelector('#manualpanel'),
                    d.querySelector('#aboutpanel')];

                version.innerText = background.getPreference('data.version');
                hostname.value = background.getPreference('prefs.host');
                portnum.value = background.getPreference('prefs.port');
                path.value = background.getPreference('prefs.path');
                maxsplits.value = background.getPreference('prefs.splits');
                maxdownloads.value = background.getPreference('prefs.downloads');
                speed_inp.value = background.getPreference('prefs.speed');
            }

            settings.tabs[0].classList.add('curr');
            settings.panels[0].classList.add('curr');
            settings.panels[0].addEventListener('blur', settings, true);
            settings.panels[0].addEventListener('click', settings, false);
            settings.panels[0].addEventListener('keyup', settings, true);
            settings.tabbar.addEventListener('click', settings, false);
        }
    }
};

document.addEventListener('DOMContentLoaded', settings, false);
