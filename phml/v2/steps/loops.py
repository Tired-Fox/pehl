
# TODO: For each scope apply list of steps
# - Each step takes; node, context, component manager
# - Each step mutates the current scope
from copy import deepcopy
import re
from typing import Any

from ..nodes import Parent, Element
from ..embedded import exec_embedded
from .base import comp_step


def _update_fallbacks(node: Element, exc: Exception):
    fallbacks = _get_fallbacks(node)
    for fallback in fallbacks:
        fallback.context["_loop_fail_"] = exc

def _remove_fallbacks(node: Element):
    fallbacks = _get_fallbacks(node)
    for fallback in fallbacks:
        if fallback.parent is not None:
            fallback.parent.remove(fallback)

def _get_fallbacks(node: Element) -> list[Element]:
    fallbacks = []
    if node.parent is not None:
        idx = node.parent.children.index(node)
        for i in range(idx+1, len(node.parent)):
            if isinstance(node.parent[i], Element):
                if "@elif" in node.parent[i]:
                    fallbacks.append(node.parent[i])
                    continue
                elif "@else" in node.parent[i]:
                    fallbacks.append(node.parent[i])
            break
    return fallbacks

def replace_default(node: Element, exc: Exception, sub: Element = Element("", {"@if": "False"})):
    if node.parent is not None and node.parent.children is not None:
        node.attributes.pop("@elif", None)
        node.attributes.pop("@else", None)
        node.attributes["@if"] = "False"

        _update_fallbacks(node, exc)


@comp_step
def step_expand_loop_tags(
    *,
    node: Parent,
    context: dict[str, Any]
):
    if node.children is None:
        return

    for_loops = [
        child for child in node
        if isinstance(child, Element)
        and child.tag == "For"
        and node.children is not None
    ]

    def gen_new_children(node: Parent, context: dict[str, Any]) -> list:
        new_children = deepcopy(node.children or [])
        for child in new_children:
            if isinstance(child, Element):
                child.context.update(context)
            child.parent = None
            child._position = None
        return new_children


    for loop in for_loops:
        parsed_loop = re.match(
                r"(?:for\s*)?(?P<captures>.+) in (?P<source>.+):?",
                loop.get(":each", loop.get("each", ""))
        )

        if parsed_loop is None:
            raise ValueError(
                "Expected expression in 'each' attribute for <For/> to be a valid list comprehension."
            )

        parsed_loop = parsed_loop.groupdict()

        captures = re.findall(r"([^\s,]+)", parsed_loop["captures"])
        source = parsed_loop["source"].strip()

        dict_key = lambda a: f"'{a}':{a}"
        process = f"""\
__children__ = []
iterations = 0
for {loop.get(":each", loop.get("each"))}:
    __children__.extend(
        __gen_new_children__(
            __node__,
            {{{','.join(dict_key(key) for key in captures)}}}
        )
    )
    iterations += 1
(iterations, __children__)
"""

        if ":each" in loop:
            _each = f':each="{loop[":each"]}"'
        elif "each" in loop:
            _each = f':each="{loop[":each"]}"'
        else:
            _each = ""

        try:
            iterations, new_nodes = exec_embedded(
                process,
                f"<For {_each}>",
                **context,
                __gen_new_children__=gen_new_children,
                __node__=loop,
            )

            if iterations == 0:
                replace_default(loop, Exception("No iterations occured. Expected non empty iterator."))
            elif loop.parent is not None:
                _remove_fallbacks(loop)

                idx = loop.parent.children.index(loop)
                loop.parent.remove(loop)
                loop.parent.insert(idx, new_nodes)
        except Exception as exec:
            replace_default(loop, exec)

