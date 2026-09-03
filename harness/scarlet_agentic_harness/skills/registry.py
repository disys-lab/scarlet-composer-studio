"""
Skill discovery.

This is the actual generalization mechanism: adding a new skill means adding
a new module under scarlet_agentic_harness/skills/ that defines a Skill
subclass - discover_skills() finds it automatically. head.py/worker.py never
import a specific skill by name.
"""
import importlib
import inspect
import pkgutil

from scarlet_agentic_harness.skills.base import Skill


def discover_skills() -> dict[str, Skill]:
    """
    Find and instantiate every `Skill` subclass under `scarlet_agentic_harness.skills`.

    Adding a new skill means adding a new module here defining a `Skill`
    subclass - this finds it automatically, so `head`/`worker` never
    import a specific skill by name.

    Returns
    -------
    dict of str to Skill
        Skill instances keyed by `Skill.name`.

    Raises
    ------
    ValueError
        If a discovered `Skill` subclass has no `name` set, or two
        subclasses declare the same `name`.
    """
    import scarlet_agentic_harness.skills as skills_pkg

    found: dict[str, Skill] = {}
    for _, module_name, _ in pkgutil.iter_modules(skills_pkg.__path__):
        if module_name in ("base", "registry"):
            continue
        module = importlib.import_module(f"{skills_pkg.__name__}.{module_name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Skill)
                and obj is not Skill
                and obj.__module__ == module.__name__
            ):
                instance = obj()
                if not instance.name:
                    raise ValueError(f"{obj.__name__} in {module_name} did not set a `name`")
                if instance.name in found:
                    raise ValueError(f"duplicate skill name {instance.name!r}")
                found[instance.name] = instance
    return found
