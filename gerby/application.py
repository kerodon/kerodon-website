import os
import os.path
import time
import urllib.request
import itertools
import socket
import re
from flask import Flask, render_template, request, send_from_directory, send_file
#import flask_profiler
import flask_scss

from peewee import *
from playhouse.sqlite_ext import *

from gerby.configuration import *
from gerby.database import *

db.init(DATABASE)

# Flask setup code
app = Flask(__name__)
app.config.from_object(__name__)

flask_scss.Scss(app, static_dir="gerby/static/css", asset_dir="gerby/assets")

#app.config["flask_profiler"] = {
#    "enabled": "true",
#    "storage": {
#        "engine": "sqlite"
#    },
#    "basicAuth": {
#        "enabled": False,
#    },
#    "ignore": ["^/static/.*"]
#}


@app.route("/kerodon.pdf")
def download_file():
  return send_file("kerodon.pdf")


@app.route("/about")
def show_about():
  return render_template("kerodon/about.html")


@app.route("/tags")
def show_tags():
  return render_template("kerodon/tags.html")


@app.route("/markdown")
def show_markdown():
  return render_template("kerodon/markdown.html")


@app.route("/statistics")
def show_statistics():
  total = Tag.select().count()

  counts = dict()
  for count in Tag.select(Tag.type, fn.COUNT(Tag.tag).alias("count")).group_by(Tag.type):
    counts[count.type] = count.count

  extras = dict()
  for (name, extra) in {"slogans": Slogan, "references": Reference, "historical remarks": History}.items():
    extras[name] = extra.select().count()

  records = dict()
  records["complex"] = TagStatistic.select(TagStatistic.tag, fn.MAX(TagStatistic.value).alias("value")).where(TagStatistic.statistic == "preliminaries").execute()[0]
  records["used"] = TagStatistic.select(TagStatistic.tag, fn.MAX(TagStatistic.value).alias("value")).where(TagStatistic.statistic == "consequences").execute()[0]
  records["referenced"] = Dependency.select(Dependency.to, fn.COUNT(Dependency.to).alias("value")).group_by(Dependency.to).order_by(fn.COUNT(Dependency.to).desc())[0]
  records["proof"] = Proof.select(Proof.tag, fn.length(Proof.html).alias("value")).order_by(fn.length(Proof.html).desc())[0]

  return render_template("kerodon/statistics.html", total=total, counts=counts, extras=extras, records=records)


@app.route("/robots.txt")
def show_robots():
  return send_from_directory(app.static_folder, request.path[1:])


app.jinja_env.add_extension('jinja2.ext.do')

import gerby.views.bibliography
import gerby.views.comments
import gerby.views.search
import gerby.views.tag


#flask_profiler.init_app(app)

# Kerodon specific pages
import gerby.views.kerodon
