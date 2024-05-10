# Garrison

> Watchtower for backups.

This project has been inspired by the [restic-compose-backup Project](https://github.com/ZettaIO/restic-compose-backup).

## How does it work?

The Garrison container will run a task based on a cron schedule.
On every execution Garrison will select containers and their volumes based on labels.
For every volume to back up, an additional container will be created.
This backup container will have the volume to backup mounted and run the actual backup.

## Configuration

### Environment Variables

The main backup container supports the following Environment Variables:

| Variable name            | Description | Required / Default |
|--------------------------|-------------|--------------------|
| CRON_SCHEDULE            | The schedule when to run backups. | Default: `0 2 * * *` (At 02:00) |
| BACKUP_CONTAINER_IMAGE   | The image name to use for the backup container. The backup container is responsible for running the actual backup. | Required |
| BACKUP_CONTAINER_COMMAND | The command with which the backup container is started. It needs to be a template where the information what to backup is inserted. | Required |
| BACKUP_CONTAINER_VOLUMES | Additional volumes to mount in the backup container. The format is based on the [docker compose file volumes short syntax](https://docs.docker.com/compose/compose-file/05-services/#short-syntax-5), delimited by `,`. | Optional |
| REQUIRE_ENABLE           | Set to `true` to include only containers which are explicitely enabled for backup by a label. | Default: `false` |

To connect to the docker daemon the environment variables supported by docker-py are used.
You can read more about these in the [docker-py documentations](https://docker-py.readthedocs.io/en/stable/client.html#docker.client.from_env).

For the container running the actual backup, all environment variables will be passed on.

### Labels

Labels, that can be set on containers to control how their volumes are backed up.

| Label name | Description |
|------------|-------------|
| `at.jyasapara.garrison.enable` | Set to `false` to disable backups for this container. If `REQUIRE_ENABLE` is set to true, set this to `true` to enable backups for this container. |
| `at.jyasapara.garrison.volumes.include` | List of volume names or bind mount paths of the container to backup, seperated by `,`. If unset, all volumes will be seen as included. |
| `at.jyasapara.garrison.volumes.exclude` | List of volume names or bind mount paths of the container to exclude from backup, separated by `,`. If unset, no volumes will be seen as excluded. |
| `at.jyasapara.garrison.volumes.include_bind` | If set to `true`, bind mounts are included in the list of volumes to back up. Defaults to `false`. |

## Backup command formatting

Currently the backup command needs to be a python3 format string with named replacement fields.
The following replacement fields all need to be present:

| Field name | Description |
|------------|-------------|
| server_name | Name of the underlying server where the docker daemon is running. |
| project_name | Name of the docker compose project of the container being backed up. |
| container_name | Name of the container being backed up. |
| volume_name | Name of the volume being backed up. To prevent formatting issued, for bind mounts the local path is hashed. |
| volume_path | The path of the volume inside the container. This will be the same for the container being backed up and the backup container. |

As of now additional fields are not supported.
