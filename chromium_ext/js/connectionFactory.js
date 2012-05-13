var ConnectionFactory = {}

ConnectionFactory.timeout = 5;
ConnectionFactory.max_retries = 3;
//ConnectionFactory.Adapters = {}

ConnectionFactory.createConnection = function(address) {
    var str = address || "ws://{0}:{1}".format(Preferences.getItem("prefs.host"), Preferences.getItem("prefs.port"));
    return new Connection(str, ConnectionFactory.max_retries, ConnectionFactory.timeout);
}
