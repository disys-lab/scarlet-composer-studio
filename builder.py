import shutil
import sys
import os
import subprocess
from pathlib import Path

"""
Build one wheel and (optionally) push it to Gemfury.

    python builder.py <setup_file> [gemfury_token]

Adapted from disys-lab/gustavo's builder.py, used the same way from
.github/workflows/multi-build.yml (agent-*build / composer-*build jobs -
composer needs both setup.py's scarlets wheel and setup_composer.py's
scarletcomposer wheel, so this is called once per setup file). Two
deliberate simplifications versus gustavo's version: its first positional
argument was a git repo URL whose *value* was never actually used beyond
a truthy prod-vs-dev gate (`if gitRepo:`) - dropped here in favor of just
branching on whether a Gemfury token was actually supplied - and its
second Gemfury token/push target was confirmed to be an unused relic, so
this only ever pushes to one Gemfury target.

With no token arg (dev mode), builds the wheel into dist/ and stops -
doesn't push anywhere. With a token arg (prod mode, what CI uses), also
pushes to Gemfury.
"""

setup_file = sys.argv[1]
if len(sys.argv) > 2:
    mode = "prod"
    GEMFURY_TOKEN = sys.argv[2]
else:
    mode = "dev"
    GEMFURY_TOKEN = ""

subprocess.run(["git", "remote", "update"])
describe = subprocess.run(
    ["git", "describe", "--tags"], capture_output=True, text=True,
)
version_info = describe.stdout.strip() or "(no tags yet - setuptools-scm's fallback_version will apply)"

print(
    "\033[1m"
    + "\n\n\n\t\t\t__________________Creating Output directory __________________\n"
    + "\033[0m"
)
print(f"Building {setup_file} - version: {version_info}")

# Real bug found by actually running this twice in one workspace (composer
# needs both scarlets and scarletcomposer wheels, built back-to-back by two
# calls to this script): bdist_wheel reuses build/ as a staging directory,
# and without cleaning it between invocations, the second build silently
# bundles the first build's already-staged files too (scarletcomposer's
# wheel ended up containing scarlets/*.py alongside its own files). Clean
# both build/ and the setup file's own *.egg-info before every build so
# back-to-back invocations in the same job can never contaminate each
# other, regardless of build order.
shutil.rmtree("build", ignore_errors=True)
for egg_info in Path(".").glob("*.egg-info"):
    shutil.rmtree(egg_info, ignore_errors=True)

subprocess.run([sys.executable, setup_file, "bdist_wheel"], check=True)

dist_path = Path("./dist/")
built_wheels = sorted(dist_path.glob("*.whl"), key=lambda p: p.stat().st_mtime)
if not built_wheels:
    raise SystemExit(f"bdist_wheel produced no .whl file in {dist_path}")
package_info = built_wheels[-1]
print(f"Built: {package_info}")

if mode == "prod":
    # Same Gemfury account gustavo's own packages publish to
    # ("osu-home-stri") - Gemfury distinguishes packages by their own
    # `name` field (scarlets / scarletcomposer / gustavo), not by account,
    # so this adds new packages to that same account rather than
    # colliding with gustavo's own.
    subprocess.run(
        [
            "curl",
            "-F",
            "package=@" + str(package_info),
            "https://{}@push.fury.io/osu-home-stri/".format(GEMFURY_TOKEN),
        ],
        check=True,
    )
