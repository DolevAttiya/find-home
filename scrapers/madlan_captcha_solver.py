"""
madlan_captcha_solver.py
========================
Automated solver for the PerimeterX "press and hold" challenge on Madlan.

How the challenge works
-----------------------
PerimeterX injects a `#px-captcha` div into the page.
Inside that div it loads an <iframe> (from px-cdn.net) that renders
the actual "press and hold" button.

Two states:
  INTERACTIVE  – iframe is visible and has real dimensions.
                 We hold at its centre — CDP dispatches trusted
                 mousedown/pointerdown to the iframe's content.
  HARD-BLOCK   – iframe stays display:none forever.
                 Repeated failed attempts cause this.
                 Nothing works; we must wait for the block to expire
                 and ask the user to solve manually.

Architecture
------------
1. Launch real Google Chrome (not Playwright's Chromium) — passes fingerprint checks
2. Connect Playwright to it via CDP
3. On challenge detection:
   a. Wait for the iframe inside #px-captcha to become visible (interactive state)
   b. Hold at the centre of the visible iframe using only native CDP mouse events
   c. If iframe never becomes visible (hard block) → notify user
4. Verify cookies were set, retry at most once
"""

from __future__ import annotations

import os
import random
import subprocess
import time
import winreg
from typing import Optional

from playwright.sync_api import Page, Browser, Playwright


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CDP_PORT                  = 9222
CHALLENGE_HTML_THRESHOLD  = 50_000

# How long to wait for the interactive iframe to appear after challenge loads
IFRAME_WAIT_S             = 15

HOLD_MS_MIN       = 1_900
HOLD_MS_MAX       = 2_600
JITTER_PX         = 2.0          # max pixel drift during hold
JITTER_INTERVAL   = 0.080        # seconds between jitter moves
PATH_STEPS        = 35           # Bezier path resolution


# ---------------------------------------------------------------------------
# Chrome discovery
# ---------------------------------------------------------------------------

_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
]


def find_chrome() -> Optional[str]:
    """Returns path to real Google Chrome binary, or None."""
    for p in _CHROME_PATHS:
        if os.path.exists(p):
            return p
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
        )
        p, _ = winreg.QueryValueEx(key, "")
        if os.path.exists(p):
            return p
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Mouse path — cubic Bezier
# ---------------------------------------------------------------------------

def _cubic_bezier(p0, p1, p2, p3, t):
    u = 1 - t
    x = u**3*p0[0] + 3*u**2*t*p1[0] + 3*u*t**2*p2[0] + t**3*p3[0]
    y = u**3*p0[1] + 3*u**2*t*p1[1] + 3*u*t**2*p2[1] + t**3*p3[1]
    return x, y


def _human_path(start: tuple, end: tuple, steps: int = PATH_STEPS) -> list[tuple]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    spread = max(abs(dx), abs(dy), 40)
    cp1 = (
        start[0] + dx * 0.25 + random.uniform(-0.3, 0.3) * spread,
        start[1] + dy * 0.25 + random.uniform(-0.3, 0.3) * spread,
    )
    cp2 = (
        start[0] + dx * 0.75 + random.uniform(-0.2, 0.2) * spread,
        start[1] + dy * 0.75 + random.uniform(-0.2, 0.2) * spread,
    )
    return [_cubic_bezier(start, cp1, cp2, end, i / steps) for i in range(steps + 1)]


# ---------------------------------------------------------------------------
# PerimeterXSolver
# ---------------------------------------------------------------------------

class PerimeterXSolver:

    def __init__(self, profile_dir: str, cdp_port: int = CDP_PORT):
        self.profile_dir  = profile_dir
        self.cdp_port     = cdp_port
        self.chrome_path  = find_chrome()
        self._mouse_x     = 200.0
        self._mouse_y     = 200.0

    # ------------------------------------------------------------------
    # Chrome
    # ------------------------------------------------------------------

    def launch_chrome(self) -> Optional[subprocess.Popen]:
        if not self.chrome_path:
            return None
        args = [
            self.chrome_path,
            f"--remote-debugging-port={self.cdp_port}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-blink-features=AutomationControlled",
        ]
        return subprocess.Popen(args)

    def connect(self, p: Playwright) -> Browser:
        return p.chromium.connect_over_cdp(f"http://localhost:{self.cdp_port}")

    # ------------------------------------------------------------------
    # Challenge detection
    # ------------------------------------------------------------------

    def challenge_active(self, page: Page) -> bool:
        try:
            return len(page.content()) < CHALLENGE_HTML_THRESHOLD
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Wait for interactive iframe
    # ------------------------------------------------------------------

    def _wait_for_iframe(self, page: Page, timeout_s: int = IFRAME_WAIT_S) -> Optional[dict]:
        """
        Waits up to timeout_s seconds for the challenge iframe inside #px-captcha
        to become visible (display != none, non-zero dimensions).

        Returns the iframe's bounding box if it becomes visible, None otherwise
        (= hard-block state — PX is not serving the interactive challenge).
        """
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                result = page.evaluate("""() => {
                    const cap = document.getElementById('px-captcha');
                    if (!cap) return null;
                    const iframe = cap.querySelector('iframe');
                    if (!iframe) return null;
                    const display = getComputedStyle(iframe).display;
                    if (display === 'none') return null;
                    const r = iframe.getBoundingClientRect();
                    if (r.width < 10 || r.height < 10) return null;
                    return {x: r.left, y: r.top, width: r.width, height: r.height};
                }""")
                if result:
                    return result
            except Exception:
                pass
            time.sleep(0.5)
        return None

    # ------------------------------------------------------------------
    # Mouse movement
    # ------------------------------------------------------------------

    def _move_to(self, page: Page, tx: float, ty: float):
        path = _human_path((self._mouse_x, self._mouse_y), (tx, ty))
        for x, y in path:
            page.mouse.move(x, y)
            time.sleep(random.uniform(0.007, 0.018))
        self._mouse_x, self._mouse_y = tx, ty

    # ------------------------------------------------------------------
    # Hold simulation
    # ------------------------------------------------------------------

    def _hold_via_locator(self, page: Page, iframe_el) -> float:
        """
        Preferred: use Playwright's element-level click(delay=) on the
        hold button inside the iframe.  Works when the iframe is reachable
        (same-origin or accessible via content_frame()).
        Returns hold duration in ms, or 0 if unavailable.
        """
        try:
            frame = iframe_el.content_frame()
            if frame is None:
                return 0
            # PX renders a single pill-shaped hold button — it is always
            # the first sizeable interactive element in the frame body.
            candidates = frame.query_selector_all("div, button, a")
            for el in candidates:
                box = el.bounding_box()
                if box and box["width"] > 40 and box["height"] > 20:
                    hold_ms = random.randint(HOLD_MS_MIN, HOLD_MS_MAX)
                    el.click(delay=hold_ms, force=True, no_wait_after=True,
                             timeout=hold_ms + 3000)
                    return hold_ms
        except Exception:
            pass
        return 0

    def _hold_via_mouse(self, page: Page, cx: float, cy: float) -> float:
        """
        Fallback: raw CDP mouse events at the given viewport coordinates.
        page.mouse.down() fires trusted mousedown + pointerdown via CDP.
        No dispatchEvent() — that creates isTrusted=false which PX rejects.
        """
        hold_s   = random.uniform(HOLD_MS_MIN, HOLD_MS_MAX) / 1000
        deadline = time.time() + hold_s

        page.mouse.move(cx, cy)
        time.sleep(random.uniform(0.08, 0.15))

        page.mouse.down()   # CDP → isTrusted=true mousedown + pointerdown

        while time.time() < deadline:
            jx = cx + random.gauss(0, JITTER_PX / 2)
            jy = cy + random.gauss(0, JITTER_PX / 2)
            page.mouse.move(jx, jy)
            time.sleep(JITTER_INTERVAL + random.uniform(-0.02, 0.02))

        page.mouse.move(cx, cy)
        time.sleep(random.uniform(0.03, 0.07))

        page.mouse.up()     # CDP → isTrusted=true mouseup + pointerup

        self._mouse_x, self._mouse_y = cx, cy
        return hold_s * 1000

    # ------------------------------------------------------------------
    # Windows notification helper
    # ------------------------------------------------------------------

    @staticmethod
    def _notify(title: str, msg: str):
        try:
            subprocess.Popen([
                "powershell", "-WindowStyle", "Hidden", "-Command",
                "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
                "$n=New-Object System.Windows.Forms.NotifyIcon;"
                "$n.Icon=[System.Drawing.SystemIcons]::Warning;"
                "$n.Visible=$true;"
                f"$n.BalloonTipTitle='{title}';"
                f"$n.BalloonTipText='{msg}';"
                "$n.BalloonTipIcon='Warning';"
                "$n.ShowBalloonTip(15000);"
                "Start-Sleep 17; $n.Dispose()"
            ], creationflags=0x08000000)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Full solve loop
    # ------------------------------------------------------------------

    def solve(self, page: Page, max_attempts: int = 2, log=None) -> bool:
        """
        Attempts to solve the PerimeterX hold challenge.

        Flow:
        1. Wait for the interactive iframe to appear (up to IFRAME_WAIT_S seconds).
           If it never appears → hard-block, can't auto-solve, return False.
        2. Move naturally to the iframe centre, press-and-hold.
        3. Wait for page to reload past the challenge.
        4. If still challenged after max_attempts, return False.

        Keeping max_attempts LOW (default 2) is crucial:
        every failed attempt hardens the PX block.
        """
        def _log(msg):
            if log:   log(msg)
            else:     print(msg, flush=True)

        try:
            page.mouse.move(self._mouse_x, self._mouse_y)
        except Exception:
            pass

        for attempt in range(1, max_attempts + 1):
            _log(f"PX Solver: ניסיון {attempt}/{max_attempts} — ממתין לטעינת ה-challenge...")

            # Step 1: wait for the interactive iframe (not just the outer div)
            box = self._wait_for_iframe(page, timeout_s=IFRAME_WAIT_S)

            if box is None:
                # Hard-block: PX is not serving the interactive challenge.
                # Retrying will only make things worse.
                _log("PX Solver: ✗ hard-block — ה-iframe לא נטען (PX חסם את ה-IP/session).")
                _log("           פתח את madlan.co.il בדפדפן ידנית ופתור CAPTCHA.")
                self._notify(
                    "מדלן — CAPTCHA (hard block)",
                    "PerimeterX חסם את הסשן. פתח Chrome ב-madlan.co.il ופתור ידנית."
                )
                return False

            cx = box["x"] + box["width"]  / 2
            cy = box["y"] + box["height"] / 2
            _log(f"PX Solver: iframe נמצא ב-({cx:.0f}, {cy:.0f}), גודל={box['width']:.0f}×{box['height']:.0f}")

            # Step 2: approach naturally then hold
            self._move_to(page, cx, cy)
            time.sleep(random.uniform(0.15, 0.35))

            # Prefer element-level click(delay=) inside the frame (most correct).
            # Fall back to raw mouse coordinates if frame is not accessible.
            try:
                iframe_el = page.query_selector("#px-captcha iframe")
            except Exception:
                iframe_el = None

            if iframe_el:
                held_ms = self._hold_via_locator(page, iframe_el)
            else:
                held_ms = 0

            if not held_ms:
                _log("PX Solver: frame לא נגיש — משתמש ב-mouse coordinates")
                held_ms = self._hold_via_mouse(page, cx, cy)

            _log(f"PX Solver: הוחזק {held_ms:.0f}ms")

            # Step 3: wait for redirect / cookie set
            time.sleep(2.0)
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass

            if not self.challenge_active(page):
                _log("PX Solver: ✓ עבר בהצלחה!")
                return True

            _log("PX Solver: עדיין בדף ה-CAPTCHA...")
            if attempt < max_attempts:
                wait = random.uniform(8, 14)   # longer wait between retries
                _log(f"PX Solver: ממתין {wait:.0f}s לפני ניסיון {attempt + 1}...")
                time.sleep(wait)

        _log("PX Solver: נכשל — מודיע למשתמש")
        self._notify(
            "מדלן — CAPTCHA לא נפתר",
            "פתח Chrome ב-madlan.co.il, פתור CAPTCHA ידנית, ואז הסריקה תמשיך."
        )
        return False
