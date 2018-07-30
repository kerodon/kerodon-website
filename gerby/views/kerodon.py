from flask import render_template, send_from_directory, redirect
from datetime import datetime

from gerby.application import app
from gerby.database import *
from gerby.views.methods import *


@app.route("/recent-changes")
def show_recent_changes():
  return render_template("kerodon/changes.html")
