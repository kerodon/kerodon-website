from flask import render_template, send_from_directory, redirect
import dateutil.parser

from gerby.application import app
from gerby.database import *
from gerby.views.methods import *


@app.route("/changes")
def show_recent_changes():
  changes = dict()

  with app.open_resource("changes.md", mode="r") as f:
    date = None

    for line in f:
      # new item starts with date
      if line.startswith("#"):
        date = dateutil.parser.parse(line[2:].strip())
        changes[date] = ""
      elif date != None:
        changes[date] = changes[date] + line

  # turn Markdown into HTML
  changes.update({date: sfm(change) for date, change in changes.items()})

  years = list(set([date.year for date in changes]))
  changes = {year : [(date, changes[date]) for date in changes if date.year == year] for year in years}

  return render_template("kerodon/changes.html", changes=changes)
