var Months = [
    "Jan","Feb","Mar","Apr","May","Jun",
    "Jul","Aug","Sep","Oct","Nov","Dec"
];

Date.prototype.today = function(format) {
    return Months[this.getMonth()] + " " + this.getDate() + ", " + this.getFullYear();
}
