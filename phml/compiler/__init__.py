from collections.abc import Callable
from typing import Any

from phml.embedded import Embedded
from phml.helpers import normalize_indent
from phml.nodes import (
    LiteralType,
    Literal,
    Element,
    Parent,
    inspect
)
from phml.components import ComponentManager

from .steps import *

__all__ = [
    "SETUP",
    "STEPS",
    "POST",
    "HypertextMarkupCompiler",
]

SETUP: list[Callable] = []

STEPS: list[Callable] = [
    step_expand_loop_tags,
    step_execute_conditions,
    step_execute_embedded_python,
    step_substitute_components,
    step_compile_markdown,
]

POST: list[Callable] = [
    step_add_cached_component_elements,
]

class HypertextMarkupCompiler:
    def _get_python_elements(self, node: Parent) -> list[Element]:
        result = []
        for child in node:
            if isinstance(child, Element):
                if child.tag == "python":
                    result.append(child)
                    idx = node.index(child)
                    del node[idx]
                else:
                    result.extend(self._get_python_elements(child))

        return result

    def _process_scope_(
        self,
        node: Parent,
        components: ComponentManager,
        context: dict,
    ):
        """Process steps for a given scope/parent node."""
        
        # Core compile steps
        for _step in STEPS:
            _step(node, components, context)
        
        # Recurse steps for each scope
        for child in node:
            if isinstance(child, Element):
                self._process_scope_(child, components, context)

    def compile(self, node: Parent, _components: ComponentManager, **context: Any) -> Parent:
        # get all python elements and process them
        p_elems = self._get_python_elements(node)
        embedded = Embedded("")
        for p_elem in p_elems:
            embedded += Embedded(p_elem)

        # Setup steps to collect data before comiling at different scopes
        for step in SETUP:
            step(node, _components, context)

        # Recursively process scopes
        context.update(embedded.context)
        self._process_scope_(node, _components, context)

        # Post compiling steps to finalize the ast
        for step in POST:
            step(node, _components, context)

        return node

    def _render_attribute(self, key: str, value: str | bool) -> str:
        if isinstance(value, str):
            return f'{key}="{value}"'
        else:
            return str(key) if value else ""

    def _render_element(
        self, element: Element, components: ComponentManager, indent: int = 0, compress: str = "\n"
    ) -> str:
        attr_idt = 2
        attrs = ""
        if element.in_pre:
            attrs = " " + " ".join(
                self._render_attribute(key, value)
                for key, value in element.attributes.items()
                if value != False
            )
        elif len(element.attributes) > 1:
            idt = indent + attr_idt if compress == "\n" else 1
            attrs = (
                f"{compress}"
                + " " * (idt)
                + f'{compress}{" "*(idt)}'.join(
                    self._render_attribute(key, value)
                    for key, value in element.attributes.items()
                    if value != False
                )
                + f"{compress}{' '*(indent)}"
            )
        elif len(element.attributes) == 1:
            key, value = list(element.attributes.items())[0]
            attrs = " " + self._render_attribute(key, value)

        result = f"{' '*indent if not element.in_pre else ''}<{element.tag}{attrs}{'' if len(element) > 0 else '/'}>"
        if len(element) == 0:
            return result

        if (
            compress != "\n"
            or element.in_pre
            or (
                element.tag not in ["script", "style", "python"]
                and len(element) == 1
                and Literal.is_text(element[0])
                and "\n" not in element[0].content
                and "\n" not in result
            )
        ):
            children = self._render_tree_(element, components, _compress=compress)
            result += children + f"</{element.tag}>"
        else:
            children = self._render_tree_(element, components, indent + 2, _compress=compress)
            result += compress + children
            result += f"{compress}{' '*indent}</{element.tag}>"

        return result

    def _render_literal(
        self, literal: Literal, indent: int = 0, compress: str = "\n"
    ) -> str:
        offset = " " * indent
        if literal.in_pre:
            offset = ""
            compress = ""
            content = literal.content
        else:
            content = literal.content.strip()
            if compress == "\n":
                content = normalize_indent(literal.content, indent)
                content = content.strip()
            elif literal.parent.tag in ["python", "script", "style"]:
                content = normalize_indent(literal.content)
                content = content.strip()
                offset = ""
            else:
                lines = content.split("\n")
                content = f"{compress}{offset}".join(lines)

        if literal.name == LiteralType.Text:
            return offset + content

        if literal.name == LiteralType.Comment:
            return f"{offset}<!--" + content + "-->"
        return ""

    def _render_tree_(
        self,
        node: Parent,
        _components: ComponentManager,
        indent: int = 0,
        _compress: str = "\n",
    ):
        result = []
        for child in node:
            if isinstance(child, Element):
                if child.tag == "doctype":
                    result.append(f"<!DOCTYPE html>")
                else:
                    result.append(self._render_element(child, _components, indent, _compress))
            elif isinstance(child, Literal):
                result.append(self._render_literal(child, indent, _compress))
            else:
                raise TypeError(f"Unknown renderable node type {type(child)}")

        return _compress.join(result)


    def render(
        self,
        node: Parent,
        _components: ComponentManager,
        indent: int = 0,
        _compress: str = "\n",
        **context: Any
    ) -> str:
        return self._render_tree_(node, _components, indent, _compress)
