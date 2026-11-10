/*
MPM Conductor - collaboration features (public feedback + schedule sharing)

Run once in the Conductor database (schema MPMC). Safe to re-run:
every step checks first and skips anything that already exists.
Only ADDS tables and columns - nothing existing is changed or dropped,
so the current version of the app keeps working before and after this runs.

Creates:
  1. MPMC.feedback_comments       comments on a feedback item
  2. MPMC.feedback_votes          upvotes on a feedback item (one per person)
  3. MPMC.feedback_comment_votes  upvotes on a comment (one per person)
  4. MPMC.schedule_shares         who a schedule is shared with (edit or view)
  5. MPMC.schedules + 2 columns   last_edited_by_id, last_edited_at

The Conductor service account needs SELECT, INSERT, UPDATE, DELETE on the
new tables (already covered if it has those rights on the whole MPMC schema).
All times are stored in UTC.
*/

/* 1. Comments on feedback. Deleting a feedback item deletes its comments. */
IF OBJECT_ID('MPMC.feedback_comments', 'U') IS NULL
BEGIN
    CREATE TABLE MPMC.feedback_comments (
        id           INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_feedback_comments PRIMARY KEY,
        feedback_id  INT            NOT NULL,
        user_id      INT            NOT NULL,
        message      NVARCHAR(MAX)  NOT NULL,
        created_at   DATETIME2      NOT NULL CONSTRAINT DF_feedback_comments_created DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_feedback_comments_feedback FOREIGN KEY (feedback_id) REFERENCES MPMC.feedback (id) ON DELETE CASCADE,
        CONSTRAINT FK_feedback_comments_user     FOREIGN KEY (user_id)     REFERENCES MPMC.users (id)
    );
    CREATE INDEX IX_feedback_comments_feedback ON MPMC.feedback_comments (feedback_id, created_at);
END
GO

/* 2. Upvotes on feedback. One row per person per item. */
IF OBJECT_ID('MPMC.feedback_votes', 'U') IS NULL
BEGIN
    CREATE TABLE MPMC.feedback_votes (
        feedback_id  INT        NOT NULL,
        user_id      INT        NOT NULL,
        created_at   DATETIME2  NOT NULL CONSTRAINT DF_feedback_votes_created DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_feedback_votes PRIMARY KEY (feedback_id, user_id),
        CONSTRAINT FK_feedback_votes_feedback FOREIGN KEY (feedback_id) REFERENCES MPMC.feedback (id) ON DELETE CASCADE,
        CONSTRAINT FK_feedback_votes_user     FOREIGN KEY (user_id)     REFERENCES MPMC.users (id)
    );
END
GO

/* 3. Upvotes on comments. One row per person per comment. */
IF OBJECT_ID('MPMC.feedback_comment_votes', 'U') IS NULL
BEGIN
    CREATE TABLE MPMC.feedback_comment_votes (
        comment_id   INT        NOT NULL,
        user_id      INT        NOT NULL,
        created_at   DATETIME2  NOT NULL CONSTRAINT DF_feedback_comment_votes_created DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_feedback_comment_votes PRIMARY KEY (comment_id, user_id),
        CONSTRAINT FK_feedback_comment_votes_comment FOREIGN KEY (comment_id) REFERENCES MPMC.feedback_comments (id) ON DELETE CASCADE,
        CONSTRAINT FK_feedback_comment_votes_user    FOREIGN KEY (user_id)    REFERENCES MPMC.users (id)
    );
END
GO

/* 4. Schedule sharing. access = 'edit' or 'view'. No end date: a row stays
      until the owner removes it. Deleting a schedule deletes its shares. */
IF OBJECT_ID('MPMC.schedule_shares', 'U') IS NULL
BEGIN
    CREATE TABLE MPMC.schedule_shares (
        id            INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_schedule_shares PRIMARY KEY,
        schedule_id   INT          NOT NULL,
        user_id       INT          NOT NULL,
        access        VARCHAR(10)  NOT NULL CONSTRAINT DF_schedule_shares_access DEFAULT 'edit',
        shared_by_id  INT          NOT NULL,
        created_at    DATETIME2    NOT NULL CONSTRAINT DF_schedule_shares_created DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_schedule_shares UNIQUE (schedule_id, user_id),
        CONSTRAINT CK_schedule_shares_access CHECK (access IN ('edit', 'view')),
        CONSTRAINT FK_schedule_shares_schedule  FOREIGN KEY (schedule_id)  REFERENCES MPMC.schedules (id) ON DELETE CASCADE,
        CONSTRAINT FK_schedule_shares_user      FOREIGN KEY (user_id)      REFERENCES MPMC.users (id),
        CONSTRAINT FK_schedule_shares_shared_by FOREIGN KEY (shared_by_id) REFERENCES MPMC.users (id)
    );
    CREATE INDEX IX_schedule_shares_user ON MPMC.schedule_shares (user_id);
END
GO

/* 5. "Last edited by" on schedules. Both NULL until someone edits the
      schedule after this release. (The existing updated_at column also
      changes on every run, so it can't be used for this.) */
IF COL_LENGTH('MPMC.schedules', 'last_edited_by_id') IS NULL
    ALTER TABLE MPMC.schedules ADD last_edited_by_id INT NULL
        CONSTRAINT FK_schedules_last_edited_by FOREIGN KEY REFERENCES MPMC.users (id);
GO
IF COL_LENGTH('MPMC.schedules', 'last_edited_at') IS NULL
    ALTER TABLE MPMC.schedules ADD last_edited_at DATETIME2 NULL;
GO

/* Check: should return 4 tables and 2 columns. */
SELECT name AS created_table FROM sys.tables
WHERE schema_id = SCHEMA_ID('MPMC')
  AND name IN ('feedback_comments', 'feedback_votes', 'feedback_comment_votes', 'schedule_shares');
SELECT name AS new_column FROM sys.columns
WHERE object_id = OBJECT_ID('MPMC.schedules') AND name IN ('last_edited_by_id', 'last_edited_at');
