var wnd = window;
document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("downloads").addEventListener("click", function () {
        wnd.close();
        chrome.extension.getBackgroundPage().displayPage("downloads.html");
    }, false);
    document.getElementById("preferences").addEventListener("click", function () {
        wnd.close();
        chrome.extension.getBackgroundPage().displayPage("settings.html");
    }, false);
}, false);
