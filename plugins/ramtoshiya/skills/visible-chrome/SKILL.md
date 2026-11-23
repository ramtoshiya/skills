---
name: visible-chrome
description: Open a visible Chrome with a persistent profile for user sign-in, then drive the signed-in site over CDP.
---

# Visible Chrome {:#visible-chrome}

Use this workflow when a site needs the user's own browser login and the task calls for browser automation. Use a real, visible Chrome, never headless. The helper requires macOS, Node.js with built-in WebSocket support, and Google Chrome. Set `CHROME_APP` to an alternate Chrome app bundle if needed.

## Open and sign in {:#sign-in}

Choose a stable profile name for the site or project. The helper stores it at `~/.local/share/agent-chrome/<name>`, so the name `career` maps to `~/.local/share/agent-chrome/career`. Treat the profile and CDP endpoint as credentials. Do not read or copy cookies or authentication files into a repository. Coordinate access to a profile with other sessions before using or closing its Chrome.

Run the helper relative to this skill's directory:

```sh
node scripts/chrome.mjs open career corner
```

The command prints the loopback CDP HTTP endpoint. It reuses Chrome when the profile's `DevToolsActivePort` answers. Otherwise it starts a separate Chrome with muted audio. Use the endpoint's `/json/list` to find a page and its WebSocket URL. Drive that page with CDP using the tools available in the project.

Detect sign-out using the site's page state. When the user must sign in, run `node scripts/chrome.mjs open career front`, navigate to the site's login page, and notify the user with the exact action needed. Let the user enter credentials and complete any authentication prompts. Wait for their response and verify the signed-in page. Do not ask for credentials in chat. Run `node scripts/chrome.mjs open career corner` before unattended work.

## Work and close {:#work-and-close}

Keep audio muted and use `corner` whenever the user does not need to act. With BetterDisplay, `betterdisplaycli`, Swift, and one built-in display, the helper creates a 1200 by 900 point virtual screen for the profile. It places that screen at the built-in display's lower-right corner and puts the 1100 by 800 Chrome window 40 points inside it. The pointer can cross that corner onto the virtual screen. The helper falls back to the old corner placement if it cannot create or arrange the screen. macOS can clamp that placement and leave part of Chrome visible.

The display is named `agent-chrome-<profile>`. The helper removes a stale screen of that name before starting a new Chrome, reuses it while Chrome is running, and discards it after moving Chrome to `front` or closing Chrome. It never changes the origin of an existing display. It uses these BetterDisplay operations. Set `tag_id` to the returned `tagID` before the last two commands:

```sh
betterdisplaycli create -type=VirtualScreen -virtualScreenName=agent-chrome-career -useResolutionList=on -resolutionList=1200x900 -virtualScreenHiDPI=off
betterdisplaycli get -name=agent-chrome-career -type=VirtualScreen -identifiers
betterdisplaycli set -tagID="$tag_id" -connected=on
betterdisplaycli discard -tagID="$tag_id"
```

The helper uses CoreGraphics to move only the virtual screen and verifies the built-in display's bounds and the virtual screen's resulting origin. A second active display makes it fall back, so it does not rearrange existing displays. A profile's `virtual-display` marker records that cleanup may be needed after a crash. If cleanup fails, restore access to BetterDisplay and run `close` again.

The helper starts Chrome with `--disable-blink-features=AutomationControlled` and `--window-size=1100,800`. Judge browser detection by signals the page or server can observe, including `navigator.webdriver`, viewport, input, and request behavior. A Chrome-only unsupported-flag notice is not itself a page signal and can affect viewport size. These flags do not guarantee that a site cannot detect automation.

When the task is done, close Chrome with `node scripts/chrome.mjs close career` after checking that no other session uses it. Keep the profile for later sign-ins. The helper does not delete profiles. Never expose the CDP endpoint outside loopback.
