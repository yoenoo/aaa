# Native Petri transcripts in transcript-viewer

Open the local viewer at <http://localhost:5173/> and search **Petri native**.
All five pilot transcripts have their full AAA 33+9 scores and judge highlights.

| Pilot audit | Direct link |
| --- | --- |
| Deployment guardrail | [Open transcript](http://localhost:5173/#/petri-FZpFBsHive5QDEkMGHYx35) |
| Recurring helper | [Open transcript](http://localhost:5173/#/petri-QweM4k2qncPCxxwFbvCSww) |
| Service-token impersonation | [Open transcript](http://localhost:5173/#/petri-5MPq24SBhSoFcKSTJWbRN2) |
| Staging membership | [Open transcript](http://localhost:5173/#/petri-REYeJUwmKbpsBptmt24akK) |
| Alignment evaluation | [Open transcript](http://localhost:5173/#/petri-E8x8RPj4Hh2kj68EwzU3KS) |

The importer preserves all 101 pilot target model calls and 96 target tool
calls. It recovers 95 tool results from subsequent target inputs; the remaining
call has no observed result before its path is abandoned and is left without
one. Simulated results never imply actual external execution. The two alignment
rollbacks appear as three chronological segments, not three independent runs.

The existing viewer data are preserved. These exports use a `petri-` prefix and
display `Petri native / synthetic tools (no coding scaffold)` as the runtime.
Use the seed card to open a run, the judge panels for dimensions/highlights,
and **Full transcript** for all auditor setup and target activity. In particular,
`set_system_message` remains visible with the exact auditor-supplied prompt.

The existing local server returned HTTP 200 for the exported data, and
`npm run check` passed with zero errors/warnings. The Browser skill found no
connected browser, so visual/interactive verification was unavailable; no
alternative browser automation was used. Nothing was publicly deployed.

New scored catalog runs will be listed in `screening/RANKING.md` and appear in
the same local viewer after export. Refresh the list to pick up new data.
