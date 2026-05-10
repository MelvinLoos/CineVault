# Bazarr — Subtitle Provider & Sync Configuration

Bazarr is the subtitle companion to Radarr and Sonarr in the CineVault stack.
It watches the libraries those two apps manage and pulls down matching
subtitle tracks for each movie or episode. For a **Dutch / English bilingual
household** the defaults are not good enough — Bazarr will happily download
mis-synced WEB-DL subtitles over the top of a perfectly good embedded MKV
track, or grab five copies of the same `.srt` from five different providers.

This page documents the exact UI clicks required to make a fresh Bazarr
deployment produce **accurate, synchronised and deduplicated** subtitles for
NL + EN viewers.

!!! warning "Stateful configuration"
    Everything on this page lives inside Bazarr's own SQLite database
    (`/opt/mediastack/data/bazarr/`). It is **not** managed by Ansible —
    these steps must be performed once via the web UI after the container
    is up.

---

## A. Subtitle Providers

Navigate to **Settings -> Providers** and enable **only** the following stack.
This combination has been tested for English and Dutch coverage across both
movies and TV without burning through any single provider's rate limit.

| Provider              | Account required          | Best for           |
| --------------------- | ------------------------- | ------------------ |
| **OpenSubtitles.com** | Yes (free account)        | General coverage   |
| **Addic7ed**          | Yes (free account)        | TV shows           |
| **Podnapisi**         | No                        | Dutch + EU titles  |
| **YIFY**              | No                        | Movies **only**    |
| **BSPlayer**          | No                        | Fallback / fill-in |

!!! warning "Do NOT enable every provider"
    Bazarr will query every enabled provider for every missing subtitle on
    every search cycle. Enabling the full list in the UI is the single
    fastest way to get your IP **rate-limited or temporarily banned** by
    OpenSubtitles and Addic7ed — both of which enforce strict daily download
    caps on free accounts. Stick to the five providers above.

!!! note "Subscene is dead"
    Subscene was shut down permanently in 2024 and its API no longer
    responds. If you see it listed in the provider dropdown, **do not enable
    it** — it will only generate failed-request log spam. Any older guide
    that recommends Subscene is out of date.

---

## B. Preventing Duplicate Subtitle Downloads

A correctly tagged MKV from a good release group usually already contains
the Dutch and English subtitle tracks embedded inside the container. Without
the settings below, Bazarr will ignore those embedded tracks and download
external `.srt` files anyway — leaving you with **two** copies of the same
subtitle (one inside the MKV, one next to it on disk) and the external sidecar
taking priority in most players.

Navigate to **Settings -> Subtitles** and enable **both** of the following
options:

- **Use Embedded Subtitles** — tells Bazarr to count the MKV's internal
  subtitle tracks as valid coverage for the language profile.
- **Analyze Video Files** — tells Bazarr to actually open each file with
  `ffprobe` on import so it knows which embedded tracks exist in the first
  place. Without this toggle the previous option does nothing, because Bazarr
  has no idea what is inside the MKV.

With both enabled, Bazarr will skip the external download entirely whenever
the MKV already ships with the desired language track, eliminating the
duplicate-subtitle problem at the source.

---

## C. Audio-Based Synchronisation

External subtitles are notoriously mis-timed — a WEB-DL sub applied to a
BluRay release is typically off by several seconds because of the
distributor's intro card, and even "matching" releases drift by 100–500 ms.
Bazarr ships with two waveform-based sync tools that fix this automatically.

Navigate to **Settings -> Subtitles** and configure:

1. Enable **Automatic Subtitles Synchronization**.
2. Select either **alass** or **ffsubsync** as the sync engine.

Both tools are already installed inside the Bazarr container image — there
is nothing to apt-get or pip-install on the host. They work by extracting
the audio waveform of the video file and mathematically aligning the
subtitle timestamps to where speech actually occurs, rather than relying on
the (often wrong) release-name metadata.

!!! note "alass vs. ffsubsync"
    - **alass** is generally faster and handles subtitles with long gaps
      (e.g. silent intros, post-credit scenes) more gracefully.
    - **ffsubsync** is slightly more conservative and a good fallback if
      alass produces an obviously broken result on a specific file.

    Either choice is fine — pick one and stay with it.

---

## D. Language Profiles

Navigate to **Languages -> Profiles** and create a single dual-language
profile called **`NL + EN`**, then assign it to every series in Sonarr and
every movie in Radarr.

Inside the profile, order and configure the languages as follows:

| Order | Language    | Cutoff               |
| ----- | ----------- | -------------------- |
| 1     | **Dutch**   | ✅ (set cutoff here) |
| 2     | English     |                      |

### Why Dutch at the top with the cutoff on Dutch?

Bazarr treats the **cutoff** as "the target language — once this one is
downloaded, stop searching the rest". By placing Dutch first **and** setting
the cutoff on Dutch:

- **English is grabbed immediately** when the file is first imported, because
  it is by far the most likely subtitle to be available on day one of a
  release. You can sit down and watch the episode tonight.
- **Dutch is upgraded in the background** — Bazarr keeps searching for the
  Dutch track on its normal schedule and silently swaps it in once a Dutch
  provider publishes a matching `.srt`. The English copy is kept alongside
  it.
- **Searching stops once Dutch lands.** With the cutoff on Dutch, Bazarr will
  not keep hammering providers indefinitely for a "better" track once the
  preferred language is in place.

The net effect is "watchable right now in English, eventually in Dutch" —
which is exactly the desired bilingual-household behaviour.

---

## E. Minimum Scores

Bazarr scores each subtitle candidate against the video file based on release
group, source (BluRay / WEB-DL / HDTV), resolution, and other metadata. The
default minimum score is low enough that a WEB-DL subtitle will routinely be
applied to a BluRay release, producing a sub that is **several seconds
out of sync** before the audio-sync step even runs.

Navigate to **Settings -> Subtitles** and raise the minimum scores to at
least the following values:

| Content type | Minimum score |
| ------------ | ------------- |
| Movies       | **70**        |
| TV shows     | **80**        |

This forces Bazarr to only accept subtitles where the source / release-group
fingerprint actually matches the video file, preventing out-of-sync WEB-DL
subs from being applied to BluRay rips (and vice versa). Anything that
scores below the threshold is rejected and the search continues until a
properly matched track is found — or, failing that, no track is applied
rather than a wrong one.

Combined with the alass / ffsubsync step in section **C**, this produces
subtitles that are correctly matched to the release **and** waveform-aligned
to the audio, which is as good as automated subtitle delivery gets.
