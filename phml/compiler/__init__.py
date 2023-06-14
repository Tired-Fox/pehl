from collections.abc import Callable
from copy import deepcopy
from typing import Any
from typing import Literal as Lit
from typing import NoReturn, overload

from phml.components import ComponentManager
from phml.embedded import Embedded
from phml.helpers import normalize_indent
from phml.nodes import AST, Element, Literal, LiteralType, Parent

from .steps import *
from .steps.base import post_step, scoped_step, setup_step

__all__ = [
    "HypertextMarkupCompiler",
    "setup_step",
    "scoped_step",
    "post_step",
]

PRE_LIKE = ["script", "style", "python", "code"]

__SETUP__: list[Callable] = []

__STEPS__: list[Callable] = [
    step_replace_phml_wrapper,
    step_expand_loop_tags,
    step_execute_conditions,
    step_compile_markdown,
    step_execute_embedded_python,
    step_substitute_components,
]

__POST__: list[Callable] = [
    step_add_cached_component_elements,
]

StepStage = Lit["setup", "scoped", "post"]

self_closing = [
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
    "command",
    "keygen",
    "menuitem",
    "Slot",
    "Markdown",
]


class HypertextMarkupCompiler:
    def __init__(self) -> None:
        self.pre = list(__SETUP__)
        self.scoped = list(__STEPS__)
        self.post = list(__POST__)
        self.results: dict[str, Any] = {}


    @overload
    def add_step(
        self,
        step: Callable[[AST, ComponentManager, dict[str, Any], dict[str, Any]], None],
        stage: Lit["setup", "post"],
    ) -> NoReturn:
        ...
    
    
    @overload
    def add_step(
        self,
        step: Callable[[Parent, ComponentManager, dict[str, Any], dict[str, Any]], None],
        stage: Lit["scoped"],
    ) -> NoReturn:
        ...


    def add_step(
        self,
        step: Callable[[Parent, ComponentManager, dict[str, Any], dict[str, Any]], None]
        | Callable[[AST, ComponentManager, dict[str, Any], dict[str, Any]], None],
        stage: StepStage,
    ):
        if stage == "setup" and stage not in self.pre:
            self.pre.append(step)
        elif stage == "scoped" and stage not in self.scoped:
            self.scoped.append(step)
        elif stage == "post" and stage not in self.post:
            self.post.append(step)


    @overload
    def remove_step(
        self,
        step: Callable[[AST, ComponentManager, dict[str, Any], dict[str, Any]], None],
        stage: Lit["setup", "post"],
    ) -> NoReturn:
        ...


    @overload
    def remove_step(
        self,
        step: Callable[[Parent, ComponentManager, dict[str, Any], dict[str, Any]], None],
        stage: Lit["scoped"],
    ) -> NoReturn:
        ...


    def remove_step(
        self,
        step: Callable[[Parent, ComponentManager, dict[str, Any], dict[str, Any]], None]
        | Callable[[AST, ComponentManager, dict[str, Any], dict[str, Any]], None],
        stage: StepStage,
    ):
        if stage == "setup":
            self.pre.remove(step)
        elif stage == "scoped":
            self.scoped.remove(step)
        elif stage == "post":
            self.post.remove(step)

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
        for _step in self.scoped:
            _step(node, components, context, self.results)

        # Recurse steps for each scope
        for child in node:
            if isinstance(child, Element):
                self._process_scope_(child, components, context)

    @overload
    def compile(self, node: AST, _components: ComponentManager, **context: Any) -> AST:
        ...

    @overload
    def compile(
        self, node: Parent, _components: ComponentManager, **context: Any
    ) -> Parent:
        ...

    def compile(
        self, node: Parent, _components: ComponentManager, **context: Any
    ) -> Parent:
        self.results = {}

        # get all python elements and process them
        node = deepcopy(node)
        p_elems = self._get_python_elements(node)
        embedded = Embedded("")
        for p_elem in p_elems:
            embedded += Embedded(p_elem)

        # Setup steps to collect data before comiling at different scopes
        for step in self.pre:
            step(node, _components, context, self.results)

        # Recursively process scopes
        context.update(embedded.context)
        self._process_scope_(node, _components, context)

        # Post compiling steps to finalize the ast
        for step in self.post:
            step(node, _components, context, self.results)

        return node

    def _render_attribute(self, key: str, value: str | bool) -> str:
        if isinstance(value, str):
            return f'{key}="{value}"'
        else:
            return str(key) if value else f'{key}="false"'

    def _render_element(
        self,
        element: Element,
        indent: int = 0,
        compress: str = "\n",
    ) -> str:
        attr_idt = 2
        attrs = ""
        lead_space = " " if len(element.attributes) > 0 else ""
        if element.in_pre:
            attrs = lead_space + " ".join(
                self._render_attribute(key, value)
                for key, value in element.attributes.items()
            )
        elif len(element.attributes) > 1:
            idt = indent + attr_idt if compress == "\n" else 1
            attrs = (
                f"{compress}"
                + " " * (idt)
                + f'{compress}{" "*(idt)}'.join(
                    self._render_attribute(key, value)
                    for key, value in element.attributes.items()
                )
                + f"{compress}{' '*(indent)}"
            )
        elif len(element.attributes) == 1:
            key, value = list(element.attributes.items())[0]
            attrs = lead_space + self._render_attribute(key, value)

        closing = "/"
        if element.children is not None or element.decl or element.tag in self_closing:
            closing = ""

        result = (
            f"{' '*indent if not element.in_pre else ''}"
            f"<{'!' if element.decl else ''}{element.tag}" + f"{attrs}{closing}>"
        )

        if element.children is None:
            return result

        if (
            compress != "\n"
            or element.in_pre
            or (
                element.tag not in PRE_LIKE
                and len(element) == 1
                and Literal.is_text(element[0])
                and "\n" not in element[0].content
                and "\n" not in result
            )
        ):
            children = self._render_tree_(element, _compress="")
            result += children + f"</{element.tag}>"
        else:
            children = self._render_tree_(element, indent + 2, _compress=compress)
            if len(children) > 0:
                result += compress + children
                result += f"{compress}{' '*indent}</{element.tag}>"
            else:
                result += children
                result += f"</{element.tag}>"

        return result

    def _render_literal(
        self,
        literal: Literal,
        indent: int = 0,
        compress: str = "\n",
    ) -> str:
        offset = " " * indent
        if literal.in_pre:
            offset = ""
            compress = ""
            content = literal.content
        else:
            content = literal.content
            # if compress == "\n":
            #     content = normalize_indent(literal.content, indent)
            #     content = content.strip()
            if not isinstance(literal.parent, AST) and literal.parent.tag in PRE_LIKE:
                content = normalize_indent(literal.content, indent)
                content = content.strip()
            else:
                if indent != -1:
                    lines = content.strip().split("\n")
                else:
                    lines = content.split("\n")
                content = f"{compress}{offset}".join(lines)

        if literal.name == LiteralType.Text:
            return offset + content

        if literal.name == LiteralType.Comment:
            return f"{offset}<!--" + content + "-->"
        return ""  # pragma: no cover

    def _render_tree_(
        self,
        node: Parent,
        indent: int = 0,
        _compress: str = "\n",
    ):
        result = []
        for i, child in enumerate(node):
            if isinstance(child, Element):
                result.append(
                    f"{_compress}{self._render_element(child, indent, _compress)}"
                )
            elif isinstance(child, Literal):
                result.append(
                    self._render_literal(child, indent if i == 0 else -1, _compress)
                )
            else:
                raise TypeError(f"Unknown renderable node type {type(child)}")

        return "".join(result).lstrip("\n")

    def render(
        self,
        node: Parent,
        _compress: bool = False,
        indent: int = 0,
    ) -> str:
        return self._render_tree_(node, indent, "" if _compress else "\n")
