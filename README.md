# FoxGo / KataGo — Personal Go Studio

A local Go trainer with a browser board, real KataGo analysis, and three connectors: **direct FoxGo TCP, official FoxGTP relay, and calibrated screen vision**. The app never logs into FoxGo itself. FoxGo controls online games through its AI-enabled account interface.

## Start on Windows

Requires Python 3.10+ and a working OpenCL GPU driver. The web server uses only the Python standard library; no npm, Docker, cloud hosting, or Python package installation is required.

```powershell
git clone git@github.com:junyang-zh/foxgo-katago.git
cd foxgo-katago
python scripts/setup_katago.py
python -m trainer.server
```

Open **http://127.0.0.1:8173**, choose **Engine settings → Connect engine**. The installer fills in local paths. `./start.ps1` is an alternative launcher that can also use the Codex bundled Python runtime. Keep the terminal open while using the trainer; Ctrl+C stops the server and engine. Use `--port 8174` if the default port is occupied.

For matches, `./start.ps1 -Background` runs the server independently of the launching terminal. It prints the process ID for stopping it and writes server output to `data/server.stdout.log` and `data/server.stderr.log`. Connect KataGo and start the listener in the panel after launch. If the backend stops, reconnect FoxGo after restarting it; a browser tab alone does not run the engine.

The installer downloads official **KataGo v1.16.4 OpenCL for Windows** and **kata1-b28c512nbt-s13255194368-d5935380940**. This conservative OpenCL build supports the selected model and avoids a separate CUDA/cuDNN installation. The first start tunes GPU kernels and can take several minutes; later starts reuse its cache. On Linux/macOS, install your platform's KataGo build and set the executable/model/config paths manually. Paths with spaces are supported because subprocess arguments are passed as an array, without a shell.

## Local training

- Choose 9×9, 13×13, or 19×19; Chinese or Japanese rules; komi; and 2–9 fixed handicap stones.
- In Engine settings, choose which color KataGo plays, or select manual replies for two-player/review play. Search time and visits limit effort; they are not calibrated ranks.
- Click the board to play. The focused board also accepts arrow keys and Enter. Use Pass, AI move, Undo, Analyze, Score, or Resign.
- Candidate markers show KataGo's top choices. Click a candidate row to preview its principal variation. The numbered preview is an illustrative overlay of up to ten moves, not a separate variation board with capture simulation; the full displayed PV text is authoritative.
- Territory shows predicted ownership, not settled territory or a final score.
- The winrate and 目数 curves always use **Black's perspective**. Positive score means Black leads; candidate rows use the player-to-move perspective. Points lost compare before/after score estimates and can be negative because evaluation is noisy.
- Use the timeline to review any played position and its saved analysis. Review does not modify the live game. Return to **Live** before playing. Undo takes back one move.
- Two passes stop automatic replies; **Score** asks KataGo for a result. Final scoring is an engine estimate, especially when dead stones or unfinished territory remain. In FoxGo, the official client handles acceptance of a scoring result.
- Save an SGF before replacing a game. The current session and analysis automatically persist in `data/session.json`; engine paths/preferences live in `data/settings.json`.
- Without KataGo, two-player local play still supports captures, no suicide, and simple ko. Handicap placement, AI evaluation, and final scoring require KataGo.

## Connect FoxGo directly

```text
FoxGo client (AI-enabled account)
    │  Fox Go AI protocol v1.05, TCP 127.0.0.1:6001
    ▼
Python trainer ── GTP stdin/stdout ── KataGo
    └── browser panel http://127.0.0.1:8173
```

1. Log in to FoxGo with your AI-enabled account.
2. Connect KataGo in the panel, then click **Start listener**. Default port: **6001**. Stop FoxGTP’s listener if it occupies this port.
3. In FoxGo's AI management, connect to **127.0.0.1:6001** (or the selected port). Enable **Use Chinese rules after AI connection** and **Prohibit manual when AI connected**.
4. Start matches in FoxGo. Invitations and adjudication remain in the official client. The panel displays the connection, clocks, confirmed board, pending move, and analysis.
5. Click **Stop listener** to disconnect and return to local practice.

If FoxGo says it is connected but the board is empty, check the connection detail. **FoxGo reports no active game** means the client sent `FASTATUS,0`, not that KataGo is thinking. During your own active match, select your actual color and click **Request game status** to send the documented `AFSTATUS` query. This does not place a move. An active snapshot still needs rules and a turn notice before the trainer can play.

The controller implements checksummed CRLF packets, rules/handicap snapshots, indexed moves, passes, resignation, score requests/results and clocks from the supplied protocol. It accepts one local client. Malformed packets, conflicting moves and index gaps suspend play and request a snapshot. Local edits are locked while listening.

KataGo searches without changing its board. Only FoxGo-confirmed moves are applied. Incoming events cancel an active search so a stale result is not sent. The default one-second reserve reduces the available clock; main-time consumption is tracked between FoxGo clock updates. Search time and visit limits still apply. Stopping online play restores untimed local play.

Online curves contain analysis from AI turns. Reconnection requires fresh rules and a complete snapshot. The 2022 guide does not define pass records in snapshots: ambiguous pass histories are rejected rather than guessed. Same-connection snapshots can retain already-confirmed pass history when all indexed stones match. A fresh game may be necessary after reconnecting a game containing passes.

This implementation targets **Fox Go AI Protocol v1.05 (2022-06-06)**. Automated TCP peers and the installed real KataGo validate the implementation; this is separate from completing a live FoxGo match. Choose the separate FoxGTP connector when using the official relay.

## Official FoxGTP relay

Choose **Official FoxGTP relay** in the TCP connector selector, then start the listener on **8001**. In FoxGTP select **Work → Synchronize AI to FoxClient** and **Communication → TCP/IP: FoxGTP → AI Engine**. Connect its engine side to **127.0.0.1:8001**, and listen for FoxGo on **6001**. FoxGo connects to **127.0.0.1:6001**. Leave common Go byo-yomi unchecked in FoxGTP and reserve one second for transmission. The panel mirrors GTP commands and collects KataGo analysis. This is now part of the main application; the temporary comparison checkout is no longer needed.

## Screen / computer vision connector (Windows)

Install the optional capture dependency using the same Python that starts the trainer:

```powershell
python -m pip install "Pillow>=11.2.1"
python -m trainer.server
```

This connector reads pixels from the standard yellow FoxGo board, recognizes black/white stones, follows legal moves and captures, asks KataGo for a move, and clicks its intersection. It does not require FoxGo to forward TCP game packets. Only one connector can control the board at a time.

1. Stop any TCP listener in the trainer. Disconnect FoxGo's AI TCP connection and disable **Prohibit manual moves when AI connected**. Mouse input must be allowed.
2. Connect KataGo and choose **your AI account's color**, board size and komi in **Screen / computer vision**. Click **Start automatic play** (or **Enable automatic moves**). Both start the same observation loop with automatic play enabled. There is no capture countdown or separate arming step.
3. The connector finds the game window, detects the grid, and continuously captures its contents even behind the trainer panel. Keep FoxGo unminimized. The live preview shows green for empty intersections, blue for black stones, pink for white stones, and red for uncertain readings. If several FoxGo windows are open, use **Find FoxGo** to select one.
4. Start before the first move, or just after Black's opening move. Existing mid-game history and handicap setup cannot be recovered from a screenshot. Three matching observations establish a stable position; subsequent legal moves and captures are tracked automatically.
5. FoxGo is brought forward automatically just before a move, and the position is checked again before clicking. If Windows denies activation, select FoxGo once. Temporary unreadable frames, minimization and an inactive match keep the observer waiting without disabling automatic play. Moving the window is supported; resizing triggers grid detection again.
6. **Hold Escape** or press **Pause clicks** to disarm while observation continues. **Resume automatic moves** resumes immediately. A different game room, inconsistent move history, or an unconfirmed click pauses automatic play. The connector never automatically repeats an unconfirmed click. Stop tracking before changing games.

For an unusual layout, optional manual calibration remains available: stop tracking, find/select FoxGo, **Capture now**, mark the top-left and bottom-right grid intersections, and press **Read calibrated board**. The normal start path does not require these steps.

A click is committed to KataGo only after its stone and captures are seen. A fast opponent reply can confirm both consecutive legal moves. After clicking, the pointer is parked over the title bar to avoid FoxGo's hover marker. Screen polling and three-frame confirmation add about one second; this connector does not read clocks, so use a conservative engine search limit (for example 1–2 seconds) and avoid very fast time controls.

Passes and resignations cannot be reliably inferred from unchanged board pixels. If KataGo recommends either, automatic play pauses and shows the recommendation. Perform the action in FoxGo yourself. For **each actual pass by either player**, pause and click **Confirm a manual pass** to advance the tracked turn; do not use this while a player is merely thinking. After resignation or game end, stop tracking. Scoring and result acceptance remain manual in FoxGo.

Calibration and automatic-play state are session-only. Restarting never resumes automatic clicking. Captured calibration images remain in local process memory and are served only by the local panel. Run the trainer and FoxGo at the same Windows privilege level. The recognizer is tuned for the standard yellow board and Chinese game-window titles; alternate themes/locales need adaptation. It uses confidence thresholds and surrounding-board checks, not a trained OCR model. These checks reduce errors but do not prove screen recognition is perfect.

Validation includes 39 unit tests, automatic grid detection, marker recognition, temporary capture failure recovery, fast replies, cancellation and no-retry behavior. Background capture and stone recognition were checked against the installed FoxGo window at 200% DPI. The installed KataGo also completed a search → simulated click → visual confirmation → engine commit cycle. Completing a live match through native mouse control has not yet been verified.

## Diagnostics and local files

- Enable **GTP / engine detail** for timestamped engine stderr and request/response traces. UI logs retain the latest 300 entries; **Export log** downloads that buffer.
- KataGo writes its detailed logs under `data/katago-logs`. These logs can grow over time.
- `data/install.json` records download URLs and local SHA-256 fingerprints. Downloads use HTTPS; these fingerprints record the installed artifacts, not independent upstream signatures.
- `engines/`, `models/`, `data/`, logs, and credentials are excluded from Git. FoxGTP and the supplied PDF manuals are not redistributed.
- The HTTP and FoxGo sockets bind **only to 127.0.0.1**. The HTTP API checks Host, Origin and a per-run token; there is no CORS access. Do not put the service behind a public reverse proxy. The unauthenticated FoxGo port is intended only for the local FoxGo client.

## Development and verification

```powershell
python -m pip install "Pillow>=11.2.1"  # optional, enables vision tests
python -m unittest discover -s tests -v
node --check web/app.js  # optional JavaScript syntax check
python scripts/smoke_real.py  # requires installed KataGo and model; uses a temporary game
```

`tests/fake_engine.py` is a deterministic protocol fixture used only in tests. The product never substitutes simulated analysis for KataGo. Tests cover board captures/ko, undo, SGF, GTP errors/timeouts/IDs, streaming analysis, save/restore, FoxGo packet framing and online edit locks, and HTTP origin/token/path protection.

Architecture: `trainer/board.py` owns board/history; `gtp.py` frames subprocess requests and parses analysis; `app.py` serializes game operations; `fox.py` implements the direct loopback FoxGo controller; `foxgtp.py` handles the official relay; `vision.py` recognizes/tracks screen moves and `vision_native.py` isolates Windows capture/input; `server.py` serves the browser/API. The UI is plain JavaScript/SVG/CSS in `web/`, so there is no frontend build step. Run from a source checkout; this repository is not packaged as a standalone Python wheel.

The UI optionally registers `read_go_position` and `play_local_go_move` when the experimental `document.modelContext` API exists. Ordinary browsers do not need it. This optional WebMCP surface has not been verified in a browser that implements that API.

## References

- [KataGo upstream](https://github.com/lightvector/KataGo)
- [KataGo GTP extensions](https://github.com/lightvector/KataGo/blob/master/docs/GTP_Extensions.md)
- [Official networks and their licenses](https://katagotraining.org/networks/)
- User-supplied **Fox Go AI Manual v2.01** and **Fox Go AI Protocol v1.05**, dated 2022-06-06. Integration implements the wire protocol directly, as requested, replacing the manual’s relay setup.

KataGo and its networks retain their upstream licenses. This app is an independent personal trainer and is not affiliated with FoxGo or KataGo.
