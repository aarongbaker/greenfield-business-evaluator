"""Static shell completion scripts generated from the `greenfield` parser tree (Python 3.11+)."""
from __future__ import annotations
import argparse


def _subcommands(parser):
    """Visible subcommand names and parsers (hidden ones were added without help)."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            visible = {a.dest for a in action._choices_actions}
            return [(n, p) for n, p in action.choices.items() if n in visible]
    return []


def _options(parser):
    return [s for a in parser._actions for s in a.option_strings if s.startswith("--")]


def table(parser):
    """{"": top-level words, "cmd": its words, "cmd sub": its words}."""
    out = {"": [n for n, _ in _subcommands(parser)] + _options(parser)}
    for name, p in _subcommands(parser):
        subs = _subcommands(p)
        out[name] = [n for n, _ in subs] or _options(p)
        for sub, sp in subs:
            out[f"{name} {sub}"] = _options(sp)
    return out


def script(parser, shell):
    words = table(parser)
    if shell == "fish":
        lines = ["complete -c greenfield -f -n __fish_use_subcommand -a " + repr(" ".join(words[""]))]
        for key, w in words.items():
            if key:
                cond = "; and ".join(f"__fish_seen_subcommand_from {k}" for k in key.split())
                lines.append(f"complete -c greenfield -f -n '{cond}' -a " + repr(" ".join(w)))
        return "\n".join(lines) + "\n"
    pairs = "".join(f'    "{k}") w="{" ".join(v)}";;\n' for k, v in words.items() if " " in k)
    singles = "".join(f'    {k}) w="{" ".join(v)}";;\n' for k, v in words.items() if k and " " not in k)
    body = ("_greenfield() {\n"
            '  local cur="${COMP_WORDS[COMP_CWORD]}" w=""\n'
            '  if [ "$COMP_CWORD" -gt 2 ]; then case "${COMP_WORDS[1]} ${COMP_WORDS[2]}" in\n' + pairs + "  esac; fi\n"
            '  if [ -z "$w" ] && [ "$COMP_CWORD" -gt 1 ]; then case "${COMP_WORDS[1]}" in\n' + singles + "  esac; fi\n"
            f'  [ -n "$w" ] || w="{" ".join(words[""])}"\n'
            '  COMPREPLY=($(compgen -W "$w" -- "$cur"))\n'
            "}\ncomplete -F _greenfield greenfield\n")
    return ("(( $+functions[compdef] )) || { autoload -U +X compinit && compinit; }\nautoload -U +X bashcompinit && bashcompinit\n" if shell == "zsh" else "") + body
