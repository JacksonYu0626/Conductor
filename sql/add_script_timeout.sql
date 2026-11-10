/*
Adds a per-script timeout to Conductor.
Run once in the Conductor database. Safe to re-run.
Update schema name if your .env CONDUCTOR_DB_SCHEMA is not MPMC.

timeout_sec = NULL  -> script uses the default 1 hour (3600 seconds)
Allowed range       -> 300 (5 minutes) to 43200 (12 hours)
Ignored for script_type = 'app' (apps have no timeout)
*/

IF COL_LENGTH('MPMC.scripts', 'timeout_sec') IS NULL
    ALTER TABLE MPMC.scripts ADD timeout_sec INT NULL;
GO

/* Example: give the claims script 8 hours (find its id in MPMC.scripts first)
UPDATE MPMC.scripts SET timeout_sec = 28800 WHERE id = <script_id>;
*/
