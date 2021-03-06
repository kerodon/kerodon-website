// check whether we should execute the onChange for the checkbox
var execute = false;

$(document).ready(function() {
  // we do this in JS as it only makes sense to have these when JS is enabled
  var html = '<input class="toggle" name="toggle" type="checkbox" checked data-toggle="toggle" data-on="numbers" data-off="tags" data-size="small" data-width="130" data-height="40" data-onstyle="default">';

  $("span#sidebar-toggle").replaceWith(html);
  $("span#hamburger-toggle").replaceWith(html);

  // turn the checkbox into a toggle button
  $("input.toggle").bootstrapToggle();

  $("input.toggle").change(function(e) {
    // change the state which decides whether we execute the event
    execute = !execute;
    // check whether we should execute the event or not: synchronise fires a second event
    if (!execute) return;

    // the actual toggling code
    $("*[data-tag]").each(function(index, reference) {
      $(reference).toggleClass("tag");

      var value = $(reference).attr("data-tag");
      $(reference).attr("data-tag", $(reference).text())
      $(reference).text(value);
    });

    // synchronise the other checkbox
    $("input.toggle").not($(this)).bootstrapToggle("toggle");

    // and save preference: use presence of tag class
    if ($("*[data-tag]").hasClass("tag"))
      localStorage.setItem("toggle", "tag");
    else
      localStorage.setItem("toggle", "numbers");

    // hide hamburger when clicking toggle
    if ($(e.currentTarget.parentElement.parentElement).is("#burger-content"))
      $("input#burger-checkbox").click();
  });

  // toggle if localStorage says so
  if (localStorage.getItem("toggle") == "tag") {
    $("section#sidebar input.toggle").bootstrapToggle("toggle");
  }
});
