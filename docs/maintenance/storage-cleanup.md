# Storage Cleanup & The Atomic Hardlink Paradox

This guide explains why `/data/usenet` silently fills up over time even after you "delete" media from your library, and how to configure Radarr, Sonarr, and SABnzbd to clean up after themselves automatically.

## The Atomic Hardlink Paradox

Radarr and Sonarr are configured to **hardlink** files from `/data/usenet` (the raw download scratch space) into `/data/media` (the curated library that Jellyfin and Tdarr read from). This is the core trick that makes the stack fast and disk-efficient — no copying, no duplication of bytes.

But hardlinks behave in a way that surprises most users:

- A hardlink is **the same inode** — two (or more) filenames pointing at one single file on disk.
- There is no "original" and no "copy". Both names are equally real.
- Disk space is only reclaimed by the kernel when **all** hardlinks pointing at that inode are removed.

The practical consequence — the paradox:

- Deleting a file from your **Jellyfin / Tdarr library** (`/data/media/...`) does **NOT** free disk space, because the twin hardlink in `/data/usenet/...` still pins the inode.
- Deleting a file from `/data/usenet/...` does **NOT** remove it from your library either, for the same reason.
- Over weeks and months, `/data/usenet` accumulates every download you have ever grabbed, even after upgrades, replacements, and manual library cleanups. The disk silently fills until imports start failing.

The rest of this document is the cure.

## Radarr / Sonarr Fix — Remove Completed

The first and most important setting tells the *arr to remove the download from SABnzbd's tracking (and the raw file from `/data/usenet`) the moment it has been successfully imported into the library. Because the file is hardlinked, the library copy survives — only the redundant scratch-space twin disappears.

1. Open Radarr (and later Sonarr) in your browser.
2. Navigate to **Settings -> Download Clients**.
3. Click **Show Advanced** at the top of the page to reveal hidden options.
4. Toggle **Remove Completed** to **ON**.
5. Save.
6. Repeat the entire procedure in **both Radarr and Sonarr**.

From this point forward, every successful import will clean up its own raw download.

## The Recycle Bin Trap — Media Management

Even with **Remove Completed** enabled, there is a second, hidden source of storage bloat: Radarr/Sonarr's own **Recycle Bin**. When you (or an upgrade event) delete a file from the library, by default it is not actually deleted — it is silently moved to a recycle folder that itself never gets cleaned out. This folder grows forever.

1. Navigate to **Settings -> Media Management -> File Management**.
2. Choose **one** of the following two strategies:
    - **Disable the Recycle Bin entirely:** clear the **Recycle Bin** path field so it is empty. Deletions become immediate and permanent.
    - **Auto-purge quickly:** leave the Recycle Bin path set, but change the **Recycle Bin Cleanup** interval to `1` day so the bin is auto-purged every 24 hours.
3. Save.
4. Repeat in **both Radarr and Sonarr**.

Without one of these two settings, "deleted" media simply migrates to a hidden recycle folder and continues to occupy disk space indefinitely.

## Manual Purge Procedures (Emergencies Only)

If `/data/usenet` has already filled up before you fixed the settings above, you will need to purge it manually. **These actions are destructive and irreversible** — they will not affect your hardlinked library copies in `/data/media`, but any download still mid-import or not yet hardlinked will be lost.

### Host Shell — wipe the completed scratch space

Run on the Docker host (not inside a container):

```bash
sudo rm -rf /data/usenet/completed/*
```

This frees every inode that is no longer pinned by a library hardlink. Files still referenced by `/data/media` remain intact on disk.

### SABnzbd UI — purge tracked history and underlying files

SABnzbd keeps its own history database that references completed downloads. To clear both the records and the files together:

1. Open the SABnzbd web UI.
2. Navigate to **History**.
3. Use **Purge History (with files)**.

This removes SABnzbd's tracked completed downloads **and** deletes the underlying files on disk in one action.

> **Caution:** Both procedures are destructive and cannot be undone. Run them only when you understand which files are still hardlinked into `/data/media` and which are orphaned. When in doubt, fix the automation settings above first and let the system clean itself up on the next import cycle.
