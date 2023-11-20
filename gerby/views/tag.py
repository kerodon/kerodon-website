import datetime
import string
import random
import itertools

from flask import render_template, request, redirect

from gerby.application import app
from gerby.database import *
from gerby.views.methods import *

import gerby.configuration

import re

headings = ["part", "chapter", "section", "subsection", "subsubsection"]
hideComments = ["part"]
extras = {"slogan": Slogan, "history": History, "reference": Reference}

# Tags pattern as used in the tag_up scripts
TAGS_PATTERN = re.compile("^[0-9a-zA-Z]{4}")

# validate whether something is (potentially) a tag
def isTag(string):
  return TAGS_PATTERN.match(string) is not None and len(string) == 4

# turn a flat list into a tree based on tag.ref length
def combine(tags):
  level = min([len(tag.ref.split(".")) for tag in tags], default=0)

  # split up into tags and parts
  parts = sorted([tag for tag in tags if tag.type == "part"])
  tags = [tag for tag in tags if tag.type != "part"]

  output = []
  children = []
  for tag in tags:
    # if we are at the bottom level (locally) we add it to the output
    if len(tag.ref.split(".")) == level:
      output.append(tag)
    # if we have a 0 at on the position of the current level we also add it to the output
    elif tag.ref.split(".")[level - 1] == "0":
      output.append(tag)
    else:
      children.append(tag)

  # attach children to the correct parent
  for tag in children:
    # construct the reference for the parent
    ref = ".".join([piece for piece in tag.ref.split(".")[0:level]])
    for parent in output:
      if parent.ref == ref:
        # create children if necessary
        if not hasattr(parent, "children"):
          parent.children = []
        parent.children.append(tag)

  # recurse for all elements in output which have children
  for tag in output:
    if hasattr(tag, "children"):
      tag.children = combine(tag.children)

  # if no parts are present we are done
  if len(parts) == 0:
    return output
  # otherwise we recombine parts and other tags
  else:
    # add part information to chapters
    for chapter in output:
      chapter.part = Part.get(Part.chapter == chapter).part

    # combine parts with chapters
    for part in parts:
      part.children = [tag for tag in output if tag.part == part]


    return parts


def getNeighbours(tag):
  # items cannot be dealt with appropriately, so we just don't
  if tag.type == "item":
    return (None, None)

  pieces = tag.ref.split(".")
  try:
    pieces[-1] = int(pieces[-1])
  except ValueError:
    return (None, None) # TODO deal with appendices

  # left
  pieces[-1] = pieces[-1] - 1
  left = ".".join(map(str, pieces))
  try:
    if tag.type in headings:
      left = Tag.get(Tag.ref == left, Tag.type == tag.type) # to deal with parts appropriately we select for part / chapter with the appropriate number
    else:
      left = Tag.get(Tag.ref == left, Tag.type != "item")
  except Tag.DoesNotExist:
    left = None

  # right
  pieces[-1] = pieces[-1] + 2
  right = ".".join(map(str, pieces))
  try:
    if tag.type in headings:
      right = Tag.get(Tag.ref == right, Tag.type == tag.type) # to deal with parts appropriately we select for part / chapter with the appropriate number
    else:
      right = Tag.get(Tag.ref == right, Tag.type != "item")
  except Tag.DoesNotExist:
    right = None

  # deal with thmenv in parts
  if left and left.type.startswith("part"): left.type = left.type[4:]
  if right and right.type.startswith("part"): right.type = right.type[4:]

  # up
  up = ".".join(map(str, pieces[:-1]))
  try:
    if tag.type in headings: # for now we don't deal with this, Kerodon might need this though
      up = None
    else:
      up = Tag.get(Tag.ref == up, Tag.type != "item")
  except Tag.DoesNotExist:
    up = None

  return (left, right, up)


def get_statistics():
  statistics = []

  if BookStatistic.table_exists():
    try:
      statistics.append(str(BookStatistic.get(BookStatistic.statistic == "pages").value) + " pages")
    except BookStatistic.DoesNotExist:
      app.logger.warning("No entry 'pages' in table 'BookStatistics'.")

    try:
      statistics.append(str(BookStatistic.get(BookStatistic.statistic == "lines").value) + " lines of code")
    except BookStatistic.DoesNotExist:
      app.logger.warning("No entry 'lines' in table 'BookStatistics'.")

  tags = Tag.select().where(Tag.active == True).count()
  statistics.append(str(tags) + " tags")
  statistics.append(str(Tag.select().where(Tag.type == "section").count()) + " sections")
  statistics.append(str(Tag.select().where(Tag.type == "chapter").count()) + " chapters")
  statistics.append(str(Slogan.select().count()) + " slogans")

  return statistics



@app.route("/")
def show_index():
  kerodi = ["Kerodon-Climbing.svg"] # for now only the climber, "Kerodon-Guitar.svg", "Kerodon-Reading.svg", "Kerodon-Scientist.svg", "Kerodon-Sports.svg", "Kerodon-Surfing.svg", "Kerodon-VR.svg"]
  number = 1 # change accordingly

  tags = Tag.select().where(Tag.type << ["part", "chapter"]).order_by(Tag.ref.cast("int"))

  # get rid of retired tags on frontpage
  tags = [tag for tag in tags if tag.tag not in ["00FP", "00FN"]]

  tags = combine(tags)

  return render_template(
      "index.html",
      tags=tags,
      kerodi=random.choice(list(itertools.combinations(kerodi, number))),
      statistics=get_statistics(),
      )


@app.route("/tag/<string:tag>")
def show_tag(tag):
  tag = tag.upper()

  if not isTag(tag):
    return render_template("tag.invalid.html", tag=tag)

  try:
    tag = (Tag.select(Tag,
                      Slogan.html.alias("slogan"),
                      History.html.alias("history"),
                      Reference.html.alias("reference"))
                .where(Tag.tag == tag.upper())
                .join(Slogan, JOIN.LEFT_OUTER).switch(Tag)
                .join(History, JOIN.LEFT_OUTER).switch(Tag)
                .join(Reference, JOIN.LEFT_OUTER)).get()
  except Tag.DoesNotExist:
    return render_template("tag.notfound.html", tag=tag)


  html = ""
  breadcrumb = getBreadcrumb(tag)
  neighbours = getNeighbours(tag)


  # if the tag is section-like: decide whether we output a table of contents or generate all output
  # the second case is just like an ordinary tag, but with tags glued together, and is treated as such
  if tag.type in headings:
    html = tag.html

    # if we are below the cutoff: generate all data below it too
    if headings.index(tag.type) >= headings.index(gerby.configuration.UNIT):
      tags = Tag.select().where(Tag.ref.startswith(tag.ref + "."), Tag.type << headings)
      html = html + "".join([item.html for item in sorted(tags)])

      # add badges for extras: look for HTML code that signifies a tag
      pattern = re.compile("id=\"([0-9A-Z]{4})\">")
      identifiers = pattern.findall(html)

      references = Reference.select().where(Reference.tag << identifiers)
      for reference in references:
        html = html.replace("id=\"" + reference.tag.tag + "\">", 'id="' + reference.tag.tag + '"><a tabindex="0" role="button" data-trigger="focus" data-placement="bottom" class="btn badge badge-info" data-toggle="popover" title="Reference" data-html="true" data-content=\'' + reference.html + '\'>reference</a>')
      histories = History.select().where(History.tag << identifiers)
      for history in histories:
        html = html.replace("id=\"" + history.tag.tag + "\">", 'id="' + history.tag.tag + '"><a tabindex="0" role="button" data-trigger="focus" data-placement="bottom" class="btn badge badge-secondary" data-toggle="popover" title="Historical remark" data-html="true" data-content=\'' + history.html + '\'>historical remark</a>')
      slogans = Slogan.select().where(Slogan.tag << identifiers)
      for slogan in slogans:
        html = html.replace("id=\"" + slogan.tag.tag + "\">", 'id="' + slogan.tag.tag + '"><a tabindex="0" role="button" data-trigger="focus" data-placement="bottom" class="btn badge badge-primary" data-toggle="popover" title="Slogan" data-html="true" data-content=\'' + slogan.html + '\'>slogan</a>')


  # it's an item
  elif tag.type == "item":
    html = "<ul>" + tag.html + "</ul>" # <ol start> is incompatible with our current counter setup

  # it's a tag (maybe with proofs)
  else:
    html = tag.html + "".join([proof.html for proof in tag.proofs.order_by(Proof.number)])

  # handle footnotes: relabeling the labels to actual numbers
  pattern = re.compile("class=\"footnotemark\" href=\"#(a[0-9]+)\"")
  labels = pattern.findall(html)
  for number, label in enumerate(labels):
    old = re.search(r"id=\"" + label + "-mark\"><sup>([0-9]+)</sup>", html).group(1)
    html = html.replace(
        "id=\"" + label + "-mark\"><sup>" + old + "</sup>",
        "id=\"" + label + "-mark\"></a><a href=\"#" + label + "\"><sup>" + str(number + 1) + "</sup>")
    # make the HTML pretty (and hide plasTeX id's)
    html = html.replace(label, "footnote-" + str(number + 1))

  # adding offset on the footnote marks in the text
  html = html.replace("class=\"footnotemark\"", "class=\"footnotemark footnote-offset\"")

  footnotes = Footnote.select().where(Footnote.label << labels)

  html = fixDataMarker(html)
  html = fixFutureRef(html)

  # some Gerby bug fixes
  html = html.replace("xymatrix@ 1", "xymatrix@1") # not sure why this is newly introduced on January 21 2021 (maybe it has to do with an upgrade of my Python version?)

  tree = None
  quicknav = None
  # if it's a heading
  if tag.type in headings and headings.index(tag.type) < headings.index(gerby.configuration.UNIT):
    # if the tag is a part, we select all chapters, and then do the startswith for these
    if tag.type == "part":
      chapters = Part.select(Part.chapter).where(Part.part == tag.tag)
      chapters = Tag.select().where(Tag.tag << [chapter.chapter.tag for chapter in chapters])

      tags = [tag for chapter in chapters for tag in Tag.select().where(Tag.ref.startswith(chapter.ref), Tag.type << headings, Tag.type != "part")]
    else:
      tags = Tag.select().where(Tag.ref.startswith(tag.ref + "."), Tag.type << headings)

    tree = combine(sorted(tags))

    if headings.index(tag.type) < headings.index(gerby.configuration.UNIT):
      level = min([len(tag.ref.split(".")) for tag in tags], default=-1)
      quicknav = sorted([tag for tag in tags if len(tag.ref.split(".")) == level])

  # dealing with comments
  commentsEnabled = tag.type not in hideComments and Comment.table_exists()
  comments = []
  parentComments = []
  if commentsEnabled:
    comments = Comment.select().where(Comment.tag == tag.tag, Comment.active)
    for comment in comments:
      comment.comment = sfm(comment.comment)

    # looking for comments higher up in the breadcrumb
    parentComments = []
    for parent in breadcrumb:
      if parent.tag == tag.tag:
        continue
      count = Comment.select().where(Comment.tag == parent.tag, Comment.active).count() # this could be done in a single JOIN
      if count > 0:
        parentComments.append([parent, count])

  # Kerodon: we are not using separate files for the pdf's
  filename = "kerodon.pdf"

  return render_template("tag.show.html",
                         tag=tag,
                         breadcrumb=breadcrumb,
                         neighbours=neighbours,
                         html=html,
                         footnotes=footnotes,
                         dependencies=tag.incoming,
                         tree=tree,
                         quicknav=quicknav,
                         commentsEnabled=commentsEnabled,
                         comments=comments,
                         filename=filename,
                         parentComments=parentComments,
                         depth=gerby.configuration.DEPTH)

@app.route("/tag/<string:tag>/comments")
def show_comments(tag):
  if not isTag(tag):
    return render_template("tag.invalid.html", tag=tag)

  try:
    tag = Tag.get(Tag.tag == tag.upper())
  except Tag.DoesNotExist:
    return render_template("tag.notfound.html", tag=tag), 404

  breadcrumb = getBreadcrumb(tag)

  commentsEnabled = tag.type not in hideComments and Comment.table_exists()
  comments = []
  parentComments = []

  if not commentsEnabled:
    return render_template("tag.nocomments.html", tag=tag)

  comments = Comment.select().where(Comment.tag == tag.tag, Comment.active)
  for comment in comments:
    comment.comment = sfm(comment.comment)

  # looking for comments higher up in the breadcrumb
  parentComments = []
  for parent in breadcrumb:
    if parent.tag == tag.tag:
      continue
    count = Comment.select().where(Comment.tag == parent.tag, Comment.active).count() # this could be done in a single JOIN
    if count > 0:
      parentComments.append([parent, count])

  return render_template("tag.comments.html",
                         tag=tag,
                         breadcrumb=breadcrumb,
                         neighbours=getNeighbours(tag),
                         commentsEnabled=commentsEnabled,
                         comments=comments,
                         parentComments=parentComments)

@app.route("/tag/<string:tag>/cite")
def show_citation(tag):
  if not isTag(tag):
    return render_template("tag.invalid.html", tag=tag)

  try:
    tag = Tag.get(Tag.tag == tag.upper())
  except Tag.DoesNotExist:
    return render_template("tag.notfound.html", tag=tag), 404

  breadcrumb = getBreadcrumb(tag)
  neighbours = getNeighbours(tag)

  return render_template("tag.citation.html",
                         tag=tag,
                         breadcrumb=breadcrumb,
                         neighbours=neighbours,
                         time=datetime.datetime.utcnow())

@app.route("/tag/<string:tag>/statistics")
def show_tag_statistics(tag):
  if not isTag(tag):
    return render_template("tag.invalid.html", tag=tag)

  try:
    tag = Tag.get(Tag.tag == tag.upper())
  except Tag.DoesNotExist:
    return render_template("tag.notfound.html", tag=tag), 404

  breadcrumb = getBreadcrumb(tag)
  neighbours = getNeighbours(tag)

  # dealing with the creation and update date
  creation = None
  update = None
  try:
    creation = tag.changes.where(Change.action == "creation").get()
    creation = datetime.datetime.strptime(creation.commit.time.decode(), "%Y-%m-%d %H:%M:%S %z")

    update = Commit.select().where(Commit.hash << [change.commit.hash for change in tag.changes]).order_by(Commit.time.desc()).get()
    update = datetime.datetime.strptime(update.time.decode(), "%Y-%m-%d %H:%M:%S %z")
  except (Change.DoesNotExist, Commit.DoesNotExist):
    pass

  # dealing with the tags using this results
  tag.incoming = sorted(tag.incoming)

  # making sure we can give section numbers here
  sections = []
  for dependency in tag.incoming:
    sections.append(".".join(dependency.tag.ref.split(".")[0:-1]))

  sections = Tag.select().where(Tag.ref << sections, ~(Tag.type << ["item"]))
  sections = {section.ref: section for section in sections}

  for dependency in tag.incoming:
    ref = ".".join(dependency.tag.ref.split(".")[0:-1])
    dependency.parent = sections[ref]

  # dealing with statistics
  statistics = dict()
  statistics["proof"] = tag.outgoing.count()

  if TagStatistic.table_exists():
    for statistic in ["preliminaries", "chapters", "sections", "consequences"]:
      try:
        statistics[statistic] = tag.statistics.filter(TagStatistic.statistic == statistic).get().value
      except TagStatistic.DoesNotExist:
        log.warning("Unable to get statistic '{0}' for tag '{1}'.".format(statistic, tag))
        statistics[statistic] = -1

  return render_template("tag.statistics.html",
                         tag=tag,
                         breadcrumb=breadcrumb,
                         neighbours=neighbours,
                         creation=creation,
                         update=update,
                         statistics=statistics,
                         filename=tag.label.split("-" + tag.type)[0],
                         dependencies=tag.incoming)
