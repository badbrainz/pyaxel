var ConnectionFactory = {}

ConnectionFactory.timeout = 5;
ConnectionFactory.max_retries = 3;
//ConnectionFactory.Adapters = {}

ConnectionFactory.createConnection = function(address) {
    return new Connection(address, ConnectionFactory.max_retries, ConnectionFactory.timeout);
}
