# 📊 Google Sheet Structure

## Tab Name: `Database`
## Total Columns: 18 (A through R)

| Col | Name | Written By | Description |
|-----|------|-----------|-------------|
| A | `Status` | Both | `Pending` → `Processing` → `Generated` → `Done` / `Error` |
| B | `Theme` | You | Story theme (Friendship, Adventure, etc.) |
| C | `Title` | You | Story title |
| D | `Story` | You | Full story text |
| E | `Moral` | You | Story moral / lesson |
| F | `Gen_Title` | Generate | AI-generated title from MagicLight |
| G | `Gen_Summary` | Generate | AI-generated summary |
| H | `Gen_Tags` | Generate | AI-generated hashtags |
| I | `Drive_Link` | Generate | Raw video Drive link — written after Mode 1 |
| J | `DriveImg_Link` | Generate | Thumbnail Drive link |
| K | `Project_URL` | Generate | MagicLight project URL |
| L | `Credit_Before` | Generate | Credits before generation |
| M | `Credit_After` | Generate | Credits after generation |
| N | `Email_Used` | Generate | Which account was used |
| O | `Notes` | Both | Status notes / error messages |
| P | `Created_Time` | Generate | Generation start timestamp |
| Q | `Completed_Time` | Both | Last completion timestamp |
| R | `Process_D_Link` | Process | Processed video Drive link — written after Mode 2/3 |

## Status Lifecycle

```
Pending
  └─► Processing
        ├─► Generated  (video downloaded, Drive_Link written)
        │     └─► Done  (processed, Process_D_Link written)
        ├─► No_Video   (render done, download failed)
        ├─► Error      (unexpected failure)
        └─► Low Credit (account ran out of credits)
```

## Setup

Run once to write correct headers to your sheet:

```bash
python main.py --migrate-schema
```
