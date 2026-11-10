/*
Conductor performance indexes for SQL Server production.
Run once in the Conductor database. Safe to re-run.
Update schema name if your .env CONDUCTOR_DB_SCHEMA is not MPMC.
*/

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_run_logs_started_at' AND object_id = OBJECT_ID('MPMC.run_logs'))
    CREATE INDEX ix_run_logs_started_at ON MPMC.run_logs (started_at DESC);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_run_logs_status_started' AND object_id = OBJECT_ID('MPMC.run_logs'))
    CREATE INDEX ix_run_logs_status_started ON MPMC.run_logs (status, started_at DESC);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_run_logs_type_started' AND object_id = OBJECT_ID('MPMC.run_logs'))
    CREATE INDEX ix_run_logs_type_started ON MPMC.run_logs (log_type, started_at DESC);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_run_logs_script_started' AND object_id = OBJECT_ID('MPMC.run_logs'))
    CREATE INDEX ix_run_logs_script_started ON MPMC.run_logs (script_id, started_at DESC);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_run_logs_schedule_started' AND object_id = OBJECT_ID('MPMC.run_logs'))
    CREATE INDEX ix_run_logs_schedule_started ON MPMC.run_logs (schedule_id, started_at DESC);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_run_logs_owner_started' AND object_id = OBJECT_ID('MPMC.run_logs'))
    CREATE INDEX ix_run_logs_owner_started ON MPMC.run_logs (owner_id, started_at DESC);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_schedules_owner_type' AND object_id = OBJECT_ID('MPMC.schedules'))
    CREATE INDEX ix_schedules_owner_type ON MPMC.schedules (owner_id, schedule_type);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_schedules_script_active' AND object_id = OBJECT_ID('MPMC.schedules'))
    CREATE INDEX ix_schedules_script_active ON MPMC.schedules (script_id, is_active);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_schedules_dashboard_active' AND object_id = OBJECT_ID('MPMC.schedules'))
    CREATE INDEX ix_schedules_dashboard_active ON MPMC.schedules (dashboard_id, is_active);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_schedules_sp_site_active' AND object_id = OBJECT_ID('MPMC.schedules'))
    CREATE INDEX ix_schedules_sp_site_active ON MPMC.schedules (sharepoint_site_id, is_active);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_scripts_owner_active' AND object_id = OBJECT_ID('MPMC.scripts'))
    CREATE INDEX ix_scripts_owner_active ON MPMC.scripts (owner_id, is_active);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_dashboards_owner_active' AND object_id = OBJECT_ID('MPMC.dashboards'))
    CREATE INDEX ix_dashboards_owner_active ON MPMC.dashboards (owner_id, is_active);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_sharepoint_sites_owner_active' AND object_id = OBJECT_ID('MPMC.sharepoint_sites'))
    CREATE INDEX ix_sharepoint_sites_owner_active ON MPMC.sharepoint_sites (owner_id, is_active);

-- Additional indexes for Summary filters and SharePoint/Schedule list counts
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_run_logs_log_type_started_at' AND object_id = OBJECT_ID('MPMC.run_logs'))
    CREATE NONCLUSTERED INDEX IX_run_logs_log_type_started_at
    ON MPMC.run_logs (log_type, started_at DESC);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_run_logs_log_type_status_started_at' AND object_id = OBJECT_ID('MPMC.run_logs'))
    CREATE NONCLUSTERED INDEX IX_run_logs_log_type_status_started_at
    ON MPMC.run_logs (log_type, status, started_at DESC);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_schedules_sharepoint_site_id_is_active' AND object_id = OBJECT_ID('MPMC.schedules'))
    CREATE NONCLUSTERED INDEX IX_schedules_sharepoint_site_id_is_active
    ON MPMC.schedules (sharepoint_site_id, is_active);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_schedules_script_id_is_active' AND object_id = OBJECT_ID('MPMC.schedules'))
    CREATE NONCLUSTERED INDEX IX_schedules_script_id_is_active
    ON MPMC.schedules (script_id, is_active);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_schedules_dashboard_id_is_active' AND object_id = OBJECT_ID('MPMC.schedules'))
    CREATE NONCLUSTERED INDEX IX_schedules_dashboard_id_is_active
    ON MPMC.schedules (dashboard_id, is_active);
