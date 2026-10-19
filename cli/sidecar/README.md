# sidecar

`sidecar` is a macOS command that connects an iPad as a Sidecar display. A
generated iPad shortcut runs it over SSH, so you can start Sidecar from the
iPad without touching the Mac.

`sidecar connect NAME` connects the iPad, makes it the primary display at its
native Retina resolution, and makes the Mac's current monitor mirror it. A TV
connected to the Mac then follows the iPad's desktop size and aspect ratio.
Running `connect` again repairs the display arrangement without dropping the
connection.

## Install

Requires macOS with Apple's Command Line Tools and an iPad that supports
Sidecar. There are no other dependencies. From a clone of this repository:

```sh
git clone https://github.com/ramtoshiya/skills.git
cd skills
sh cli/sidecar/install.sh
```

The installer compiles `sidecar.m` into `~/.local/share/sidecar/0.1.0/` and
links `~/.local/bin/sidecar` to it. It refuses to replace a different command
at that path. Run it again after changing the source. If `~/.local/bin` is not
on your `PATH`, add it or run `~/.local/bin/sidecar` by its full path. The
[machine setup](../../docs/setup.md) adds it.

## Commands

```sh
sidecar devices                  # list iPads that Sidecar can use
sidecar connect "My iPad"        # connect and arrange the displays
sidecar status "My iPad"         # show the mirror direction and resolution
sidecar disconnect "My iPad"
```

Device names must match exactly. A locked or sleeping iPad can return Sidecar
error `-203`. Unlock it and retry. Every operation has a timeout. The exit
status tells what failed: 1 arguments, 2 device, 3 framework, 4 connection,
5 timeout, 6 mirroring.

## Create the iPad shortcut

1. On the Mac, turn on **System Settings > General > Sharing > Remote Login**.
2. Find the Mac's host name with `scutil --get LocalHostName` and add `.local`.
   Find your account name with `id -un`.
3. Generate the shortcut:

   ```sh
   xcrun swift cli/sidecar/create-shortcut.swift \
     My-Mac.local mylogin "My iPad" "$HOME/Downloads/iPad Display Shortcuts"
   ```

4. Open **Start iPad Display.shortcut** in Shortcuts. It syncs to the iPad
   through iCloud, or you can copy the file to the iPad and import it there.
5. In the shortcut's **Run Script over SSH** action, enter your Mac password, or
   switch to SSH key authentication and add the key that Shortcuts generates
   to the Mac's `~/.ssh/authorized_keys`.

The generated file holds no credentials. A copy you export after entering a
password does, so keep it out of the repository.

The shortcut runs:

```sh
exec /usr/bin/caffeinate -u -d -t 45 "$HOME/.local/bin/sidecar" connect 'My iPad'
```

The Mac must be reachable on the network and logged in. Keep the iPad awake and
unlocked. Wireless Sidecar also needs the same Apple Account on both devices,
with Bluetooth, Wi-Fi, and Handoff on, as described in
[Apple's Sidecar instructions](https://support.apple.com/en-gb/102597).
`caffeinate` wakes the display only after SSH connects, so wake a sleeping Mac
first, or turn on **Wake for network access**. The shortcut only starts
Sidecar. End the session from the iPad.

## How it works

`sidecar` picks the iPad's default Retina mode from the modes the display
advertises. It removes any previous mirror arrangement, sets the iPad's mode
and position, and makes the Mac monitor mirror the iPad. Before reporting
success, it checks the primary display, the mirror direction, the desktop size
in points, and the size in pixels. The changes last for the current login
session. On the iPad it was tested with, the desktop is 1194 × 834 points
backed by 2388 × 1668 pixels.

Connecting uses Apple's private `SidecarCore` framework, as
[SidecarLauncher](https://github.com/Ocasio-J/SidecarLauncher) does. A macOS
update can change it. The command checks that the private methods it needs
exist and reports an incompatibility instead of crashing. Display arrangement
uses the public CoreGraphics API.

Tested on macOS 26.5.1.
