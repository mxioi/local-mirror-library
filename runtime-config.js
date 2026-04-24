(function () {
  if (window.ARCHIVE_API_BASE) return;
  var host = (window.location && window.location.hostname) || "127.0.0.1";
  var proto = window.location && window.location.protocol === "https:" ? "https:" : "http:";
  window.ARCHIVE_API_BASE = proto + "//" + host + ":8010/api/v1";
})();
