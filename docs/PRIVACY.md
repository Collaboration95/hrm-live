# Privacy

HRM Live reads Bluetooth heart-rate notifications from the selected strap and
stores settings in `~/.config/hrm/config.json`.

Session samples stay in memory while recording. A CSV is written only after
you stop a non-empty session and choose a destination in the save dialog.
Cancelling the dialog creates no file.

The app does not send Bluetooth readings, settings, or exported CSV files to a
server. Exported files are plain CSV files at the location you choose.

HRM Live is a fitness display and recording tool. It is not a medical device
and should not be used for medical diagnosis, treatment, or emergency alerts.
