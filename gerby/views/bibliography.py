from flask import render_template

from gerby.gerby import app
from gerby.database import *

def decorateEntries(entries):
  for entry in entries:
    fields = BibliographyField.select().where(BibliographyField.key == entry.key)
    # make the fields accessible in Jinja
    for field in fields:
      setattr(entry, field.field, field.value)

  return entries



@app.route("/bibliography")
def show_bibliography():
  entries = BibliographyEntry.select()
  entries = decorateEntries(entries)
  entries = sorted(entries)

  return render_template("bibliography.overview.html", entries=entries)

@app.route("/bibliography/<string:key>")
def show_entry(key):
  entry = BibliographyEntry.get(BibliographyEntry.key == key)

  fields = BibliographyField.select().where(BibliographyField.key == entry.key)
  entry.fields = dict()
  for field in fields:
    entry.fields[field.field] = field.value

  # it's too unpleasant to sort in SQL so we do it here, but the result might be a bit slow
  entries = BibliographyEntry.select()
  entries = decorateEntries(entries) # we need the author field to be present for sorting to work...
  entries = sorted(entries)

  index = -1
  for i in range(len(entries)):
    if entries[i].key == entry.key:
      index = i

  neighbours = [None, None]
  if index > 0:
    neighbours[0] = entries[index-1]
  if index < len(entries) - 1:
    neighbours[1] = entries[index+1]

  citations = Tag.select().join(Citation).where(Citation.key == entry.key).order_by()
  citations = sorted(citations)

  return render_template("bibliography.entry.html",
                         entry=entry,
                         neighbours=neighbours,
                         citations=citations)
