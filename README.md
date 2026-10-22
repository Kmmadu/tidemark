![AutoConfigBackup Dashboard](https://raw.githubusercontent.com/Kmmadu/AutoConfigBackup/main/In_progress.png)

# Tidemark

A Linux desktop app that backs up, compares and safely restores network device configurations over SSH.

Tidemark keeps a permanent record of every configuration your devices have had, shows exactly what changed between any two points, and lets you roll back with guard rails.

## Status

Early development. Tidemark is being rebuilt from its web-based predecessor (AutoConfigBackup, a Flask dashboard) into a native Linux application. The old Flask version remains in the git history.

See the roadmap below for what is done and what is next.

## What it will do

- Back up device configs over SSH on a schedule or on demand
- Store every change as a versioned snapshot in a local git repository
- Show clean diffs between any two snapshots, ignoring noise such as timestamps
- Restore a saved config with a preview, risk warnings, a pre-restore snapshot and a typed confirmation
- Alert on failed backups and unexpected changes (desktop, email, Slack, Telegram)
- Run without a server: everything stays on your machine

## Supported devices

Vendors are defined by small YAML profiles, so adding a vendor does not need code changes. Any device reachable over SSH can be added with a custom profile.

- Tested: MikroTik RouterOS, Cisco IOS
- Included, community and untested: Cisco NX-OS and ASA, Juniper, Arista, Huawei, Fortinet, Ubiquiti
- Anything else: custom profile with your own config command

Fetching, diffing and versioning work for every profile. Restore is enabled per profile and starts with Cisco IOS.

## How it is built

- Python 3.11+, Netmiko for SSH, SQLite for inventory and history
- PySide6 (Qt) desktop interface
- Headless core, so the GUI, CLI and scheduler daemon share the same engine
- Credentials stored in the system keyring
- Data kept in standard XDG folders

## Roadmap

- [ ] M0: Clean up, secure and add tests to the existing code
- [ ] M1: Core engine, vendor profiles and storage
- [ ] M2: Credentials and safe restore
- [ ] M3: Scheduler daemon and CLI
- [ ] M4: Desktop GUI
- [ ] M5: Alerts and notifications
- [ ] M6: Packaging (AppImage, .deb) and first release

## Security notes

- Never commit credentials. Tidemark keeps them in the system keyring, not in project files.
- Saved configs can contain secrets. Treat the data folder as sensitive.
- Diffs shown in the app and sent in alerts are redacted.
- Always test restore on a lab device first.

## Author

Kingsley Mmadubugwu, network engineer.

## License

To be added.
