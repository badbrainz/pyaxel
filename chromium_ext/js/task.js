var TaskManager = (function() {
    var tasks = [];
    var counter = 0;

    return {
        start: function(task) {
            var index = tasks.indexOf(task);
            var interval = ~~task.interval || 1000;
            if (index != -1) {
                task = tasks[index];
                task.timer.stop();
                task.timer.interval = interval;
                if (typeof task.timer._runid !== 'undefined') {
                    window.clearTimeout(task.timer._runid);
                    delete task.timer._runid;
                }
            }
            else {
                task.timer = new Timer(task.run.bind(task), interval);
                task.timer.name = task.name || 'timer' + counter++;
                tasks.push(task);
            }

            if (task.runAt) {
                task.timer._runid = window.setTimeout(function() {
                    delete task.timer._runid;
                    task.timer.start();
                    task.run();
                }, task.runAt - Date.now());
            }
            else
                task.timer.start();
        },

        kill: function(task) {
            if (typeof task === 'string') {
                for (var i = 0; i < tasks.length; i++)
                    if (tasks[i].timer.name === task) {
                        tasks[i].timer.stop();
                        tasks.splice(i, 1);
                        break;
                    }
                return;
            }

            var index = tasks.indexOf(task);
            if (index != -1) {
                tasks[index].timer.stop();
                tasks.splice(index, 1);
            }
        }
    };
})();
