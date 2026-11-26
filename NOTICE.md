# Credits and dependency boundaries

The source authored for this project is provided under GPL-3.0-only; see LICENSE. Existing copyright and attribution headers are retained.

- `native_decoder.c` uses Annex B access-unit assembly based on Valentin Radu's `nbt_decoder.c`, as supplied in JayJay3071/nbt-android-auto. Copyright (C) 2026 Valentin Radu. Those source contributions are GPL-3.0-only. https://github.com/JayJay3071/nbt-android-auto and https://github.com/valinet/nbt-android-auto
- MacPlay is an external GPLv3 dependency. This repository contains a separate adaptation generator, not the installed application's code, binaries, authentication assets or pairing data. Source and distribution: https://github.com/Roylyl/MacPlay
- The underlying BMW-NBT-Emulator graphics bridge is an external dependency, copyright 2026 davisod & JEtsKi. The checked upstream project uses PolyForm Strict 1.0.0. Its source and modified binaries are not redistributed here. The integration directory contains this project's extension code only. Obtain the necessary rights for your local upstream installation and adaptations separately. https://github.com/DAviS0d/BMW-NBT-Emulator
- BMW firmware, BMW libraries, QNX SDK/runtime components and locally provisioned authentication or SSH keys are external prerequisites and are not part of this distribution.
- FFmpeg is an external dependency for QNX decoding; use the pinned upstream build workflow in your existing authorized development environment and retain its applicable notices when distributing binaries. No FFmpeg binaries are included here.

The runtime and integration directories describe and test a local emulator integration. They are not a BMW firmware release or a completed native QNX CarPlay protocol implementation.

The separate `vehicle_installer` is an original GPL-3.0-only desktop installer. It downloads, verifies and installs the unmodified JayJay3071 official vehicle package at runtime, under that package's own license and additional permissions. The upstream release binaries are not redistributed in this repository or embedded in our application. See https://github.com/JayJay3071/nbt-android-auto/blob/master/NOTICE.md and the pinned release page linked in the installer documentation. The installer itself has not been validated on a real vehicle.

Packaged desktop installers include Python (PSF license), Tcl/Tk (Tcl/Tk licenses), Paramiko (LGPL-2.1), cryptography (Apache-2.0 or BSD-3-Clause), bcrypt and PyNaCl (Apache-2.0), CFFI (MIT), certifi (MPL-2.0) and the PyInstaller bootloader (GPL-2.0 with the bootloader exception). Dependency metadata and available license files are copied into the application; upstream source is available through each dependency's package project links. Build requirements are in `vehicle_installer/requirements-build.txt`.
