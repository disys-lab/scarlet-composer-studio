import click, os, logging, warnings, pkg_resources
from scarletcomposer.composer.ScarletHandler import ScarletHandler
from streamlit.web import cli

def fxn():
    warnings.warn("deprecated", UserWarning)

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    fxn()

try:
    VERSION = pkg_resources.require("scarletcomposer")[0].version
except Exception:
    VERSION = "dev"


@click.version_option(version=VERSION)
@click.group(help="Manage creation and deployment of Scarlets from the CLI.")
def scarletcomposer():
    pass


@click.version_option(version=VERSION)
@scarletcomposer.group(help="Manage creation and deployment of Scarlets")
def composer():
    pass


def _interpret(directory, file, sh):
    target_script = os.path.join(directory, file)
    if os.path.isfile(target_script):
        sh.interpretScript(target_script)
        logging.info(f"Interpreted {target_script}")
        for scarlet, attrs in sh.getScarlets().items():
            logging.info(f"  Scarlet: {scarlet} — {attrs['scarlet_attributes']}")
    else:
        logging.error(f"{target_script} does not exist")
        raise SystemExit(1)


@composer.command()
@click.option("--deploy", is_flag=True, help="Deploy scarlets to Redis after interpretation")
@click.option("--file", "file", default=None, help="Target file within dir")
@click.argument("dir")
def compose(deploy, file, dir):
    """Parse a Python script (or directory) for #scarlet declarations."""
    sh = ScarletHandler()
    sh.printLog()

    if file:
        _interpret(dir, file, sh)
    else:
        if os.path.exists(dir):
            for scarlet_file in os.listdir(dir):
                _interpret(dir, scarlet_file, sh)
        else:
            logging.error(f"{dir} does not exist")
            raise SystemExit(1)

    if deploy:
        scarlets = list(sh.getScarlets().keys())
        logging.info(f"Deploying: {', '.join(scarlets)}")
        sh.deployScarlets()


@composer.command(name="gui", help="Start the Scarlet Composer web UI")
@click.option("--port", "-p", default=8501, show_default=True, help="Streamlit port")
@click.option("--lport", "-lp", default=9099, show_default=True,
              help="Background Tornado port (node identity / getNodeInfo)")
def gui(port, lport):
    from scarletcomposer.pages.config.BackgroundServer import start_background_tornado

    cwd = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    gui_runner_file = os.path.join(cwd, "Scarlets.py")

    os.environ["STREAMLIT_PORT"] = str(port)
    os.environ["STREAMLIT_LIP_PORT"] = str(lport)

    logging.info(f"Starting background service on port {lport}...")
    try:
        start_background_tornado(port=lport)
        logging.info(f"Background service started on port {lport}")
    except Exception as e:
        logging.critical(f"Could not start background service: {e}")

    cli.main_run([
        gui_runner_file,
        "--server.headless", "true",
        "--server.port", int(port),
        "--server.enableCORS", "false",
        "--server.enableXsrfProtection", "false",
    ])
