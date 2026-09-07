# FoxGo / KataGo — Personal Go Studio

A local Go trainer with a browser board, real KataGo analysis, and an adapter for the **official FoxGTP relay**. The app never logs into FoxGo itself. FoxGo controls online games through its AI-enabled account interface.

## Start on Windows

Requires Python 3.10+ and a working OpenCL GPU driver. The web server uses only the Python standard library; no npm, Docker, cloud hosting, or Python package installation is required.

```powershell
git clone git@github.com:junyang-zh/foxgo-katago.git
cd foxgo-katago
python scripts/setup_katago.py
python -m trainer.server
```

Open **http://127.0.0.1:8173**, choose **Engine settings → Connect engine**. The installer fills in local paths. `./start.ps1` is an alternative launcher that can also use the Codex bundled Python runtime. Keep the terminal open while using the trainer; Ctrl+C stops the server and engine. Use `--port 8174` if the default port is occupied.

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

## Connect FoxGo using the supplied guide

This implements the guide's **TCP/IP: FoxGTP → AI Engine** mode:

```text
FoxGo client (AI-certified account)
    │  Fox Go AI protocol, TCP 127.0.0.1:6001
    ▼
Official FoxGTP.exe
    │  GTP v2 with command IDs, TCP 127.0.0.1:8001
    ▼
Python trainer bridge ── stdin/stdout ── KataGo
    │
    └── browser panel http://127.0.0.1:8173
```

1. Log in to the installed FoxGo client with an **AI-enabled account**.
2. Connect KataGo in the trainer, then click **Start bridge**. The bridge uses `127.0.0.1:8001` by default and selects Chinese rules. The web panel becomes an observer while the bridge is active.
3. Run `FoxGTP.exe` from the user-supplied package. If it reports missing DLLs, install the package's `Tools/vcredist_x86_2010.exe`.
4. In FoxGTP, choose **Work → Synchronize AI to FoxClient** (同步AI到野狐围棋).
5. Choose **Communication → TCP/IP: FoxGTP → AI Engine**. Enter **127.0.0.1**, port **8001**, and click **Connect** in the engine section.
6. Leave **Use Go common byo-yomi rule** unchecked. FoxGTP then maps each overtime move to Canadian GTP with one stone, which this adapter forwards unchanged. Set **Specify data transfer time** to at least **1 second** to allow for relay overhead.
7. In FoxGTP's **Listen Fox Go Client** section, enter **6001** and start listening. This is a different port from the engine bridge.
8. In FoxGo's **AI management**, enter **127.0.0.1:6001**, enable **Use Chinese rules after AI connection**, and **Prohibit manual when AI connected**. Connect. Verify both relay connections are green and FoxGo shows its connected AI indicator.
9. Start matches using FoxGo's usual AI match controls. The trainer mirrors `clear_board`, `boardsize`, komi, handicap, played moves, and generated moves. FoxGo controls invitations, clocks, adjudication and reconnection.

The trainer's connection badge confirms **FoxGTP**, not the remote FoxGo server. In online mode, search analysis is collected during `genmove`; the adapter sends no extra background review searches that could consume the opponent's clock. Consequently, online curves may contain only positions where KataGo generated a move. Use the timeline to see candidates at those positions.

The bridge preserves FoxGTP's request IDs and blank-line response framing. It accepts one relay client, buffers fragmented/pipelined commands, and serializes every engine operation. On reconnect it requires `clear_board` before moves so the relay can replay a complete game. A GTP timeout or mismatched engine response ID stops the engine rather than risking silent desynchronization. `quit` closes the relay connection while leaving the local trainer available. Stop the bridge before reconnecting/reconfiguring the engine.

Do not connect FoxGo directly to port 8001: FoxGo's proprietary checksummed protocol is handled by official FoxGTP. There is no unofficial screen scraping or mouse-move bot.

## Diagnostics and local files

- Enable **GTP / engine detail** for timestamped engine stderr and request/response traces. UI logs retain the latest 300 entries; **Export log** downloads that buffer.
- KataGo writes its detailed logs under `data/katago-logs`. These logs can grow over time.
- `data/install.json` records download URLs and local SHA-256 fingerprints. Downloads use HTTPS; these fingerprints record the installed artifacts, not independent upstream signatures.
- `engines/`, `models/`, `data/`, logs, and credentials are excluded from Git. FoxGTP and the supplied PDF manuals are not redistributed.
- The HTTP and GTP sockets bind **only to 127.0.0.1**. The HTTP API checks Host, Origin and a per-run token; there is no CORS access. Do not put the service behind a public reverse proxy. The unauthenticated GTP port is intended only for local FoxGTP.

## Development and verification

```powershell
python -m unittest discover -s tests -v
node --check web/app.js  # optional JavaScript syntax check
```

`tests/fake_engine.py` is a deterministic protocol fixture used only in tests. The product never substitutes simulated analysis for KataGo. Tests cover board captures/ko, undo, SGF, GTP errors/timeouts/IDs, streaming analysis, save/restore, FoxGTP TCP framing and online edit locks, and HTTP origin/token/path protection.

Architecture: `trainer/board.py` owns board/history; `gtp.py` frames subprocess requests and parses analysis; `app.py` serializes game operations; `fox.py` implements the loopback relay adapter; `server.py` serves the browser/API. The UI is plain JavaScript/SVG/CSS in `web/`, so there is no frontend build step. Run from a source checkout; this repository is not packaged as a standalone Python wheel.

## References

- [KataGo upstream](https://github.com/lightvector/KataGo)
- [KataGo GTP extensions](https://github.com/lightvector/KataGo/blob/master/docs/GTP_Extensions.md)
- [Official networks and their licenses](https://katagotraining.org/networks/)
- User-supplied **Fox Go AI Manual v2.01** and **Fox Go AI Protocol v1.05**, dated 2022-06-06. Integration follows Manual sections 4.1, 4.4, 4.7 and 5, using the official relay as recommended in Protocol section 1.

KataGo and its networks retain their upstream licenses. This app is an independent personal trainer and is not affiliated with FoxGo or KataGo.
