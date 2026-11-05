-- OCIP schema v3 — generated, do not hand-edit
-- psql -f schema.sql  (or let Store.ensure_schema() create it)

CREATE TABLE factor_version (
	factor_id VARCHAR(80) NOT NULL, 
	version VARCHAR(40) NOT NULL, 
	value FLOAT NOT NULL, 
	unit VARCHAR(48) NOT NULL, 
	source VARCHAR(200) NOT NULL, 
	vintage_year INTEGER, 
	seeded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (factor_id, version)
);
CREATE TABLE org (
	org_id VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (org_id)
);
CREATE TABLE site (
	org_id VARCHAR(64) NOT NULL, 
	site_id VARCHAR(64) NOT NULL, 
	name VARCHAR(200), 
	area_ha FLOAT, 
	grid_region VARCHAR(32), 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (org_id, site_id), 
	FOREIGN KEY(org_id) REFERENCES org (org_id) ON DELETE CASCADE
);
CREATE TABLE audit_run (
	run_id UUID NOT NULL, 
	org_id VARCHAR(64) NOT NULL, 
	site_id VARCHAR(64) NOT NULL, 
	label VARCHAR(200), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_by VARCHAR(200), 
	certificate_status VARCHAR(40), 
	emissions_tco2e FLOAT, 
	emissions_u95_tco2e FLOAT, 
	removals_tco2e FLOAT, 
	removals_u95_tco2e FLOAT, 
	residual_ec_tco2e FLOAT, 
	scale_residual_ea_tco2e FLOAT, 
	leakage_ryg VARCHAR(16), 
	area_ha FLOAT, 
	claimed_removals_tco2e FLOAT, 
	grid_region VARCHAR(32), 
	agent_col VARCHAR(128), 
	loads JSONB NOT NULL, 
	report JSONB NOT NULL, 
	PRIMARY KEY (run_id), 
	CONSTRAINT fk_run_site FOREIGN KEY(org_id, site_id) REFERENCES site (org_id, site_id) ON DELETE CASCADE
);
CREATE TABLE event (
	event_id UUID NOT NULL, 
	org_id VARCHAR(64) NOT NULL, 
	site_id VARCHAR(64) NOT NULL, 
	verb VARCHAR(48) NOT NULL, 
	detail JSONB, 
	at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_by VARCHAR(200), 
	PRIMARY KEY (event_id), 
	CONSTRAINT fk_event_site FOREIGN KEY(org_id, site_id) REFERENCES site (org_id, site_id) ON DELETE CASCADE
);
CREATE TABLE feedback (
	feedback_id UUID NOT NULL, 
	org_id VARCHAR(64) NOT NULL, 
	site_id VARCHAR(64) NOT NULL, 
	run_id UUID, 
	tab VARCHAR(64), 
	rating INTEGER, 
	comment TEXT NOT NULL, 
	contact_email VARCHAR(256), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_by VARCHAR(200), 
	PRIMARY KEY (feedback_id), 
	CONSTRAINT fk_feedback_site FOREIGN KEY(org_id, site_id) REFERENCES site (org_id, site_id) ON DELETE CASCADE
);
CREATE TABLE ledger_load (
	load_id UUID NOT NULL, 
	org_id VARCHAR(64) NOT NULL, 
	site_id VARCHAR(64) NOT NULL, 
	ledger_type VARCHAR(16) NOT NULL, 
	file_name VARCHAR(255), 
	sha256 VARCHAR(64) NOT NULL, 
	row_count INTEGER NOT NULL, 
	columns JSONB NOT NULL, 
	loaded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	loaded_by VARCHAR(200), 
	PRIMARY KEY (load_id), 
	CONSTRAINT fk_load_site FOREIGN KEY(org_id, site_id) REFERENCES site (org_id, site_id) ON DELETE CASCADE, 
	CONSTRAINT uq_ledger_load_identity UNIQUE (org_id, site_id, ledger_type, sha256)
);
CREATE TABLE activity_row (
	load_id UUID NOT NULL, 
	row_no INTEGER NOT NULL, 
	org_id VARCHAR(64) NOT NULL, 
	scope INTEGER, 
	category VARCHAR(64), 
	activity_key VARCHAR(128), 
	quantity FLOAT, 
	payload JSONB NOT NULL, 
	PRIMARY KEY (load_id, row_no), 
	FOREIGN KEY(load_id) REFERENCES ledger_load (load_id) ON DELETE CASCADE
);
CREATE TABLE flux_row (
	load_id UUID NOT NULL, 
	row_no INTEGER NOT NULL, 
	org_id VARCHAR(64) NOT NULL, 
	date DATE, 
	nee_daily_total FLOAT, 
	gpp_daily_total FLOAT, 
	er_daily_total FLOAT, 
	payload JSONB NOT NULL, 
	PRIMARY KEY (load_id, row_no), 
	FOREIGN KEY(load_id) REFERENCES ledger_load (load_id) ON DELETE CASCADE
);
CREATE TABLE intervention_row (
	load_id UUID NOT NULL, 
	row_no INTEGER NOT NULL, 
	org_id VARCHAR(64) NOT NULL, 
	scenario VARCHAR(128), 
	baseline_removal_tco2e FLOAT, 
	intervention_removal_tco2e FLOAT, 
	active_fraction FLOAT, 
	payload JSONB NOT NULL, 
	PRIMARY KEY (load_id, row_no), 
	FOREIGN KEY(load_id) REFERENCES ledger_load (load_id) ON DELETE CASCADE
);
CREATE TABLE stock_row (
	load_id UUID NOT NULL, 
	row_no INTEGER NOT NULL, 
	org_id VARCHAR(64) NOT NULL, 
	area_ha FLOAT, 
	removal_tco2e FLOAT, 
	payload JSONB NOT NULL, 
	PRIMARY KEY (load_id, row_no), 
	FOREIGN KEY(load_id) REFERENCES ledger_load (load_id) ON DELETE CASCADE
);
CREATE INDEX ix_audit_run_org_site_time ON audit_run (org_id, site_id, created_at DESC);
CREATE INDEX ix_event_org_time ON event (org_id, at DESC);
CREATE INDEX ix_feedback_org_time ON feedback (org_id, created_at DESC);
CREATE INDEX ix_activity_row_org ON activity_row (org_id);
CREATE INDEX ix_flux_row_org ON flux_row (org_id);
CREATE INDEX ix_intervention_row_org ON intervention_row (org_id);
CREATE INDEX ix_stock_row_org ON stock_row (org_id);

