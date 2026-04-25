# MagicLight v2.0 — PLAN

## Goal
Rebuild the pipeline into independent stages coordinated by one Google Sheet workbook.

## Stages
1. **Generate** — reads INPUT tab, automates VideoGen via Playwright, writes to VideoGen tab
2. **Process** — reads VideoGen tab (Trigger=PROCESS), runs FFmpeg, writes to Process tab
3. **Upload** — reads Process tab (Trigger=UPLOAD), uploads to YouTube/Drive, writes to YouTube tab

## Sheet Tabs
| Tab      | Purpose               |
|----------|-----------------------|
| INPUT    | Source of truth (Make.com) |
| VideoGen | Post-generation data  |
| Process  | Post-processing data  |
| YouTube  | Post-upload results   |
| Credits  | Account credit log    |

## ID Format
`YYYYMMDDHHMMSS` — example: `20260425143055`

## File Naming
`{ID}_{slug}.mp4` — example: `20260425143055_my-kids-story.mp4`

## Trigger Chain
```
INPUT Ready → generate.py → VideoGen Trigger=PROCESS
→ process.py → Process Trigger=UPLOAD
→ upload.py → YouTube Done
```
