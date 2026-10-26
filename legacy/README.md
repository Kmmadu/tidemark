# legacy/ — AutoConfigBackup (unmaintained)

This directory contains the original **AutoConfigBackup** Flask application
that Tidemark is replacing. It is kept only as a reference for the M1
importer and for historical interest.

## Do not run this on a real network

The code in this directory has known security problems:

- The Flask development server can bind to `0.0.0.0` and runs with `debug=True`
  in `app.py`.
- There is no authentication.
- There is no CSRF protection.
- `POST /api/restore/<filename>` will push a saved configuration onto a device
  with no preview, no risk flags, no pre-restore snapshot and no typed
  confirmation. It is destructive.

It is preserved so that the M1 importer can read the old
`config/devices.yaml` and the old `backups/` layout. Nothing under
`tidemark/` may import from this directory.

## Old `devices.yaml` format (read by the M1 importer)

```yaml
devices:
  - name: Core-Switch-01          # optional display name
    host: 192.168.1.1             # required
    device_type: cisco_ios        # required, a Netmiko device_type string
    port: 22                      # optional, defaults to 22
    # secret: enable-secret       # optional, per-device enable secret