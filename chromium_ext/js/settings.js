function save_settings() {
    var host = settings.hostname.value.trim();
    var port = Number(settings.portnum.value.trim());
    var path = settings.location.value.trim();
    var speed = Number(settings.speed_inp.value.trim());
    var splits = clamp(Number(settings.maxsplits.value.trim()),
        Number(settings.maxsplits.min), Number(settings.maxsplits.max));
    var downloads = clamp(Number(settings.maxdownloads.value.trim()),
        Number(settings.maxdownloads.min), Number(settings.maxdownloads.max));

    if (path === '' || regex.valid_path.test(path)) settings.background.setPreference('prefs.path', path);
    if (host !== '' && regex.valid_ip.test(host)) settings.background.setPreference('prefs.host', host);
    settings.background.setPreference('prefs.port', port);
    settings.background.setPreference('prefs.splits', splits);
    settings.background.setPreference('prefs.downloads', downloads);
    settings.background.setPreference('prefs.speed', speed);
    show_tooltip(1, 'Preferences saved');
}

function check_server() {
    var host = settings.hostname.value.trim();
    if (host === '' || !regex.valid_ip.test(host)) return;
    var connection = new Connection(formatString('ws://{0}:{1}/testing', host,
        Number(settings.portnum.value.trim())));
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
        else if (event === ConnectionEvent.DISCONNECTED)
            show_tooltip(1, 'Connection successful');
        else if (event === ConnectionEvent.ERROR)
            show_tooltip(0, 'Connection failed');
        settings.echo.removeAttribute('disabled');
    });
    connection.connect();
    settings.echo.setAttribute('disabled', 'disabled');
}

function add_class(elm, name) {
    elm.classList.add(name);
}

function remove_class(elm, name) {
    elm.classList.remove(name);
}

function show_tooltip(type, msg) {
    window.setTimeout(function() {
        var node = document.querySelector('#infoTip');
        node.innerText = msg;
        add_class(node, 'slide');
        switch (type) {
        case 0:
            add_class(node, 'failure');
            remove_class(node, 'success');
            break;
        case 1:
            add_class(node, 'success');
            remove_class(node, 'failure');
            break;
        }
        if (settings.noteid) window.clearTimeout(settings.noteid);
        settings.noteid = window.setTimeout(remove_class, 5000, node, 'slide');
    }, 400);
}

function activatetab(e) {
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

function checkinput(e) {
    var input = e.target;
    if (['splits','downloads','speed','port'].indexOf(input.id) != -1) {
        if (isNaN(input.value)) {
            show_tooltip(0, 'Value must be a number');
            return;
        }
    }
    if (input.type === 'number') {
        if (input.value && !isNaN(input.value)) {
            var min = parseInt(input.min);
            var max = parseInt(input.max);
            if (input.val < min) show_tooltip(0, 'Min value is ' + min);
            else if (input.val > max) show_tooltip(0, 'Max value is ' + max);
        }
    }
}

function validate(e) {
    var input = e.target;
    if (['splits','downloads','speed','port'].indexOf(input.id) != -1) {
        if (!input.value.trim() || isNaN(input.value)) {
            input.value = settings.background.getPreference('prefs.' + input.id);
            return;
        }
    }
    if (input.type === 'number') {
        input.value = clamp(parseInt(input.value), parseInt(input.min), parseInt(input.max));
    }
}

var events = {
    blur: {
        'splits': validate,
        'downloads': validate,
        'port': validate,
        'speed': validate
    },

    input: {
        'speed': checkinput,
        'splits': checkinput,
        'downloads': checkinput,
        'port': checkinput
    },

    click: {
        'settingstab': activatetab,
        'manualtab': activatetab,
        'abouttab': activatetab,
        'save': save_settings,
        'echo': check_server
    }
};

var settings = {
    background: chrome.extension.getBackgroundPage(),
    echo:null,
    hostname:null,
    location:null,
    maxsplits:null,
    maxdownloads:null,
    portnum:null,
    speed_inp:null,
    save_btn:null,
    version:null,
    tabbar:null,
    panels:null,
    tabs:null,
    noteid: null,

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

        else if (e.type === 'DOMContentLoaded') {
            with (settings) {
                var d = document;
                hostname = d.querySelector('#host');
                portnum = d.querySelector('#port');
                save_btn = d.querySelector('#save');
                location = d.querySelector('#location');
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
                location.value = background.getPreference('prefs.path');
                maxsplits.value = background.getPreference('prefs.splits');
                maxdownloads.value = background.getPreference('prefs.downloads');
                speed_inp.value = background.getPreference('prefs.speed');
            }

            settings.tabs[0].classList.add('curr');
            settings.panels[0].classList.add('curr');
            settings.panels[0].addEventListener('blur', settings, true);
            settings.panels[0].addEventListener('input', settings, true);
            settings.panels[0].addEventListener('click', settings, false);
            settings.tabbar.addEventListener('click', settings, false);
        }
    }
};

document.addEventListener('DOMContentLoaded', settings, false);
