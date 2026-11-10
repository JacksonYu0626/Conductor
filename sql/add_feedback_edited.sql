/*
MPM Conductor - "edited" marker for feedback and comments.

Run once in the Conductor database (schema MPMC), after add_collaboration.sql.
Safe to re-run: each step checks first. Only adds two nullable columns;
existing rows are unchanged (NULL = never edited). Times are stored in UTC.
*/

IF COL_LENGTH('MPMC.feedback', 'edited_at') IS NULL
    ALTER TABLE MPMC.feedback ADD edited_at DATETIME2 NULL;
GO
IF COL_LENGTH('MPMC.feedback_comments', 'edited_at') IS NULL
    ALTER TABLE MPMC.feedback_comments ADD edited_at DATETIME2 NULL;
GO

/* Check: should return 2 rows. */
SELECT OBJECT_NAME(object_id) AS table_name, name AS new_column FROM sys.columns
WHERE name = 'edited_at' AND object_id IN (OBJECT_ID('MPMC.feedback'), OBJECT_ID('MPMC.feedback_comments'));
