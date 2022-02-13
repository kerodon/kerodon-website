import markdown
import string

from mdx_bleach.extension import BleachExtension
from mdx_bleach.whitelist import ALLOWED_TAGS
from mdx_bleach.whitelist import ALLOWED_ATTRIBUTES
from mdx_math import MathExtension

from gerby.database import *

headings = ["part", "chapter", "section", "subsection", "subsubsection"]

def is_math(tag, name, value):
  return name == "type" and value in ["math/tex", "math/tex; mode=display"]


# Stacks flavored Markdown parser
def sfm(comment):
  attributes = ALLOWED_ATTRIBUTES
  attributes["a"] = ["data-tag", "class", "href"]
  attributes["script"] = is_math

  tags = ALLOWED_TAGS + ["span", "script"]

  bleach = BleachExtension(tags=tags, attributes=attributes)
  math = MathExtension(enable_dollar_delimiter=True)
  md = markdown.Markdown(extensions=[math, bleach])

  # Stacks flavored Markdown: only \ref{tag}, no longer \ref{label}
  references = re.compile(r"\\ref\{([0-9A-Z]{4})\}").findall(comment)
  tags = Tag.select(Tag.tag, Tag.ref).where(Tag.tag << references)
  tags = {tag.tag: tag.ref for tag in tags}

  for reference in references:
    if reference in tags:
      comment = comment.replace("\\ref{" + reference + "}", "<a href=\"/tag/" + reference + "\" data-tag=\"" + reference + "\">" + tags[reference] + "</a>")
    else:
      comment = comment.replace("\\ref{" + reference + "}", "<a href=\"/tag/" + reference + "\" class=\"tag\">" + reference + "</a>")

  comment = md.convert(comment)
  comment = comment.replace("<script>", "<script type=\"text\">")

  return comment


def getBreadcrumb(tag):
  if tag.type == "equation":
    return [tag]
  if tag.type == "item":
    return [tag]

  if tag.type == "eqnarray":
    return [tag]

  if tag.type == "part":
    return [tag]

  # to deal with tags which are immediate descendants of parts
  if tag.type not in headings and len(tag.ref.split(".")) == 2:
    part = Tag.get(Tag.ref == tag.ref.split(".")[0], Tag.type == "part")
    tag.type = tag.type[4:] # remove the prefix part
    return [part, tag]

  pieces = tag.ref.split(".")
  refs = [".".join(pieces[0:i]) for i in range(len(pieces) + 1)]

  tags = Tag.select().where(Tag.ref << refs, ~(Tag.type << ["item", "part", "eqnarray", "equation"]))
  tags = sorted(tags)

  # if there are parts, we look up the corresponding part and add it
  if Tag.select().where(Tag.type == "part").exists():
    chapter = tags[0]
    part = Part.get(Part.chapter == chapter.tag).part
    tags.insert(0, part)

  return tags


def fixDataMarker(html):
  # deal with data-marker="$$"
  symbols = {"$(" + symbol + ")$": "(" + symbol + ")" for symbol in string.ascii_letters + string.digits}
  symbols["$(\\ast )$"] = "(&lowast;)"
  symbols["$(\\ast ')$"] = "(&lowast;')"
  symbols["$(\\ast '')$"] = "(&lowast;'')"
  for symbol in symbols:
    html = html.replace("data-marker=\"" + symbol + "\"", "data-marker=\"" + symbols[symbol] + "\"")

  return html

def fixFutureRef(html):
  # deal with \futureref
  html = html.replace("[?]", '<a style="cursor: pointer;" tabindex="0" role="button" data-trigger="focus" data-placement="bottom" class="" data-toggle="popover" title="Future reference" data-html="true" data-content="This is a reference to something which is not yet available in Kerodon."><img src="/static/images/question.svg"></a>')

  return html
