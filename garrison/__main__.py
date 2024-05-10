import contextlib
import hashlib
import logging.handlers
import time
import logging
import os
import sys

from .containers import (
    ContainerInfo,
    ContainerNotStartedException,
    VolumeInfo,
    get_container_exit_status,
    get_included_container_volumes,
    get_enabled_containers,
    get_server_name,
    remove_container,
    run_backup_container,
)

from .constants import (
    INCLUDE_BIND_MOUNTS_LABEL,
)

logger = logging.getLogger("garrison")
handler = logging.StreamHandler(stream=sys.stdout)
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

# Env variables
CRON_SCHEDULE = os.getenv("CRON_SCHEDULE", "0 2 * * *")
BACKUP_CONTAINER_IMAGE = os.environ["BACKUP_CONTAINER_IMAGE"]
BACKUP_CONTAINER_COMMAND = os.environ["BACKUP_CONTAINER_COMMAND"]
BACKUP_CONTAINER_VOLUMES = os.getenv("BACKUP_CONTAINER_VOLUMES", "")
REQUIRE_ENABLE = os.getenv("REQUIRE_ENABLE", "false") == "true"


def _get_extra_volumes_for_backup_container() -> dict[str, dict[str, str]]:
    extra_volumes = {}
    for volume_str in BACKUP_CONTAINER_VOLUMES.split(","):
        if volume_str == "":
            continue
        volume_parts = volume_str.split(":")
        if len(volume_parts) == 2:
            volume_parts.append("rw")
        extra_volumes[volume_parts[0]] = {
            "bind": volume_parts[1],
            "mode": volume_parts[2],
        }
    return extra_volumes


def _trigger_backup(container: ContainerInfo, volume: VolumeInfo, server_name: str):
    extra_volumes = _get_extra_volumes_for_backup_container()
    volume_hash = hashlib.md5(volume["source"].encode()).hexdigest()
    # TODO make the command more flexible (possibly using jinja2)
    command = BACKUP_CONTAINER_COMMAND.format(
        server_name=server_name,
        project_name=container["project"],
        container_name=container["name"],
        volume_name=volume["name"] or volume_hash,
        volume_path=volume["destination"],
    )
    return run_backup_container(
        BACKUP_CONTAINER_IMAGE,
        command,
        f"garrison_{container['id']}_{volume_hash}",
        environment=dict(os.environ),
        volumes={
            volume["name"]: {"bind": volume["destination"], "mode": "ro"},
            **extra_volumes,
        },
    )


def main():
    server_name = get_server_name()
    logger.info(f"Running on server '{server_name}'")

    backup_container_ids = []

    containers = get_enabled_containers(REQUIRE_ENABLE)
    if not containers:
        logger.info("Did not find any containers to backup")
        return

    for container in containers:
        logger.debug(
            f"Found container '{container['name']}' in project '{container['project']}'"
        )
        include_bind_mounts = (
            container["labels"].get(INCLUDE_BIND_MOUNTS_LABEL, "false") == "true"
        )
        volumes = get_included_container_volumes(
            container,
            include_bind_mount=include_bind_mounts,
        )
        for volume in volumes:
            logger.info(
                f"Running backup on '{server_name}' for container '{container['name']}' ({container['id']}) "
                f"in project '{container['project']}' on volume '{volume['name'] or volume['source']}'"
            )
            with contextlib.suppress(ContainerNotStartedException):
                backup_container_ids.append(
                    _trigger_backup(container, volume, server_name)
                )

    # Wait for all backups to complete
    start_time = time.time()
    while not all(
        get_container_exit_status(container_id) != -1
        for container_id in backup_container_ids
    ):
        if time.time() - start_time > 120:
            # TODO handle case where backups do not complete within timeframe
            pass
        time.sleep(5)
    for container_id in backup_container_ids:
        if get_container_exit_status(container_id) != 0:
            logger.warning(
                f"Backup container with ID {container_id} did not exit with a success status. "
                "Will leave container for investigation purposes."
            )
            continue
        remove_container(container_id)


if __name__ == "__main__":
    main()
