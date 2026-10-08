# Mobile network watcher resource ownership

## Confirmed defect

The long-running `scripts/start-mobile-web.ps1` watcher probes the LAN every five
seconds. Its `Get-TinkroMobileLanAddress` helper called `Get-NetIPConfiguration`
without a CIM session. The installed Windows implementation creates a persistent
`New-CimSession` in this case and does not remove it. A separate read-only process
reproduced six retained sessions after six calls, including after GC/finalizers.

The existing watcher (PID 41288, started October 5) had approximately 4.2 GiB of
private committed memory, 530 MiB resident working set, and 24,000 handles. These
are different memory measures; the private allocation is not all resident RAM.
No heap dump was collected and memory fragmentation was not established.

## Fix

- Each real probe explicitly creates one owned CIM session and supplies it to
  both the IP configuration and adapter queries.
- `finally` removes exactly that session, including after a query failure.
- Query failures are terminating so the existing watcher reports `probe_failed`
  and retains its healthy gateway instead of treating partial data as offline.
- Fully injected adapter/configuration inputs create no session. Partial inputs
  only query the missing data. Caller-owned sessions are never enumerated for
  cleanup or removed.
- Network priority, gateway ownership, debounce, TLS, media transport, frame
  buffers, and Pi behavior are unchanged.

## Verification

50 checks/executions including the deliberate pre-fix failure:

| Check | Count | Result |
| --- | ---: | --- |
| New ownership regression before fix | 1 | Expected failure |
| Mocked ownership/error/injected-input scenarios | 7 | Passed |
| Existing network, gateway ownership, TLS and rollback assertions | 38 | Passed |
| Native Windows adapter queries in an isolated process | 4 | Passed |

The four native queries each preserved the one caller-owned session and left no
probe session behind. After explicit cleanup of the caller session, session count
was zero. This is bounded leak regression evidence, not a long-duration heap
stability claim. The isolated process exited; the live watcher was not stopped.

The existing suite creates and removes only its validated unique temporary test
directory, using synthetic certificates and fake gateway processes. No active
phone, production certificate, Pi operation, or live gateway was replaced.
Scoped `git diff --check` passed (only the repository's LF/CRLF warning).

## Deployment and remaining stream investigation

After explicit user authorization, restarted only the verified network watcher
tree and its owned HTTPS gateway on October 6 at 13:15 Asia/Taipei. The old
watcher PID 41288 and gateway PID 37556 exited. New watcher PID 33568 and gateway
PID 27532 are running. Backend PID 14492 retained its original 12:50:23 start
time; no Pi command or backend restart was performed.

The new watcher measured 106.61 MiB private committed memory, 194.45 MiB resident
working set and 945 handles after startup, compared with about 4.2 GiB private
memory / 24,000 handles in the old watcher. This is a post-restart observation,
not long-duration acceptance. Its log progressed from `confirming` to `started`
to `unchanged`, with an empty watcher error log.

Desktop root, phone HTTPS `/mobile`, and the proxied `/api/mobile/web-ca` returned
200. Phone HTTPS was verified against the existing local CA with hostname
verification enabled; OS trust settings and certificates were not changed. The
old phone stream is now inactive and needs to be reopened from the phone.

A pre-restart read-only snapshot still showed the same phone stream generation 4,
1280 x 720, about 30 FPS received, target bitrate 44 kbps, RTT 9 ms, no packet
loss, and no jitter-buffer overflow. Low target bitrate alone does not prove the
remaining stall's root cause or establish that this resource leak caused it.
No forced bitrate, larger buffer, artificial memory purge, or resolution fallback
was added. Physical-phone startup/rotation/AI-load acceptance remains outstanding.
