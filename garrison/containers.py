import contextlib
import logging
import time
from typing import TypedDict
import docker
import docker.errors
import socket

from .constants import (
    COMPOSE_PROJECT_LABEL,
    ENABLE_LABEL,
    VOLUME_EXCLUDE_LABEL,
    VOLUME_INCLUDE_LABEL,
)

logger = logging.getLogger(__name__)

client = docker.from_env()


class ContainerNotStartedException(Exception):
    """Exception raised if a container does not start."""


class ContainerInfo(TypedDict):
    """TypedDict with attribute information about a container."""

    id: str
    name: str
    labels: dict[str, str]
    project: str | None
    image: str
    environment: dict[str, str]


class VolumeInfo(TypedDict):
    """TypedDict with attribute information about a volume."""

    type: str
    name: str | None
    source: str
    destination: str


def get_server_name() -> str:
    """Get the name of the server the docker daemon runs on.

    Returns:
        Name of the server.
    """
    return client.info()["Name"]


def get_enabled_containers(require_enabled: bool = False) -> list[ContainerInfo]:
    """Get all containers where backup is enabled.

    Containers started by garrison to run the backup are ignored as well.

    Args:
        require_enabled: If to include only containers which are explicitely enabled for backup.
            Defaults to False.

    Returns:
        All containers where backup is enabled.
    """
    self_hostname = socket.gethostname()
    self_container = None
    with contextlib.suppress(docker.errors.NotFound):
        self_container = client.containers.get(self_hostname)
    containers = []
    for container in client.containers.list():
        if self_container and container.id == self_container.id:
            # Skip itself
            continue
        container_info: ContainerInfo = {
            "id": container.id,
            "name": container.name,
            "labels": container.labels,
            "project": container.labels.get(COMPOSE_PROJECT_LABEL),
            "image": container.image.tags[0],
            "environment": {
                item.split("=")[0]: item.split("=")[1]
                for item in container.attrs["Config"]["Env"]
            },
        }
        if container_info["name"].startswith("garrison_"):
            logger.warning(
                f"Found left over backup container with name {container_info['name']}"
            )
            continue
        if container_info["labels"].get(ENABLE_LABEL, "true") == "false":
            logger.info(
                f"Skipping container '{container_info['name']}' as backup is disabled"
            )
            continue
        if (
            require_enabled
            and container_info["labels"].get(ENABLE_LABEL, "false") != "true"
        ):
            logger.info(
                f"Skipping container '{container_info['name']}' "
                "as containers need to be enabled explicitely backup is not enabled"
            )
            continue
        containers.append(container_info)
    return containers


def get_included_container_volumes(
    container: ContainerInfo, include_bind_mount: bool = False
) -> list[VolumeInfo]:
    """Get volumes for a container.

    Volumes will be filtered according to the labels.

    Args:
        container: Information about the container to get the volumes for.
        include_bind_mount: If bind mounts should be included or not. Defaults to False

    Returns:
        All included volumes from the container.
    """
    included_volumes: None | str = container["labels"].get(VOLUME_INCLUDE_LABEL)
    if included_volumes:
        included_volumes = included_volumes.split(",")
    excluded_volumes: None | str = container["labels"].get(VOLUME_EXCLUDE_LABEL)
    if excluded_volumes:
        excluded_volumes = excluded_volumes.split(",")

    docker_container = client.containers.get(container["id"])
    volumes = []
    for volume in docker_container.attrs["Mounts"]:
        volume_name: str = volume.get("Name", volume["Source"])
        if container["project"]:
            # Remove prefix from volume name for docker-compose project
            volume_name = volume_name.removeprefix(f"{container['project']}_")
        if include_bind_mount is False and volume["Type"] == "bind":
            logger.info(
                f"Skipping volume '{volume_name}' on '{container['name']}' "
                "as it is a bind mount and bind mounts are excluded"
            )
            continue
        if included_volumes is not None and volume_name not in included_volumes:
            logger.info(
                f"Skipping volume '{volume_name}' on '{container['name']}' "
                "because it's not included"
            )
            continue
        if excluded_volumes is not None and volume_name in excluded_volumes:
            logger.info(
                f"Skipping volume '{volume_name}' on '{container['name']}' "
                "because it's excluded"
            )
            continue
        volumes.append(
            {
                "type": volume["Type"],
                "name": volume.get("Name"),
                "source": volume["Source"],
                "destination": volume["Destination"],
            }
        )
    return volumes


def run_backup_container(
    image: str,
    command: str,
    name: str,
    environment: dict[str, str],
    volumes: dict[str, dict[str, str]],
) -> str:
    """Run the backup container.

    This function will wait until the container is actually started.

    Args:
        image: The image for the backup container.
        command: The backup command to run in the backup container.
        name: The name for the backup container.
        environment: The environment for the backup container.
        volumes: Volumes for the backup container.

    Returns:
        The ID of the started backup container.

    Raises:
        ContainerNotStartedException: If the backup container does not start within 30 seconds.
    """
    logger.debug(
        f"Running backup container with name {name}, image {image} and command '{command}'"
    )
    # TODO handle docker.errors.APIError: 409 Client Error if container with the name already exists
    try:
        backup_container = client.containers.run(
            image,
            command=command,
            name=name,
            environment=environment,
            volumes=volumes,
            detach=True,
        )
    except docker.errors.APIError as exc:
        if exc.status_code == 409:
            logger.warning(
                f"Unable to start backup container {name}: "
                "There is already a container running with this name. "
                "Please remove the container manually when it's done."
            )
            return
        raise exc
    logger.debug(f"Created backup container with ID {backup_container.id}")
    start_time = time.time()

    while client.containers.get(backup_container.id).status == "created":
        if time.time() - start_time > 30:
            logger.error(
                f"Waited for 30 seconds for backup container {name} ({backup_container.id}) to start, "
                "but nothing happened. Will keep container for investigation purposes."
            )
            raise ContainerNotStartedException(name)
        time.sleep(1)

    return backup_container.id


def get_container_exit_status(container_id: str) -> int:
    """Get the exit code of a container.

    Args:
        container_id: The ID of the container to get the exit code for.

    Returns:
        -1 if the container has not exited, otherwise the exit code
    """
    docker_container = client.containers.get(container_id)
    status: str = docker_container.attrs["State"]["Status"]
    if status != "exited":
        return -1
    return docker_container.attrs["State"]["ExitCode"]


def remove_container(container_id: str):
    """Removes a container.

    Silently ignores errors if the container does not exist.

    Args:
        container_id: The ID of the container to remove.
    """
    logger.debug(f"Removing container with ID {container_id}")
    try:
        client.containers.get(container_id).remove()
    except docker.errors.NotFound:
        logger.warning(
            f"Tried to remove container with ID {container_id} "
            "but the container does not exist."
        )
        return
    logger.debug(f"Successfully remove container with ID {container_id}")
