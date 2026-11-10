# What's new in Conductor

## 2026.11.06
- **Failed runs now say why.** When a script ends with an error code but prints no error, Conductor explains it
  instead of leaving the error empty, e.g. "Python crashed (access violation). This is often caused by Excel/COM
  automation…", or "The script stopped itself with exit code 1". This shows in the run log, the Test run console
  and the failure email.
- **Crash details.** If Python itself crashes (often inside Excel/COM or a database driver), the error now shows
  which line of the script it was on. Scripts don't need any change for this.
- **Version and What's new** at the bottom of the sidebar, under your name. When a newer version is running, a
  card at the top of the page asks you to **Refresh** (or **Later**).

## 2026.10.26
- **Share schedules.** On your own schedules, **Share** lets you add teammates as **Can edit** (change settings,
  run now, pause, stop, see its runs) or **Can view** (see it, its runs and logs). Only you or an admin can delete
  it or share it further.
  - People get an email when access is given, changed or removed, with an **Open in Conductor** button.
  - Newly shared schedules show a **New** tag, a banner and a count on Schedules in the sidebar until opened.
  - Your shared schedules show "Shared with Priya +2"; hover to see everyone and their access.
- **Feedback board.** Everyone sees all feedback. Upvote items and comments, comment, and edit or delete your own
  (shown as "· edited"). Admins set the status.
- **Run history.** A "When runs happen" heatmap (weekday × hour, Pacific time) replaces the 14-day chart; click a
  cell to see only those runs. The table loads one page at a time (25 / 50 / 100 rows) and the counts are exact.
- **Summary.** "Runs over time" shows successful runs above the line and failed runs below it, so a single failure
  is easy to spot. Needs attention and Up next are always the same height; "All failing (N)" when more than 5 fail.
- **Schedules.** A "Last 12 hours · next 12 hours" strip replaces "Next 24 hours" and the Timeline view: past runs
  by result, coming-up runs in grey, and a numbered bubble when several run at once. Rows stay the same height.
- Register buttons fit their text; the Share window opens at its final size.

## 2026.10.21
- Smoother welcome → app transition.
- My profile is full width; the page no longer shifts when switching views.
- Run history: type pills, name search and status filters that also drive the chart.
- Library: filters line up on every page.
