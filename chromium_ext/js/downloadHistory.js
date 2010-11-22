/*
 * try switching to indexedDB if/when it becomes available
 */
var DownloadHistory = {}

DownloadHistory.db = null;

DownloadHistory.Queries = {
    insert: "INSERT INTO history(url, date) VALUES (?,?)",
    remove: "DELETE FROM history WHERE ID=?",
    update: "UPDATE history SET url=?, date=? WHERE ID=?",
    retrieve_all: "SELECT * FROM history"
};

DownloadHistory.init = function() {
    try {
        DownloadHistory.db = openDatabase("DownloadHistory", "1.0", "Download history", 5 * 1024 * 1024);
        DownloadHistory.query("CREATE TABLE IF NOT EXISTS history(ID INTEGER PRIMARY KEY ASC, url TEXT, status TEXT, date DATETIME)", []);
    } catch (e) { console.log("Error: Couldn't setup the database:", e); }
}

DownloadHistory.addItem = function(url) {
    DownloadHistory.query(DownloadHistory.Queries.insert, [url, (new Date()).today()]);
}

DownloadHistory.remove = function(id) {
    DownloadHistory.query(DownloadHistory.Queries.remove, [id]);
}

DownloadHistory.retrieveAll = function(callback) {
    DownloadHistory.query(DownloadHistory.Queries.retrieve_all, [], function(tx, results) {
        var items = [];
        for (var i=0, il=results.rows.length; i<il; i++)
            items.push(results.rows.item(i));
        callback(items);
    });
}

DownloadHistory.update = function(id, url, date) {
    DownloadHistory.query(DownloadHistory.Queries.update, [id, url, date]);
}

DownloadHistory.query = function(sql, values, onsuccess, onerror) {
    if (!DownloadHistory.db) {
        console.log("Error: database doesn't exist <%s>", sql);
        return;
    }

    DownloadHistory.db.transaction(function(t) {
        t.executeSql(sql, values, onsuccess, onerror);
    });
}
