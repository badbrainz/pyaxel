var wnd = window;
document.addEventListener("DOMContentLoaded", function () {
    if (!/Win/.test(navigator.platform)) {
        var k = document.getElementsByClassName('menuitem');
        var i = k.length;
        while (i--) k[i].classList.add('menuitem-decor');
    }
    document.getElementById("downloads").addEventListener("click", function () {
        wnd.close();
        chrome.extension.getBackgroundPage().displayPage("downloads.html");
    }, false);
    document.getElementById("preferences").addEventListener("click", function () {
        wnd.close();
        chrome.extension.getBackgroundPage().displayPage("settings.html");
    }, false);
}, false);
