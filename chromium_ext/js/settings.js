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

function show_advanced_options(show) {
    var elms = document.getElementsByClassName('extra');
    if (show)
        for (var i = 0; i < elms.length; i++)
            elms[i].classList.remove('hidden');
    else
        for (var i = 0; i < elms.length; i++)
            elms[i].classList.add('hidden');
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

function activate_advanced_options(e) {
    show_advanced_options(e.target.checked);
}

function validate_input(e) {
    if (e.target.type === 'text' || e.target.type === 'number') {
        var v = e.target.value.trim();
        if ('host' === e.target.id) {
            if (v && !regex.valid_ip.test(v))
                return 'Invalid address';
        }

        else if ('path' === e.target.id) {
            if (v && !regex.valid_path.test(v))
                return 'Invalid path';
        }

        else if ('port' === e.target.id||
            'speed' === e.target.id ||
            'reconnect' === e.target.id ||
            'delay' === e.target.id) {
            if (!v || isNaN(v) || v < 0)
                return 'Invalid number';
        }

        else if ('splits' === e.target.id ||
            'downloads' === e.target.id) {
            if (v && isNaN(v) || v < 0)
                return 'Invalid number';
            if (e.target.value < +e.target.min)
                return 'Min value is ' + e.target.min;
            if (e.target.value > +e.target.max)
                return 'Max value is ' + e.target.max;
        }
    }
}

function get_input_value(elm) {
    if (elm.type === 'text' || elm.type === 'number')
        return elm.value.trim();
    else if (elm.type === 'checkbox')
        return +elm.checked;
}

function set_input_value(elm, val) {
    if (elm.type === 'text' || elm.type === 'number')
        elm.value = val;
    else if (elm.type === 'checkbox')
        elm.checked = val;
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
        settings.background.setPreference('prefs.' + input.id, get_input_value(input));
        return;
    }
    err.trim() && message(0, err);
    set_input_value(input, settings.background.getPreference('prefs.' + input.id));
}

var events = {
    blur: {
        'delay': save_input,
        'downloads': save_input,
        'host': save_input,
        'reconnect': save_input,
        'port': save_input,
        'path': save_input,
        'speed': save_input,
        'splits': save_input
    },

    keyup: {
        'delay': check_character,
        'downloads': check_character,
        'host': check_character,
        'reconnect': check_character,
        'port': check_character,
        'path': check_character,
        'splits': check_character,
        'speed': check_character
    },

    click: {
        'abouttab': activate_tab,
        'echo': check_server,
        'manualtab': activate_tab,
        'options': [save_input, activate_advanced_options],
        'output': save_input,
        'settingstab': activate_tab,
        'uitab': activate_tab
    }
};

var settings = {
    background:null,
    delay:null,
    echo:null,
    hostname:null,
    path:null,
    maxsplits:null,
    maxdownloads:null,
    maxreconns:null,
    options:null,
    portnum:null,
    speed_inp:null,
    version:null,
    tabbar:null,
    panels:null,
    tabs:null,
    noteid:-1,

    handleEvent: function(e) {
        if (e.type in events) {
            if (!e.target.hasAttribute('disabled') && e.target.id in events[e.type]) {
                if (typeOf(events.click[e.target.id]) == 'array')
                    for (var i = 0; i < events.click[e.target.id].length; i++)
                        events[e.type][e.target.id][i].call(window, e);
                else
                    events[e.type][e.target.id].call(window, e);
            }
        }

        else if (e.type === 'DOMContentLoaded') {
            with (settings) {
                var d = document;

                delay = d.querySelector('#delay');
                echo = d.querySelector('#echo');
                hostname = d.querySelector('#host');
                maxsplits = d.querySelector('#splits');
                maxdownloads = d.querySelector('#downloads');
                maxreconns = d.querySelector('#reconnect');
                output = d.querySelector('#output');
                portnum = d.querySelector('#port');
                path = d.querySelector('#path');
                options = d.querySelector('#options');
                speed_inp = d.querySelector('#speed');
                version = d.querySelector('#version');

                tabbar = d.querySelector('#tabbar');
                tabs = [d.querySelector('#settingstab'),
                    d.querySelector('#uitab'),
                    d.querySelector('#manualtab'),
                    d.querySelector('#abouttab')];
                panels = [d.querySelector('#settingspanel'),
                    d.querySelector('#uipanel'),
                    d.querySelector('#manualpanel'),
                    d.querySelector('#aboutpanel')];

                background = chrome.extension.getBackgroundPage();
                delay.value = background.getPreference('prefs.delay');
                hostname.value = background.getPreference('prefs.host');
                maxsplits.value = background.getPreference('prefs.splits');
                maxdownloads.value = background.getPreference('prefs.downloads');
                maxreconns.value = background.getPreference('prefs.reconnect');
                output.checked = +background.getPreference('prefs.output');
                options.checked = +background.getPreference('prefs.options');
                portnum.value = background.getPreference('prefs.port');
                path.value = background.getPreference('prefs.path');
                speed_inp.value = background.getPreference('prefs.speed');
                version.innerText = background.getPreference('data.version');
            }

            show_advanced_options(options.checked);

            settings.tabs[0].classList.add('curr');
            settings.panels[0].classList.add('curr');
            settings.panels[0].addEventListener('blur', settings, true);
            settings.panels[0].addEventListener('click', settings, false);
            settings.panels[0].addEventListener('keyup', settings, true);
            settings.panels[1].addEventListener('blur', settings, true);
            settings.panels[1].addEventListener('click', settings, false);
            settings.panels[1].addEventListener('keyup', settings, true);
            settings.tabbar.addEventListener('click', settings, false);
        }
    }
};

document.addEventListener('DOMContentLoaded', settings, false);
