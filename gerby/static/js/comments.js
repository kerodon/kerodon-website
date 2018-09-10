$(document).ready(function() {
  // read author information from local storage
  $("input#name").val(localStorage.getItem("name"));
  $("input#mail").val(localStorage.getItem("mail"));
  $("input#site").val(localStorage.getItem("site"));
});

