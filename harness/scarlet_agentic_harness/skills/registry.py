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

from scarlet_agentic_harness.skills.base import CompoundSkill, Skill


def discover_skills() -> dict[str, Skill]:
    """
    Find and instantiate every `Skill` subclass under `scarlet_agentic_harness.skills`.

    Adding a new skill means adding a new module here defining a `Skill`
    subclass - this finds it automatically, so `dispatch`/`worker` never
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
    # walk_packages, not iter_modules: skills live in core/ and compound/
    # subpackages now, and iter_modules lists only a package's immediate
    # modules. With iter_modules this returns an empty dict - every worker
    # then boots advertising no capabilities and every dispatch fails with
    # "no online worker currently reports the X capability", which reads as
    # a fleet problem rather than a packaging one.
    for _, module_name, ispkg in pkgutil.walk_packages(
            skills_pkg.__path__, prefix=f"{skills_pkg.__name__}."):
        if ispkg:
            continue
        # module_name is fully qualified now, so match on the last segment.
        if module_name.rsplit(".", 1)[-1] in (
                "base", "skill", "step", "compound_skill",
                "registry", "safe_eval", "local_data", "predicate",
                "staggered_deadline", "distributions"):
            continue
        module = importlib.import_module(module_name)
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Skill)
                and obj is not Skill
                # CompoundSkill is a base class too - instantiating it as a
                # skill would register a nameless entry and raise.
                and obj is not CompoundSkill
                and obj.__module__ == module.__name__
            ):
                instance = obj()
                if not instance.name:
                    raise ValueError(f"{obj.__name__} in {module_name} did not set a `name`")
                if instance.name in found:
                    raise ValueError(f"duplicate skill name {instance.name!r}")
                found[instance.name] = instance
    return found
