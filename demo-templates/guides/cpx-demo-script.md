# CPX 2026 Demo Script — Sovereign Cyber Data Lake
## Analytics Track | ~25 Minutes

### Pre-Flight Checklist
- [ ] DemoForge running, template loaded from gallery
- [ ] All 6 containers healthy (3 ES + MinIO + Trino + Metabase)
- [ ] MinIO Console accessible
- [ ] Metabase accessible (dashboards pre-loaded)
- [ ] SOC Demo Queries collection visible in Metabase

---

## The Demo

### Scene 1 — Canvas Overview (0:00–1:00)
**Action:** Show the canvas topology before deploy  
**Talking point:** "What you're looking at is a sovereign cyber data lake. Three source systems — a perimeter firewall, threat intelligence feeds, and a vulnerability scanner — all pushing into a single platform. No SIEM. No proprietary format. Open standards."

### Scene 2 — Deploy + Data Flow (1:00–2:30)
**Action:** Click Deploy. Open the log viewer on "Perimeter Firewall" node  
**Talking point:** "Watch what's happening right now. 500,000 firewall events being ingested into AIStor in real time. The other two nodes are seeding concurrently — threat IOCs and vulnerability scan data."  
*Show: `[firewall_events] Seeding: 200000/500000 rows (40%)`*

### Scene 3 — MinIO Console — Tables (2:30–4:00)
**Action:** Open MinIO Console → analytics-warehouse bucket → browse Iceberg metadata  
**Talking point:** "Here's the Iceberg table metadata. Parquet data files, partition manifests, snapshot history. This is a full Iceberg V3 catalog — built into MinIO AIStor. No Hive metastore. No Glue. No Nessie. Just MinIO."

### Scene 4 — MinIO Console — Objects (4:00–4:30)
**Action:** Navigate to `threat-intel/feeds/stix/` → click a JSON file  
**Talking point:** "And here's something different. STIX 2.1 threat feed bundles — semi-structured JSON. And over here, malware sample binaries. Structured tables and unstructured objects. Same system. Same access policies. Same audit log."

### Scene 5 — Metabase: SOC Overview (4:30–7:30)
**Action:** Open Metabase → SOC Overview dashboard  
**Talking point:** "This dashboard was provisioned automatically when the firewall node started. No manual Metabase setup. The scenario YAML defines the dashboards, and the engine provisions them via the Metabase API during startup."  
*Point out: event volume time series, severity distribution, MITRE tactic breakdown, geographic origin*  
**Q: "Is this real-time?"** "Click refresh. The time series updates. The firewall node is still streaming 25 events per second."

### Scene 6 — Metabase: Threat Intelligence (7:30–9:30)
**Action:** Switch to Threat Intelligence dashboard  
**Talking point:** "Threat actor breakdown. IOC type distribution. Source feed freshness. This is the intelligence layer — cross-referenced with what we're seeing in the firewall logs."

### Scene 7 — Metabase: Vulnerability Posture (9:30–11:30)
**Action:** Switch to Vulnerability Posture dashboard  
**Talking point:** "Your CISO's board report. Severity distribution, top CVEs, remediation status by business unit. All from the same data lake. No separate vulnerability management platform."

### Scene 8 — Demo Query 3: IOC Correlation (11:30–14:00)
**Action:** Navigate to SOC Demo Queries collection → click "3. Connections to known C2 infrastructure"  
**Talking point:** "This is the money shot. Firewall logs joined with threat intelligence — right now, in SQL. Every row is a connection to a known command-and-control server. Threat actor, confidence score, which MITRE tactic, whether it was blocked."  
**Q: "How long does this query take in your current SIEM?"** *[pause]* "This runs in under 2 seconds. On commodity hardware."

### Scene 9 — Demo Queries 4 + 5 (14:00–16:00)
**Action:** Click "4. Threat actor activity summary" → "5. MITRE ATT&CK tactic detections"  
**Talking point:** "Who's attacking us, and what techniques are they using? APT33 — 14% of C2 connections. LockBit — 18%. And here's our block rate by tactic. Exfiltration attempts: 94% blocked. Lateral movement: 67% blocked. This is situational awareness."

### Scene 10 — Demo Query 6: The Priority List (16:00–19:00)
**Action:** Click "6. Highest-risk hosts: unpatched + suspicious traffic"  
**Talking point:** "This is the query that changes the conversation. Not just 'which hosts have vulnerabilities' and not just 'which hosts have suspicious traffic' — but the intersection. Unpatched, high-severity CVEs, AND active C2 connections. This is your patching priority list. This is where you spend the next 72 hours."

### Scene 11 — Demo Query 8: Unstructured → Queryable (19:00–21:00)
**Action:** Click "8. Malware samples by verdict and actor"  
**Talking point:** "Remember those binary files in the malware-vault bucket? They're unstructured. But the metadata is structured — SHA256, sandbox verdict, threat actor attribution, file size. MinIO extracts that via object tags. And suddenly, unstructured binaries are queryable with SQL. That's the AIStor story."

### Scene 12 — Demo Query 10: Live Streaming (21:00–23:00)
**Action:** Click "10. Live data — run this twice to see growth" → note count → wait 30 seconds → run again  
**Talking point:** "Note the count. [wait] Now watch. It went up. The firewall node is still streaming. 25 events per second, continuously appended to the Iceberg table. You can query the latest data at any time. This isn't batch ETL. This is a live data lake."

### Scene 13 — Close (23:00–25:00)
**Action:** Return to MinIO Console — AIStor Tables view  
**Talking point:** "One platform. Structured Iceberg tables and unstructured objects. SQL analytics and pre-built dashboards. A built-in Iceberg catalog — no metastore. Sovereign — your data, your infrastructure, your control. Open standards — Iceberg, Parquet, SQL. And at a fraction of the cost of a SIEM."  
*"That's the Sovereign Cyber Data Lake."*

---

## Common Questions & Answers

**Q: "How does this compare to Splunk / Microsoft Sentinel?"**  
A: "Splunk is proprietary format, proprietary query language, and proprietary pricing that scales with data volume. This is open Iceberg format, standard SQL, and you own the infrastructure. The cost model is completely different."

**Q: "Is this production-ready?"**  
A: "This is MinIO AIStor — the same platform running at [Fortune 500 / government agency]. The demo gives you the full architecture. The containers are the same ones you'd deploy in production."

**Q: "What about compliance and data residency?"**  
A: "Sovereign — meaning the data never leaves your infrastructure. No cloud dependency. No third-party data processing. You control the encryption keys, the access policies, and the audit trail."

**Q: "Can this ingest from our existing SIEM?"**  
A: "Yes. The External System component represents any data source — including your existing SIEM via REST API or S3 export. You'd configure it to pull from your current system while you migrate."

**Q: "How long to deploy this in production?"**  
A: "The DemoForge template you're looking at deploys in 90 seconds. A production deployment on your infrastructure would take days, not months."

---

## Cleanup
1. Click Stop → wait for all containers to stop
2. Click Destroy → confirm volume removal
3. Verify canvas shows "Not Deployed" state
