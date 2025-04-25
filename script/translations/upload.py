#!/usr/bin/env python3
"""Merge all translation sources into a single JSON file."""

import json
import os
import pathlib
import re
import subprocess

from .const import CLI_2_DOCKER_IMAGE, CORE_PROJECT_ID, INTEGRATIONS_DIR
from .error import ExitApp
from .util import get_current_branch, get_lokalise_token, load_json_from_path

FILENAME_FORMAT = re.compile(r"strings\.(?P<suffix>\w+)\.json")
LOCAL_FILE = pathlib.Path("build/translations-upload.json").absolute()
CONTAINER_FILE = "/opt/src/build/translations-upload.json"
LANG_ISO = "en"


def run_upload_docker():
    """Run the Docker image to upload the translations."""
    print("Running Docker to upload latest translations.")
    run = subprocess.run(
        [
            "docker",
            "run",
            "-v",
            f"{LOCAL_FILE}:{CONTAINER_FILE}",
            "--rm",
            f"lokalise/lokalise-cli-2:{CLI_2_DOCKER_IMAGE}",
            # Lokalise command
            "lokalise2",
            "--token",
            get_lokalise_token(),
            "--project-id",
            CORE_PROJECT_ID,
            "file",
            "upload",
            "--file",
            CONTAINER_FILE,
            "--lang-iso",
            LANG_ISO,
            "--convert-placeholders=false",
            "--replace-modified",
        ],
        check=False,
    )
    print()

    if run.returncode != 0:
        raise ExitApp("Failed to download translations")


def generate_upload_data():
    """Generate the data for uploading."""
    # Load base strings.json file to memory dict.
    translations = load_json_from_path(INTEGRATIONS_DIR.parent / "strings.json")
    translations["component"] = {}

    # Iterate over all integration's string.json files and merge them into the base translations dict.
    for path in INTEGRATIONS_DIR.glob(f"*{os.sep}strings*.json"):
        component = path.parent.name
        match = FILENAME_FORMAT.search(path.name)
        # Example: homeassistant/components/hue/strings.xx.json
        # suffix is "xx"
        platform = match.group("suffix") if match else None

        # Example: translations["component"]["hue"]
        # Where "hue" is the component subdirectory name (integration subdirectory name)
        # parent would be the dict value of the integration name (component key)
        parent = translations["component"].setdefault(component, {})

        if platform:
            # Example: translations["component"]["hue"]["platform"] = {} if not present
            platforms = parent.setdefault("platform", {})
            # Example: translations["component"]["hue"]["platform"]["xx"] = {}
            parent = platforms.setdefault(platform, {})

        # Load from component's string.json file.
        parent.update(load_json_from_path(path))

    return translations


def run():
    """Run the script."""
    if get_current_branch() != "dev" and os.environ.get("AZURE_BRANCH") != "dev":
        raise ExitApp(
            "Please only run the translations upload script from a clean checkout of dev."
        )

    translations = generate_upload_data()

    LOCAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_FILE.write_text(json.dumps(translations, indent=4, sort_keys=True))

    run_upload_docker()

    return 0
