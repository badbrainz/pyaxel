/*
 * try switching to indexedDB if/when it becomes available
 */
var history = {};
history.db = null;
history.queries = {
    insert: "INSERT INTO history(url, date) VALUES (?,?)",
    remove: "DELETE FROM history WHERE ID=?",
    update: "UPDATE history SET url=?, date=? WHERE ID=?",
    retrieve_all: "SELECT * FROM history"
};

history.init = function() {
    try {
        history.db = openDatabase("history", "1.0", "Download history", 5 * 1024 * 1024);
        history.query("CREATE TABLE IF NOT EXISTS history(ID INTEGER PRIMARY KEY ASC, url TEXT, status TEXT, date DATETIME)", []);
    } catch (e) { console.log("Error: Couldn't setup the database:", e); }
}

history.addItem = function(url) {
    history.query(history.queries.insert, [url, today()]);
}

history.remove = function(id) {
    history.query(history.queries.remove, [id]);
}

history.retrieveAll = function(callback) {
    history.query(history.queries.retrieve_all, [], function(tx, results) {
        var items = [];
        for (var i=0, il=results.rows.length; i<il; i++)
            items.push(results.rows.item(i));
        callback(items);
    });
}

history.update = function(id, url, date) {
    history.query(history.queries.update, [id, url, date]);
}

history.query = function(sql, values, onsuccess, onerror) {
    if (!history.db) {
        console.log("Error: database doesn't exist <%s>", sql);
        return;
    }

    history.db.transaction(function(t) {
        t.executeSql(sql, values, onsuccess, onerror);
    });
}
