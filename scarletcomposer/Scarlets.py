import streamlit as st

st.set_page_config(
    page_title="ScarletComposer",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "sidebar_state" not in st.session_state:
    st.session_state.sidebar_state = "expanded"
st.session_state.sidebar_state = "expanded"

import sys, os, logging, json, redis, requests, docker, traceback
import pandas as pd
from pathlib import Path
from scarletcomposer.composer.ScarletHandler import ScarletHandler
from scarlets.core.Mapper import Mapper
from scarletcomposer.pages.config.Sidebar import sidebarInit


def home_page():
    sidebarInit()
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

    st.subheader("Scarlet Management")

    st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] button { margin-right: 20px; }
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
        font-size: 1.1rem; color: #333333;
    }
    </style>""", unsafe_allow_html=True)

    error_container = st.container()
    log_placeholder = st.empty()

    view_tab, deploy_tab, build_tab = st.tabs(["View Scarlets", "Deploy Scarlets", "Container Builds"])

    def check_registry_exists(registry_url, error_container, use_https):
        protocol = "https" if use_https else "http"
        registry_api = f"{protocol}://{registry_url}/v2/"
        try:
            response = requests.get(registry_api, timeout=5)
            if response.status_code == 200:
                error_container.success(f"Registry at {registry_url} is reachable!")
                return True
            else:
                error_container.warning(f"Registry responded with status {response.status_code}.")
                return False
        except requests.exceptions.RequestException as e:
            error_container.error(f"Error connecting to registry: {e}")
            return False

    def build_image(path, repository, error_container, log_placeholder):
        client = docker.from_env()
        try:
            with error_container:
                with st.spinner("Building Docker image..."):
                    image, logs = client.images.build(
                        path=path, platform="linux/amd64", tag=repository, rm=True
                    )
                    for log in logs:
                        if "stream" in log:
                            print(log["stream"].strip())
            error_container.success(f"Image {repository} built successfully!")
        except docker.errors.BuildError as e:
            error_container.error(f"Docker build error: {e}")
        except Exception as e:
            error_container.error(f"Unexpected error: {e}")
            print(traceback.format_exc())

    def push_image(repository, error_container):
        client = docker.from_env()
        try:
            with error_container:
                with st.spinner("Pushing Docker image..."):
                    for line in client.images.push(repository, stream=True, decode=True):
                        if "errorDetail" in line:
                            error_container.error(f"Error: {line['errorDetail'].get('message')}")
            error_container.success(f"Image {repository} pushed successfully!")
        except docker.errors.APIError as e:
            error_container.error(f"Docker API error: {e}")
        except Exception as e:
            error_container.error(f"Unexpected error: {e}")

    def flattened_scarlets(scarlet_dict, scarlet="all"):
        def getrow(key, value):
            return {
                "Key": key,
                "Scarlet Type": value.get("scarlet_type", ""),
                "Mode": value.get("scarlet_attributes", {}).get("mode", ""),
                "Content": value.get("content", "").replace(";", ""),
                "Description": value.get("description", "").replace(";", ""),
            }
        flattened_data = []
        if scarlet == "all":
            for key, value in scarlet_dict.items():
                flattened_data.append(getrow(key, value))
        else:
            if scarlet in scarlet_dict:
                flattened_data.append(getrow(scarlet, scarlet_dict[scarlet]))
        return pd.DataFrame(flattened_data)

    def interpret(directory, file, sh):
        target_script = directory / file
        if os.path.isfile(target_script):
            sh.interpretScript(target_script)
            st.toast(f"✅ Interpreted {target_script}")
        else:
            st.toast(f"{target_script} does not exist")

    def refreshPage(data_editor_placeholder, mode="new"):
        scarletDict = (
            st.session_state.new_scarlets_dict if mode == "new"
            else st.session_state.all_scarlets_dict
        )
        with data_editor_placeholder.container():
            if mode != "new":
                event = st.dataframe(
                    flattened_scarlets(scarletDict, mode),
                    use_container_width=True,
                    selection_mode="multi-row",
                    on_select="rerun",
                )
                st.session_state.scarlet_select = event.selection

            for scarlet in scarletDict:
                if f"{scarlet}_desc" not in st.session_state:
                    st.session_state[f"{scarlet}_desc"] = "Undefined"
                with st.expander(scarlet):
                    st.dataframe(flattened_scarlets(scarletDict, scarlet), use_container_width=True)
                    desc = st.text_area(
                        "Description", st.session_state[f"{scarlet}_desc"],
                        key=f"{scarlet}_{mode}_DESC",
                    )
                    scarletDict[scarlet]["description"] = desc
                    if st.button("Update Description", key=f"{scarlet}_{mode}_DESC_BTN_UPDATE"):
                        st.session_state[f"{scarlet}_desc"] = desc
                        updateScarlets([scarlet])
                        st.session_state.all_scarlets_dict = scarletDict

    def refreshScarlets():
        if not st.session_state.get("REDIS_AUTH_TOKEN", ""):
            st.info(
                "**Redis not configured.** "
                "Enter your Redis Host and Auth Token in the sidebar and click **Save**.",
                icon="🔌",
            )
            return
        try:
            r = redis.StrictRedis(
                host=str(st.session_state.REDIS_HOST),
                port=int(st.session_state.REDIS_PORT),
                password=str(st.session_state.REDIS_AUTH_TOKEN),
            )
            r.ping()
        except Exception:
            st.warning(
                f"**Cannot reach Redis** at `{st.session_state.REDIS_HOST}:{st.session_state.REDIS_PORT}`. "
                "Check the Host and Auth Token in the sidebar and click **Save**.",
                icon="⚠️",
            )
            return
        matching_data = {}
        for key in r.scan_iter(match="scarlet_definition_*"):
            key_str = key.decode("utf-8")
            try:
                value = json.loads(r.get(key))
                scarlet = key_str.split("scarlet_definition_")[1]
                st.session_state[f"{scarlet}_desc"] = value.get("description", "")
                matching_data[scarlet] = value
            except Exception as e:
                st.error(f"Error processing key {key}: {e}")
        st.session_state.all_scarlets_dict = matching_data

    def updateScarlets(scarlets_to_be_updated):
        scarletContentDict = st.session_state.all_scarlets_dict
        r = redis.StrictRedis(
            host=str(st.session_state.REDIS_HOST),
            port=int(st.session_state.REDIS_PORT),
            password=str(st.session_state.REDIS_AUTH_TOKEN),
        )
        for scarlet in scarlets_to_be_updated:
            key = f"scarlet_definition_{scarlet}"
            if r.exists(key):
                r.set(key, json.dumps(scarletContentDict[scarlet]))
                st.toast(f"Scarlet '{scarlet}' description updated.")
            else:
                st.toast(f"Scarlet '{scarlet}' not found.")

    def deleteScarlets(scarlets_to_be_deleted):
        r = redis.StrictRedis(
            host=str(st.session_state.REDIS_HOST),
            port=int(st.session_state.REDIS_PORT),
            password=str(st.session_state.REDIS_AUTH_TOKEN),
        )
        for scarlet in scarlets_to_be_deleted:
            for key in [f"scarlet_definition_{scarlet}", f"scarletdoc:{scarlet}"]:
                if r.exists(key):
                    r.delete(key)
                    st.toast(f"Deleted '{key}'.")

    def resetScarlets(scarlets_to_be_reset):
        for scarlet in scarlets_to_be_reset:
            status, exception = Mapper(scarlet).clearAll()
            if len(status) and status[0]:
                st.toast(f"Scarlet '{scarlet}' content cleared.")
            else:
                st.toast(f"Could not clear '{scarlet}': {exception}")

    DEFAULT_COLUMNS = ["Key", "Scarlet Type", "Mode", "Content", "Description"]
    default_data = pd.DataFrame(columns=DEFAULT_COLUMNS)

    for key, default in [
        ("new_scarlets_df", default_data),
        ("new_scarlets_dict", {}),
        ("all_scarlets_df", default_data),
        ("all_scarlets_dict", {}),
        ("scarlet_select", {}),
        ("REGISTRY_URL", "localhost:5000"),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    redis_ready = bool(st.session_state.get("REDIS_AUTH_TOKEN", ""))

    with view_tab:
        refreshScarlets()
        refresh_col, update_col, delete_col, reset_col = st.columns(4)
        data_editor_placeholder = st.empty()

        with data_editor_placeholder.container():
            st.dataframe(
                st.session_state.all_scarlets_df,
                use_container_width=True,
                selection_mode="multi-row",
                on_select="rerun",
            )

        with refresh_col:
            if st.button("Refresh Scarlets", disabled=not redis_ready):
                refreshScarlets()

        with update_col:
            if st.button("Update Description", disabled=not redis_ready):
                try:
                    sh = ScarletHandler()
                    sh.interpreter.scarletContent = st.session_state.all_scarlets_dict
                    sh.updateScarletsDescription()
                    refreshScarlets()
                except Exception as e:
                    logging.critical(f"Update Description failed: {e}")
                    error_container.error(f"Error: {e}")

        with delete_col:
            if st.button("Delete Scarlets", disabled=not redis_ready):
                rows = st.session_state.scarlet_select.get("rows", [])
                scarlets_df = flattened_scarlets(st.session_state.all_scarlets_dict, "all")
                deleteScarlets(scarlets_df.iloc[rows]["Key"].tolist())
                refreshScarlets()

        with reset_col:
            if st.button("Reset Scarlets", disabled=not redis_ready):
                rows = st.session_state.scarlet_select.get("rows", [])
                scarlets_df = flattened_scarlets(st.session_state.all_scarlets_dict, "all")
                resetScarlets(scarlets_df.iloc[rows]["Key"].tolist())
                refreshScarlets()

        refreshPage(data_editor_placeholder, "all")

    with deploy_tab:
        data_editor_placeholder = st.empty()
        with data_editor_placeholder.container():
            st.dataframe(st.session_state.new_scarlets_df, use_container_width=True)

        user_path = st.text_input("Script or directory path:", value="")
        scarlet_compile_home = st.text_input("Scarlet compile output path:", value="/tmp/")

        if scarlet_compile_home:
            path = Path(scarlet_compile_home)
            if not path.exists():
                error_container.error(f"{scarlet_compile_home} does not exist")
            elif not path.is_dir():
                error_container.error(f"{scarlet_compile_home} is not a directory")
            else:
                os.environ["SCARLET_COMPILE_HOME"] = scarlet_compile_home
        else:
            error_container.error("SCARLET_COMPILE_HOME is blank.")

        interpret_col, deploy_col = st.columns(2)

        try:
            sh = ScarletHandler()
        except Exception as e:
            logging.critical(f"ScarletHandler init failed: {e}")
            error_container.error(f"ScarletHandler error: {e}")
            sh = None

        with interpret_col:
            if st.button("Interpret Scarlets") and sh:
                if user_path:
                    path = Path(user_path)
                    if path.exists():
                        try:
                            if path.is_file():
                                interpret(path.parent, path.name, sh)
                            elif path.is_dir():
                                for f in path.rglob("*"):
                                    if f.is_file():
                                        interpret(path, f.relative_to(path), sh)
                            st.session_state.new_scarlets_df = flattened_scarlets(sh.interpreter.scarletContent)
                            st.session_state.new_scarlets_dict = sh.interpreter.scarletContent
                        except Exception as e:
                            error_container.error(f"Interpret error: {e}")
                    else:
                        error_container.error(f"Path '{user_path}' does not exist.")
                else:
                    error_container.error("Path is blank.")

        with deploy_col:
            if st.button("Deploy Scarlets", disabled=not redis_ready) and sh:
                try:
                    sh.interpreter.scarletContent = st.session_state.new_scarlets_dict
                    sh.deployScarlets()
                    st.toast("Scarlets deployed to Redis.")
                except Exception as e:
                    logging.critical(f"Deploy failed: {e}")
                    error_container.error(f"Deploy error: {e}")

        refreshPage(data_editor_placeholder)

    with build_tab:
        docker_build_path = st.text_input("Build Context Path", "")
        if docker_build_path:
            path = Path(docker_build_path)
            if not path.exists():
                error_container.error(f"{docker_build_path} does not exist")
            elif not path.is_dir():
                error_container.error(f"{docker_build_path} is not a directory")
        else:
            error_container.info("Enter a Docker build context path.")

        image_name = st.text_input("Image Name", "")
        tag = st.text_input("Tag", "latest")
        registry_url = st.text_input("Registry URL", st.session_state.REGISTRY_URL)
        st.session_state.REGISTRY_URL = registry_url

        use_https = st.session_state.use_https
        registry_exists = check_registry_exists(registry_url, error_container, use_https)
        if registry_exists:
            error_container.success("Registry is available.")

        repository = f"{registry_url}/{image_name}:{tag}"

        if st.button("Build Docker Image") and docker_build_path and image_name:
            build_image(str(Path(docker_build_path)), repository, error_container, log_placeholder)

        if st.button("Push Docker Image") and image_name:
            push_image(repository, error_container)


home_page()
